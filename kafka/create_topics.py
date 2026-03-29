#!/usr/bin/env python3
"""
create_topics.py — Kafka Topic Initialisation Script
======================================================
Creates all required Kafka topics with correct partition count and replication
factor. Run this ONCE after the Kafka cluster is healthy.

Usage:
    python create_topics.py

Topics created:
  - tennis-events      (3 partitions, RF=3)
  - f1-telemetry       (3 partitions, RF=3)
  - ai-events          (1 partition,  RF=3)  → significant events for AI engine
  - system-health      (1 partition,  RF=3)  → health-check heartbeats
"""

from kafka import KafkaAdminClient
from kafka.admin import NewTopic
from kafka.errors import TopicAlreadyExistsError

BOOTSTRAP_SERVERS = [
    "192.168.1.12:9092",
    "192.168.1.13:9092",
    "192.168.1.14:9092",
]

TOPICS = [
    NewTopic(name="tennis-events",  num_partitions=3, replication_factor=3),
    NewTopic(name="f1-telemetry",   num_partitions=3, replication_factor=3),
    NewTopic(name="ai-events",      num_partitions=1, replication_factor=3),
    NewTopic(name="system-health",  num_partitions=1, replication_factor=3),
]


def create_topics():
    admin = KafkaAdminClient(bootstrap_servers=BOOTSTRAP_SERVERS, client_id="topic-init")
    for topic in TOPICS:
        try:
            admin.create_topics([topic])
            print(f"[✓] Created topic: {topic.name} "
                  f"(partitions={topic.num_partitions}, RF={topic.replication_factor})")
        except TopicAlreadyExistsError:
            print(f"[~] Topic already exists: {topic.name}")
    admin.close()
    print("\n[Done] All topics ready.")


if __name__ == "__main__":
    create_topics()
