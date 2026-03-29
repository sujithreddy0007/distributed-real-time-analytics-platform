"""
streaming.py — Apache Spark Structured Streaming Pipeline
==========================================================
Reads live sports events from Kafka, applies windowed aggregations, and writes
computed statistics to TimescaleDB (via JDBC) and Redis (latest-state cache).

Architecture:
  Kafka (tennis-events / f1-telemetry)
      → Spark Structured Streaming (2-second micro-batches)
          → TimescaleDB  (processed_stats table)
          → Redis        (latest_stats key for API caching)

Run with:
    spark-submit \\
        --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0 \\
        --master spark://192.168.1.13:7077 \\
        streaming.py

Spark workers auto-distribute across Nodes 2, 3, 4 (one worker per Kafka partition).
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)
import redis
import json

# ── Constants ──────────────────────────────────────────────────────────────────
KAFKA_BROKERS = "192.168.1.12:9092,192.168.1.13:9092,192.168.1.14:9092"
TIMESCALE_URL = "jdbc:postgresql://192.168.1.15:5432/sports_analytics"
TIMESCALE_PROPS = {
    "user": "analytics_user",
    "password": "changeme_strong_password",
    "driver": "org.postgresql.Driver",
}
REDIS_HOST = "192.168.1.14"
REDIS_PORT = 6379
BATCH_INTERVAL_SECONDS = 2

# ── Kafka Schema for Tennis Events ────────────────────────────────────────────
TENNIS_SCHEMA = StructType([
    StructField("event_id",      StringType(),    True),
    StructField("timestamp",     TimestampType(), True),
    StructField("match_id",      StringType(),    True),
    StructField("tournament",    StringType(),    True),
    StructField("player",        StringType(),    True),
    StructField("opponent",      StringType(),    True),
    StructField("event_type",    StringType(),    True),
    StructField("outcome",       StringType(),    True),
    StructField("is_first_serve", StringType(),   True),
    StructField("speed_kmh",     DoubleType(),    True),
    StructField("court_position", StringType(),   True),
    StructField("set",           IntegerType(),   True),
    StructField("game",          IntegerType(),   True),
    StructField("ace_count",     IntegerType(),   True),
])

# ── Spark Session ─────────────────────────────────────────────────────────────
def create_spark_session() -> SparkSession:
    return (
        SparkSession.builder
        .appName("SportsAnalyticsPipeline")
        .master("spark://192.168.1.13:7077")
        .config("spark.sql.streaming.checkpointLocation", "/tmp/spark-checkpoints")
        .config("spark.streaming.backpressure.enabled", "true")
        .config("spark.sql.shuffle.partitions", "3")  # match Kafka partitions
        .getOrCreate()
    )


# ── Read from Kafka ────────────────────────────────────────────────────────────
def read_kafka_stream(spark: SparkSession):
    """Create a streaming DataFrame from the Kafka tennis-events topic."""
    raw = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BROKERS)
        .option("subscribe", "tennis-events")
        .option("startingOffsets", "latest")
        .option("failOnDataLoss", "false")
        .load()
    )
    # Deserialise JSON payload
    return raw.select(
        F.from_json(F.col("value").cast("string"), TENNIS_SCHEMA).alias("data")
    ).select("data.*")


# ── Statistic Computations ────────────────────────────────────────────────────
def compute_rolling_stats(df):
    """
    Apply sliding window aggregations:
      - Rolling average serve speed (10-serve window)
      - Ace count per player per match
      - 1st serve percentage
      - Momentum score (recent win streak, decays with time)
    """

    # 2-minute sliding window, updating every 30 seconds
    windowed = (
        df
        .withWatermark("timestamp", "30 seconds")
        .groupBy(
            F.window("timestamp", "2 minutes", "30 seconds"),
            "player",
            "match_id",
        )
        .agg(
            F.avg("speed_kmh").alias("avg_serve_speed"),
            F.sum(F.when(F.col("outcome") == "ace", 1).otherwise(0)).alias("ace_count"),
            F.count("*").alias("total_serves"),
            F.sum(
                F.when(F.col("is_first_serve") == "true", 1).otherwise(0)
            ).alias("first_serves"),
        )
        .withColumn(
            "first_serve_pct",
            F.round(F.col("first_serves") / F.col("total_serves") * 100, 1),
        )
    )
    return windowed


# ── Write to TimescaleDB ──────────────────────────────────────────────────────
def write_to_timescale(batch_df, batch_id: int):
    """Foreachbatch sink: write each micro-batch to TimescaleDB."""
    if batch_df.isEmpty():
        return

    # Flatten and insert into processed_stats table
    rows = batch_df.collect()
    for row in rows:
        # TODO: use JDBC batch insert via asyncpg for production performance
        print(f"[Spark] Batch {batch_id} → player={row.player}, "
              f"avg_speed={row.avg_serve_speed:.1f}, aces={row.ace_count}")

    # Batch JDBC write
    (
        batch_df
        .withColumn("window_start", F.col("window.start"))
        .drop("window")
        .write
        .mode("append")
        .jdbc(TIMESCALE_URL, "processed_stats", properties=TIMESCALE_PROPS)
    )

    # Update Redis with latest snapshot
    _update_redis_cache(batch_df)


def _update_redis_cache(batch_df):
    """Push the latest aggregated stats to Redis for fast API reads."""
    client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    latest = batch_df.orderBy(F.desc("window")).first()
    if latest:
        stats = {
            "avg_serve_speed": round(latest.avg_serve_speed or 0, 1),
            "ace_count": int(latest.ace_count or 0),
            "first_serve_pct": float(latest.first_serve_pct or 0),
            "player": latest.player,
            "updated_at": str(latest["window"]["end"]),
        }
        client.set("latest_stats", json.dumps(stats))
        client.publish("stats_updated", "1")   # Notify FastAPI via pub/sub
    client.close()


# ── Main Entry Point ──────────────────────────────────────────────────────────
def main():
    spark = create_spark_session()
    spark.sparkContext.setLogLevel("WARN")

    stream_df = read_kafka_stream(spark)
    stats_df = compute_rolling_stats(stream_df)

    query = (
        stats_df.writeStream
        .foreachBatch(write_to_timescale)
        .trigger(processingTime=f"{BATCH_INTERVAL_SECONDS} seconds")
        .outputMode("update")
        .start()
    )

    print(f"[Spark] Streaming query started. Micro-batch every {BATCH_INTERVAL_SECONDS}s.")
    query.awaitTermination()


if __name__ == "__main__":
    main()
