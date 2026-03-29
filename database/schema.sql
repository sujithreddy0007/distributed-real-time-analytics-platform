-- ═══════════════════════════════════════════════════════════════════════════
-- schema.sql — TimescaleDB Schema for Real-Time Sports Analytics Platform
-- ═══════════════════════════════════════════════════════════════════════════
-- Run against TimescaleDB (PostgreSQL + extension):
--   psql -h 192.168.1.15 -U analytics_user -d sports_analytics -f schema.sql
--
-- TimescaleDB hypertables partition data by time automatically.
-- This makes range queries like "last 60 seconds" 10-100x faster than plain PG.
-- ═══════════════════════════════════════════════════════════════════════════

-- Required extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE: tennis_events
-- Raw event log — every tennis serve/ace/fault written by Spark Streaming.
-- Permanent record of the match; used for historical analysis and replay.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tennis_events (
    time            TIMESTAMPTZ     NOT NULL,
    event_id        UUID            NOT NULL,
    match_id        TEXT            NOT NULL,
    tournament      TEXT            NOT NULL,
    player          TEXT            NOT NULL,
    opponent        TEXT            NOT NULL,
    event_type      TEXT            NOT NULL,   -- 'serve', 'point', 'game_end', 'set_end'
    outcome         TEXT,                        -- 'ace', 'fault', 'in_play', 'winner', 'error'
    is_first_serve  BOOLEAN,
    speed_kmh       DOUBLE PRECISION,
    court_position  TEXT,                        -- 'deuce', 'advantage'
    set_num         SMALLINT,
    game_num        SMALLINT,
    point_score     TEXT,                        -- e.g. '40-15'
    ace_count       INTEGER
);

-- Convert to hypertable, partitioned by 'time' with 1-day chunks
SELECT create_hypertable('tennis_events', 'time', if_not_exists => TRUE);

-- Index for player-based queries (tournament leaderboards, player comparison)
CREATE INDEX IF NOT EXISTS idx_tennis_events_player ON tennis_events (player, time DESC);
CREATE INDEX IF NOT EXISTS idx_tennis_events_match  ON tennis_events (match_id, time DESC);


-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE: processed_stats
-- Aggregated metrics written by Spark every 2 seconds.
-- Dashboard reads from here for chart history.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS processed_stats (
    window_start        TIMESTAMPTZ     NOT NULL,
    window_end          TIMESTAMPTZ     NOT NULL,
    player              TEXT            NOT NULL,
    match_id            TEXT            NOT NULL,
    avg_serve_speed     DOUBLE PRECISION,   -- km/h, rolling average
    ace_count           INTEGER,
    total_serves        INTEGER,
    first_serves        INTEGER,
    first_serve_pct     DOUBLE PRECISION,   -- percentage 0-100
    momentum_score      DOUBLE PRECISION    -- -1.0 (opponent) to +1.0 (player)
);

SELECT create_hypertable('processed_stats', 'window_start', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_processed_stats_player ON processed_stats (player, window_start DESC);


-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE: ai_commentary
-- AI-generated commentary sentences written by the AI engine.
-- FastAPI reads the 10 most recent rows for dashboard commentary feed.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_commentary (
    timestamp           TIMESTAMPTZ     NOT NULL,
    event_id            UUID            NOT NULL,
    commentary_text     TEXT            NOT NULL,
    latency_ms          INTEGER,                  -- RAG + LLM generation time
    model_name          TEXT DEFAULT 'llama3.2',
    rag_docs_used       SMALLINT DEFAULT 3        -- How many context docs were retrieved
);

SELECT create_hypertable('ai_commentary', 'timestamp', if_not_exists => TRUE);


-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE: f1_telemetry
-- Per-lap Formula E telemetry data. Same hypertable pattern.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS f1_telemetry (
    time                TIMESTAMPTZ     NOT NULL,
    event_id            UUID            NOT NULL,
    race_id             TEXT            NOT NULL,
    circuit             TEXT            NOT NULL,
    driver              TEXT            NOT NULL,
    lap                 INTEGER         NOT NULL,
    lap_time_seconds    DOUBLE PRECISION,
    speed_kmh           DOUBLE PRECISION,
    tyre_temp_celsius   DOUBLE PRECISION,
    battery_pct         DOUBLE PRECISION,
    gap_to_leader_sec   DOUBLE PRECISION,
    drs_active          BOOLEAN
);

SELECT create_hypertable('f1_telemetry', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_f1_driver ON f1_telemetry (driver, time DESC);
CREATE INDEX IF NOT EXISTS idx_f1_race   ON f1_telemetry (race_id, lap ASC);


-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE: system_health
-- Heartbeat records from each service. Dashboard health panel reads this.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_health (
    time            TIMESTAMPTZ     NOT NULL,
    component       TEXT            NOT NULL,   -- 'kafka', 'spark', 'ai_engine', 'api'
    status          TEXT            NOT NULL,   -- 'healthy', 'degraded', 'down'
    message_count   BIGINT,
    notes           TEXT
);

SELECT create_hypertable('system_health', 'time', if_not_exists => TRUE);


-- ─────────────────────────────────────────────────────────────────────────────
-- DATA RETENTION POLICIES (TimescaleDB Enterprise or Community v2.x)
-- Automatically drop data older than configured thresholds.
-- ─────────────────────────────────────────────────────────────────────────────
-- Raw events: keep 90 days
SELECT add_retention_policy('tennis_events',  INTERVAL '90 days',  if_not_exists => TRUE);
SELECT add_retention_policy('f1_telemetry',   INTERVAL '90 days',  if_not_exists => TRUE);

-- Processed stats: keep 30 days (charts don't need more)
SELECT add_retention_policy('processed_stats', INTERVAL '30 days', if_not_exists => TRUE);

-- Commentary: keep forever (special moments worth archiving)
-- No retention policy on ai_commentary

-- System health: rolling 7-day window
SELECT add_retention_policy('system_health', INTERVAL '7 days',   if_not_exists => TRUE);


-- ─────────────────────────────────────────────────────────────────────────────
-- SAMPLE DATA (for development / dashboard testing without live Kafka)
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO tennis_events (time, event_id, match_id, tournament, player, opponent,
    event_type, outcome, is_first_serve, speed_kmh, court_position, set_num, game_num, ace_count)
VALUES
    (NOW() - INTERVAL '5 minutes', gen_random_uuid(), 'AO2024-F01', 'Australian Open',
     'Roger Federer', 'Rafael Nadal', 'serve', 'ace', TRUE, 217.3, 'deuce', 3, 5, 23),
    (NOW() - INTERVAL '3 minutes', gen_random_uuid(), 'AO2024-F01', 'Australian Open',
     'Rafael Nadal', 'Roger Federer', 'serve', 'fault', TRUE, 189.1, 'advantage', 3, 6, 4),
    (NOW() - INTERVAL '1 minute',  gen_random_uuid(), 'AO2024-F01', 'Australian Open',
     'Roger Federer', 'Rafael Nadal', 'serve', 'in_play', FALSE, 152.7, 'deuce', 3, 6, 23);
