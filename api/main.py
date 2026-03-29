"""
main.py — FastAPI Backend Server
==================================
REST + WebSocket API bridging the data layer (Redis + TimescaleDB)
and the React frontend. Serves live stats, historical data, and
AI-generated commentary. Handles concurrent WebSocket connections
via asyncio for sub-second push latency.

Endpoints:
  GET  /stats/live                → Latest stats from Redis
  GET  /stats/history?seconds=60  → Historical stats from TimescaleDB
  GET  /commentary/latest         → 10 most recent AI commentary lines
  GET  /health                    → Component health checks
  WS   /ws/live                   → Persistent WebSocket: pushes every 1s
  GET  /players/{name}/stats      → Player historical profile

Run:
    uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest
from starlette.responses import PlainTextResponse

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [API] %(message)s")
logger = logging.getLogger(__name__)

# ── Config (load from env in production) ─────────────────────────────────────
TIMESCALE_DSN = "postgresql://analytics_user:changeme@192.168.1.15:5432/sports_analytics"
REDIS_URL = "redis://:changeme@192.168.1.14:6379"
CORS_ORIGINS = ["http://192.168.1.12:3000", "http://localhost:3000"]
WS_PUSH_INTERVAL = 1.0  # seconds

# ── Prometheus Metrics ────────────────────────────────────────────────────────
REQUEST_COUNT = Counter("api_requests_total", "Total API requests", ["method", "endpoint"])
REQUEST_LATENCY = Histogram("api_request_latency_seconds", "API request latency", ["endpoint"])
WS_CONNECTIONS = Counter("ws_connections_total", "WebSocket connections opened")

# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Sports Analytics API",
    description="Real-time sports analytics and AI commentary backend",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── App-level State ───────────────────────────────────────────────────────────
class AppState:
    db_pool: Optional[asyncpg.Pool] = None
    redis: Optional[aioredis.Redis] = None
    active_ws_connections: set[WebSocket] = set()


state = AppState()


@app.on_event("startup")
async def startup():
    state.db_pool = await asyncpg.create_pool(TIMESCALE_DSN, min_size=5, max_size=20)
    state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    logger.info("Database pool and Redis connection initialised.")


@app.on_event("shutdown")
async def shutdown():
    if state.db_pool:
        await state.db_pool.close()
    if state.redis:
        await state.redis.close()


# ── REST Endpoints ────────────────────────────────────────────────────────────
@app.get("/stats/live")
async def get_live_stats():
    """
    Returns the latest aggregated match stats from Redis.
    Sub-millisecond response time — suitable for polling fallback if WebSocket fails.
    """
    REQUEST_COUNT.labels(method="GET", endpoint="/stats/live").inc()
    raw = await state.redis.get("latest_stats")
    if not raw:
        return JSONResponse({"error": "No live data yet. Is Spark running?"}, status_code=503)
    return json.loads(raw)


@app.get("/stats/history")
async def get_stats_history(seconds: int = 60):
    """
    Returns historical processed stats from TimescaleDB for chart initialisation.
    Called once on page load.

    Query uses TimescaleDB hypertable time-bucketing for efficient range scans.
    """
    REQUEST_COUNT.labels(method="GET", endpoint="/stats/history").inc()
    async with state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time_bucket('5 seconds', window_start) AS bucket,
                   player,
                   AVG(avg_serve_speed) AS avg_speed,
                   SUM(ace_count) AS aces
            FROM processed_stats
            WHERE window_start > NOW() - INTERVAL '1 second' * $1
            GROUP BY bucket, player
            ORDER BY bucket ASC
            """,
            seconds,
        )
    return [dict(r) for r in rows]


@app.get("/commentary/latest")
async def get_latest_commentary(limit: int = 10):
    """Returns the N most recent AI-generated commentary lines."""
    REQUEST_COUNT.labels(method="GET", endpoint="/commentary/latest").inc()
    async with state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT timestamp, event_id, commentary_text, latency_ms
            FROM ai_commentary
            ORDER BY timestamp DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


@app.get("/players/{name}/stats")
async def get_player_stats(name: str):
    """Returns historical stats for a specific player — used in comparison panel."""
    async with state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT window_start, avg_serve_speed, ace_count, first_serve_pct
            FROM processed_stats
            WHERE player = $1
            ORDER BY window_start DESC
            LIMIT 100
            """,
            name,
        )
    return [dict(r) for r in rows]


@app.get("/health")
async def health_check():
    """Returns health status of all platform components."""
    status = {}

    # Redis check
    try:
        await state.redis.ping()
        status["redis"] = "healthy"
    except Exception as e:
        status["redis"] = f"unhealthy: {e}"

    # TimescaleDB check
    try:
        async with state.db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        status["timescaledb"] = "healthy"
    except Exception as e:
        status["timescaledb"] = f"unhealthy: {e}"

    # TODO: Add Kafka + Spark health checks via JMX or Kafka AdminClient
    status["kafka"] = "unknown"
    status["spark"] = "unknown"
    status["ai_engine"] = "unknown"

    overall = "healthy" if all(v == "healthy" for v in status.values() if v != "unknown") else "degraded"
    return {"overall": overall, "components": status, "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus scrape endpoint — exposes API metrics."""
    return PlainTextResponse(generate_latest().decode())


# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    """
    Persistent WebSocket connection.
    Pushes a combined stats + latest commentary payload every WS_PUSH_INTERVAL seconds.
    Redis pub/sub can also trigger instant pushes on new commentary events.
    """
    await websocket.accept()
    state.active_ws_connections.add(websocket)
    WS_CONNECTIONS.inc()
    logger.info(f"WS connected. Active: {len(state.active_ws_connections)}")

    try:
        while True:
            # Fetch stats from Redis (< 1ms)
            stats_raw = await state.redis.get("latest_stats")
            stats = json.loads(stats_raw) if stats_raw else {}

            # Fetch latest 3 commentary lines from DB
            async with state.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT commentary_text, timestamp FROM ai_commentary "
                    "ORDER BY timestamp DESC LIMIT 3"
                )
            commentary = [
                {"text": r["commentary_text"], "timestamp": r["timestamp"].isoformat()}
                for r in rows
            ]

            payload = {
                "type": "update",
                "stats": stats,
                "commentary": commentary,
                "server_time": datetime.now(timezone.utc).isoformat(),
            }
            await websocket.send_json(payload)
            await asyncio.sleep(WS_PUSH_INTERVAL)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    finally:
        state.active_ws_connections.discard(websocket)
