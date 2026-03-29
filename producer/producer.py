"""
producer.py — Sports Telemetry Data Generator
==============================================
Simulates live sports data (tennis matches + Formula E telemetry) and publishes
events to Apache Kafka topics. In a production system this would be replaced by
a certified sports-data feed (e.g. Sportradar, Stats Perform, Formula E API).

Kafka Topics targeted:
  - tennis-events   → all tennis serve/point/game events
  - f1-telemetry    → lap-by-lap Formula E data per driver

Run with:
    python producer.py --sport tennis --interval 1.0
    python producer.py --sport f1    --interval 2.0
"""

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timezone

from kafka import KafkaProducer
from kafka.errors import KafkaError

# ── Configuration ──────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP_SERVERS = [
    "192.168.1.12:9092",
    "192.168.1.13:9092",
    "192.168.1.14:9092",
]
TENNIS_TOPIC = "tennis-events"
F1_TOPIC = "f1-telemetry"

TENNIS_PLAYERS = [("Roger Federer", "Rafael Nadal")]
F1_DRIVERS = ["Lewis Hamilton", "Max Verstappen", "Charles Leclerc", "Carlos Sainz"]
TOURNAMENTS = {
    "tennis": ["Australian Open", "Roland Garros", "Wimbledon", "US Open"],
    "f1": ["Monaco E-Prix", "Berlin E-Prix", "São Paulo E-Prix"],
}


# ── Kafka Producer Setup ───────────────────────────────────────────────────────
def create_producer() -> KafkaProducer:
    """Create and return a configured Kafka producer with JSON serialisation."""
    return KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        acks="all",             # Wait for all replicas to acknowledge
        retries=3,              # Retry on transient failures
        linger_ms=10,           # Micro-batch up to 10ms to improve throughput
        compression_type="gzip",
    )


# ── Tennis Event Generator ─────────────────────────────────────────────────────
class TennisEventGenerator:
    """Generates realistic tennis match events with score tracking."""

    SERVE_OUTCOMES = ["ace", "fault", "in_play", "in_play", "in_play"]  # weighted
    POINT_WINNERS = ["server", "returner"]

    def __init__(self, players: tuple[str, str], tournament: str):
        self.players = players
        self.tournament = tournament
        self.match_id = f"match-{uuid.uuid4().hex[:8]}"
        self.set_num = 1
        self.game_num = 1
        self.serving_player_idx = 0
        self.ace_count = {"player_0": 0, "player_1": 0}

    def _generate_serve_speed(self, is_first_serve: bool) -> float:
        """Return serve speed km/h: first serves 175–230, second 140–175."""
        if is_first_serve:
            return round(random.uniform(175, 230), 1)
        return round(random.uniform(140, 175), 1)

    def next_event(self) -> dict:
        is_first_serve = random.random() > 0.35
        outcome = random.choice(self.SERVE_OUTCOMES)
        player_key = f"player_{self.serving_player_idx}"
        player_name = self.players[self.serving_player_idx]

        if outcome == "ace":
            self.ace_count[player_key] += 1

        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "match_id": self.match_id,
            "tournament": self.tournament,
            "player": player_name,
            "opponent": self.players[1 - self.serving_player_idx],
            "event_type": "serve",
            "outcome": outcome,
            "is_first_serve": is_first_serve,
            "speed_kmh": self._generate_serve_speed(is_first_serve),
            "court_position": random.choice(["deuce", "advantage"]),
            "set": self.set_num,
            "game": self.game_num,
            "ace_count": self.ace_count[player_key],
        }
        return event


# ── F1 Telemetry Generator ─────────────────────────────────────────────────────
class F1TelemetryGenerator:
    """Generates per-lap Formula E telemetry for a race session."""

    def __init__(self, circuit: str):
        self.circuit = circuit
        self.race_id = f"race-{uuid.uuid4().hex[:8]}"
        self.lap_counts = {d: 0 for d in F1_DRIVERS}
        self.base_lap_time = 90.0  # seconds

    def next_event(self) -> dict:
        driver = random.choice(F1_DRIVERS)
        self.lap_counts[driver] += 1
        lap = self.lap_counts[driver]

        lap_time = round(self.base_lap_time + random.gauss(0, 1.5), 3)
        tyre_temp = round(random.uniform(75, 105), 1)

        return {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "race_id": self.race_id,
            "circuit": self.circuit,
            "driver": driver,
            "lap": lap,
            "lap_time_seconds": lap_time,
            "speed_kmh": round(random.uniform(200, 280), 1),
            "tyre_temp_celsius": tyre_temp,
            "battery_pct": round(random.uniform(20, 100), 1),
            "gap_to_leader_seconds": round(random.uniform(0, 30), 3),
            "drs_active": random.choice([True, False]),
        }


# ── Main Loop ──────────────────────────────────────────────────────────────────
def run(sport: str, interval: float):
    producer = create_producer()
    print(f"[Producer] Connected to Kafka. Streaming {sport.upper()} events every {interval}s")

    if sport == "tennis":
        players = random.choice(TENNIS_PLAYERS)
        tournament = random.choice(TOURNAMENTS["tennis"])
        generator = TennisEventGenerator(players, tournament)
        topic = TENNIS_TOPIC
    else:
        circuit = random.choice(TOURNAMENTS["f1"])
        generator = F1TelemetryGenerator(circuit)
        topic = F1_TOPIC

    try:
        while True:
            event = generator.next_event()
            future = producer.send(topic, value=event, key=event["event_id"].encode())
            try:
                record_metadata = future.get(timeout=10)
                print(
                    f"[Producer] ✓ topic={record_metadata.topic} "
                    f"partition={record_metadata.partition} "
                    f"offset={record_metadata.offset} | "
                    f"event_type={event.get('event_type', 'lap')} "
                    f"outcome={event.get('outcome', event.get('lap_time_seconds'))}"
                )
            except KafkaError as e:
                print(f"[Producer] ✗ Failed to send: {e}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[Producer] Shutting down gracefully...")
    finally:
        producer.flush()
        producer.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sports Telemetry Kafka Producer")
    parser.add_argument("--sport", choices=["tennis", "f1"], default="tennis")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between events")
    args = parser.parse_args()
    run(args.sport, args.interval)
