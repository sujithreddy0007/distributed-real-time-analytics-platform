# 🎾 Real-Time Sports Analytics Platform
### with AI Commentary Generation

> **Apache Kafka · Apache Spark · Qwen2.5 14B · React · Grafana · 6-Machine Cluster**

---

<div align="center">

| 6 | 4 | 3 | 14B | < 3s | 100% |
|:---:|:---:|:---:|:---:|:---:|:---:|
| Machines | Kafka Brokers | Spark Workers | AI Parameters | End-to-End | Local AI |

**Sujith · Jaswant · Joshit · March 2026**

</div>

---

## 📌 What Is This Project?

This is a distributed real-time sports analytics system built across **six physical machines on a private network**. It takes live sports data — tennis points, serve speeds, match events — processes everything instantly as it happens, runs an AI model to generate commentary sentences, and displays it all on a live web dashboard that updates every second.

The system mirrors what **Infosys actually builds and operates** for global sports events including the Australian Open, Roland Garros, ATP Tour, and Formula E. Every component was built from scratch, every machine configured manually, every failure debugged on real hardware.

---

## 🎯 The Problem We Were Solving

Traditional systems cannot handle real-time sports data well. A tennis match generates a point every 30 seconds. Formula E generates telemetry every 100 milliseconds. A simple script or regular database falls behind almost immediately — data is lost when servers crash, and you cannot generate intelligent commentary in real time.

We needed a system that:

- ✅ Never loses a single data event, even if one server crashes mid-match
- ✅ Processes data fast enough to keep up with live events
- ✅ Generates AI commentary that sounds like a real broadcast commentator
- ✅ Shows everything live in a browser, updating without any page refresh
- ✅ Can be monitored so we know exactly what every machine is doing at any moment

> **Most people build projects on one laptop.** We built this across six real machines on a real private network. Every connection, every config file, every port — all manually set up and debugged. When something broke (and a lot of things broke), we had to figure out why a machine across the room was refusing connections, why ZooKeeper was rejecting a broker registration, why Spark could not find Java. That process taught us more than any tutorial ever could.

---

## 🏗️ Architecture — Five Layers

The system has five layers. Each layer does exactly one thing. A failure in one does not stop the others.

| Layer | What It Does | Technology |
|-------|-------------|------------|
| **1 — Data Generation** | Creates tennis and F1 events every 2 seconds, sends to Kafka | Python script on GPU machine |
| **2 — Transport** | Carries events from producer to multiple consumers, stores everything durably | Apache Kafka — 4 brokers, 3 replicas |
| **3 — Processing** | Reads from Kafka every 5 seconds, computes statistics, writes results | Apache Spark — 3 workers |
| **4 — AI Commentary** | Detects significant events (aces, faults), generates commentary sentences | Qwen2.5 14B via Ollama on NVIDIA GPU |
| **5 — Display** | Serves live data to browser dashboard every second via WebSocket | FastAPI + React |

---

## 🖥️ The 6-Machine Cluster

| Machine | IP Address | What Runs On It |
|---------|-----------|-----------------|
| **GPU Machine (main)** | `172.21.30.15` | Data producer, AI engine, Qwen2.5 14B, React dashboard |
| **k1 — Kali Linux** | `172.21.30.89` | Kafka Broker 1, Spark Master + Worker, FastAPI server |
| **w1 — Windows + WSL2** | `172.21.30.28` | Kafka Broker 2, Spark Worker |
| **w2 — Windows + WSL2** | `172.21.30.20` | Kafka Broker 3, Spark Worker, Redis cache |
| **w3 — Windows + WSL2** | `172.21.30.22` | Prometheus, Grafana monitoring |
| **w4 — Windows + WSL2** | `172.21.30.13` | ZooKeeper, Kafka Broker 4, TimescaleDB |

All machines are on a private `172.21.30.x` network. Windows machines use **WSL2 with mirrored networking** — solving the typical WSL2 IP routing problems.

---

## 🔁 Data Flow — Following One Event

Here is exactly what happens when Federer hits an ace:

```
① Python producer → JSON event (player, speed, outcome, timestamp)
② → Kafka (3 brokers store it simultaneously, 1 copy on each)
③ → Spark reads 5-second batch → computes stats → Redis + TimescaleDB
④ → AI Engine detects "ace" → Qwen2.5 14B generates commentary (2-3s)
⑤ → FastAPI reads Redis every 1s → WebSocket push → React dashboard
```

> *Total time from event to visible update: approximately 3–5 seconds.*

---

## 🤖 AI Commentary — Qwen2.5 14B

The AI commentary engine is the most technically interesting component. A **14-billion parameter language model** runs entirely on our NVIDIA GPU — no external API, no internet required, no cost per request.

### Why 14B?

| Model | Size | Commentary Quality | Response Time |
|-------|------|--------------------|---------------|
| llama3.2:3b | 3B | Generic, repetitive — "Good serve!" | < 1 second |
| qwen2.5:7b | 7B | Better but still formulaic | 1–2 seconds |
| **Qwen2.5:14b ✓ CHOSEN** | **14B** | **Broadcast quality — specific stats, context, flow** | **2–3 seconds** |
| qwen2.5:32b | 32B | Outstanding quality | 4–6 seconds |

### Sample Output

> *"Roger Federer serves up an absolute thunderbolt, nailing his fifteenth ace of the match at an astounding 221.0 km/h, unerring down the T!"*

> *"Roger Federer fires down his fourteenth ace of the match, serving at an astonishing 221.8 kilometers per hour right down the T!"*

> *"Federer, known for his precision and power, serves up a surprising double fault at 167.1 km/h, his first in this match as he had already recorded thirteen aces."*

These appear on the dashboard within **3 seconds** of the actual event. The model knows the ace count, the speed, and the player's background — because we build context into the prompt before sending to the model. Zero API cost. Zero data leaving the lab.

---

## 📸 Screenshots

### Live Dashboard

![Dashboard with AI Commentary](screenshots/dashboard_ai_commentary.png)
*Live dashboard showing Federer (15 aces, 496 points) vs Nadal (5 aces, 509 points) with AI commentary feed active.*

![First Dashboard Run](screenshots/dashboard_first_run.png)
*First run — stats updating live, speed chart building in real time.*

### Grafana Monitoring

![Grafana Node Exporter](screenshots/grafana_node_exporter.png)
*Grafana Node Exporter Full dashboard showing k1 (Kali machine). CPU 52.6% — running Kafka, Spark, and FastAPI simultaneously. RAM 25.3% of 16GB used.*

---

## 🔧 Why Each Technology?

### Apache Kafka — Why Not Just Use a Database?
If the database is slow or down, the producer has nowhere to send data. If two consumers want the same data, you have to duplicate writes. Kafka solves all of this. Producer sends, job done. Multiple consumers read independently. If a consumer crashes, it picks up exactly where it left off.

We ran 4 brokers with **replication factor 3** — every message exists on 3 machines. We shut down one broker mid-stream during testing. Kafka elected a new partition leader in under 10 seconds. **Zero messages lost.**

### Apache Spark — Why Not Just Use Python?
Python processes events one at a time. At real scale, a Python script falls behind and never catches up. Spark processes a batch of all events from the last 5 seconds **simultaneously across 3 machines**. What Python does in 30 seconds, Spark does in 2.

### TimescaleDB — Why Not Plain PostgreSQL?
TimescaleDB automatically partitions data by time. A query for "last 30 seconds" only scans the current time partition — **10–100x faster** than plain PostgreSQL at scale. And it is 100% PostgreSQL-compatible.

### Redis — Why Not Just Query the Database?
The FastAPI backend pushes data to 100 dashboard viewers every second — that is 100 DB queries per second just for the latest ace count. Redis answers in **0.1 milliseconds from RAM**. TimescaleDB handles historical queries only.

---

## ⚡ Tech Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Message Broker | Apache Kafka | 3.7.0 | Event streaming across 4 brokers |
| Cluster Coordinator | Apache ZooKeeper | bundled | Kafka broker coordination |
| Stream Processor | Apache Spark | 3.5.1 | Distributed real-time computation |
| Time-Series DB | TimescaleDB | 2.x (PG16) | Historical event storage |
| Cache | Redis | 7.x | Sub-millisecond live stats |
| AI Model | Qwen2.5 14B | Q4_K_M | Sports commentary generation |
| LLM Runtime | Ollama | Latest | Local GPU model serving |
| Backend API | FastAPI | 0.115 | REST + WebSocket server |
| Frontend | React + Recharts | 18.x | Live dashboard |
| Monitoring | Prometheus + Grafana | 2.51 / 10.x | System metrics |
| System Metrics | Node Exporter | 1.7.0 | CPU/RAM/network per machine |
| Language | Python | 3.12 | All backend scripts |

---

## 🗄️ Database Schema

| Table | Type | Key Columns | Notes |
|-------|------|-------------|-------|
| `tennis_events` | TimescaleDB hypertable | time, player, speed_kmh, outcome | 185+ rows per player per session |
| `processed_stats` | TimescaleDB hypertable | time, player, metric_name, value | Every Spark batch |
| `ai_commentary` | TimescaleDB hypertable | time, player, commentary_text | 1 per ace or double fault |
| `f1_telemetry` | TimescaleDB hypertable | time, driver, lap_num, speed_kmh | Continuous F1 events |

---

## 📊 Performance Numbers

| Metric | Measured Value |
|--------|---------------|
| Kafka message delivery latency | ~50ms from `producer.send()` to consumer receive |
| Spark batch processing time | < 2 seconds per 5-second batch |
| AI commentary generation | 2–3 seconds (Qwen2.5 14B on GPU) |
| Redis read latency | < 0.1ms |
| Dashboard WebSocket push interval | 1 second |
| End-to-end event to dashboard | 3–5 seconds |
| Kafka consumer lag | < 10 messages |
| k1 CPU during full operation | ~52% — Kafka + Spark + FastAPI concurrently |

---

## 🔍 Verification

### Kafka Cluster — All 4 Brokers

```bash
bin/kafka-broker-api-versions.sh --bootstrap-server 172.21.30.89:9092 2>/dev/null | grep "id:"

# Output:
# 172.21.30.13:9092 (id: 4 rack: null)
# 172.21.30.89:9092 (id: 1 rack: null)
# 172.21.30.20:9092 (id: 3 rack: null)
# 172.21.30.28:9092 (id: 2 rack: null)
```

### Data in TimescaleDB

```sql
SELECT player, COUNT(*) as events, MAX(speed_kmh) as top_speed
FROM tennis_events GROUP BY player;

--  player  | events | top_speed
-- ---------+--------+-----------
--  Federer |    185 |     229.7
--  Nadal   |    208 |     230.0
```

### Fault Tolerance Test

1. Shut down Kafka Broker 2 (w1) while producer was sending
2. ZooKeeper detected failure within **10 seconds**
3. Automatically elected Broker 3 as new leader for partition 1
4. Producer reconnected automatically — no code change needed
5. Dashboard continued updating. Ace count kept incrementing. **Zero data loss**
6. Restarted Broker 2 — it rejoined and caught up on missed replication

---

## 🐛 Real Challenges We Solved

### WSL2 Network Problem
WSL2 creates its own virtual network with different IPs. Kafka brokers were advertising wrong addresses. **Fix:** WSL2 mirrored networking mode — add `networkingMode=mirrored` to `.wslconfig`.

### Duplicate Broker ID
w4 accidentally had `broker.id=1` — same as k1. ZooKeeper got confused, messages stopped flowing. **Fix:** Assigned `broker.id=4` to w4, cleared ZooKeeper data to remove stale registrations.

### Java Path on Kali Linux
Kali uses `zsh`, not `bash`. Variables added to `.bashrc` were ignored. `spark-submit` failed with "No such file or directory". **Fix:** Added path to `.zshrc` AND wrote `JAVA_HOME` directly into `spark/conf/spark-env.sh`.

### IP Addresses Changed After 5 Days
Router reassigned DHCP addresses. Every Kafka config had stale IPs. **Fix:** Updated `server.properties` on all machines, cleared old `kafka-logs` directories, restarted in correct dependency order. Lesson: always use DNS names, not hardcoded IPs.

### TimescaleDB Preload Error
`CREATE EXTENSION timescaledb` failed with FATAL error — PostgreSQL crashed. **Fix:** Added `shared_preload_libraries = 'timescaledb'` to `postgresql.conf` before starting PostgreSQL.

---

## 🚀 How to Run

> **Startup order is critical.** ZooKeeper → PostgreSQL → Redis → Kafka → Spark → Monitoring → FastAPI → Spark Processor → Ollama → AI Engine → Producer → Dashboard

| Step | Machine | Command | Verify |
|------|---------|---------|--------|
| 1 | w4 | Start ZooKeeper | `echo 'ruok' \| nc localhost 2181` → `imok` |
| 2 | w4 | `sudo service postgresql start` | `service postgresql status` → active |
| 3 | w2 | `sudo service redis-server start` | `redis-cli -a Redis@2024 ping` → PONG |
| 4 | k1 | Start Kafka Broker 1 | `grep 'started' ~/kafka-broker1.log` |
| 5 | w1 | Start Kafka Broker 2 | `grep 'started' ~/kafka-broker2.log` |
| 6 | w2 | Start Kafka Broker 3 | `grep 'started' ~/kafka-broker3.log` |
| 7 | w4 | Start Kafka Broker 4 | `grep 'started' ~/kafka-broker4.log` |
| 8 | k1 | `sbin/start-master.sh` | `http://172.21.30.89:8080` → ALIVE |
| 9 | w1 | `sbin/start-worker.sh spark://172.21.30.89:7077` | Spark UI shows 2 workers |
| 10 | w2 | `sbin/start-worker.sh spark://172.21.30.89:7077` | Spark UI shows 3 workers |
| 11 | w3 | Start Prometheus + Grafana | `http://172.21.30.22:3000` |
| 12 | k1 | `python3 api.py` | `http://172.21.30.89:8000/health` → ok |
| 13 | k1 | `spark-submit spark_processor.py` | Batch output in terminal |
| 14 | GPU | Ollama in Windows tray | `localhost:11434/api/tags` → model listed |
| 15 | GPU | `python3 ai_engine.py` | Ollama OK in terminal |
| 16 | GPU | `python3 producer.py` | TENNIS/F1 lines appear |
| 17 | GPU | `npm start` | `http://172.21.30.15:3000` → live dashboard |

---

## 🗺️ System at a Glance — All 19 Services

| Component | Status | Location | Notes |
|-----------|--------|----------|-------|
| ZooKeeper | ✅ Running | w4 — `172.21.30.13:2181` | Kafka cluster coordinator |
| Kafka Broker 1 | ✅ Running | k1 — `172.21.30.89:9092` | Partition 0 leader |
| Kafka Broker 2 | ✅ Running | w1 — `172.21.30.28:9092` | Partition 1 leader |
| Kafka Broker 3 | ✅ Running | w2 — `172.21.30.20:9092` | Partition 2 leader |
| Kafka Broker 4 | ✅ Running | w4 — `172.21.30.13:9092` | All-partition replica |
| Spark Master | ✅ Running | k1 — `172.21.30.89:7077` | Coordinates workers |
| Spark Worker 1 | ✅ Running | k1 — `172.21.30.89` | 2 cores, 4GB RAM |
| Spark Worker 2 | ✅ Running | w1 — `172.21.30.28` | 2 cores, 4GB RAM |
| Spark Worker 3 | ✅ Running | w2 — `172.21.30.20` | 2 cores, 4GB RAM |
| TimescaleDB | ✅ Running | w4 — `172.21.30.13:5432` | 4 hypertables created |
| Redis | ✅ Running | w2 — `172.21.30.20:6379` | 6 live keys per player |
| FastAPI | ✅ Running | k1 — `172.21.30.89:8000` | 5 endpoints + WebSocket |
| Spark Processor | ✅ Running | k1 | Processing every 5 seconds |
| Ollama (Qwen2.5) | ✅ Running | GPU — `172.21.30.15:11434` | 14B params on NVIDIA GPU |
| AI Engine | ✅ Running | GPU — `172.21.30.15` | Generating commentary |
| Data Producer | ✅ Running | GPU — `172.21.30.15` | 1 event every 2 seconds |
| React Dashboard | ✅ Running | GPU — `172.21.30.15:3000` | 1-second update via WebSocket |
| Prometheus | ✅ Running | w3 — `172.21.30.22:9090` | Scraping all 6 machines |
| Grafana | ✅ Running | w3 — `172.21.30.22:3000` | Node Exporter Full dashboard |

---

## 🔮 What We Plan to Add Next

- **RAG (Retrieval-Augmented Generation)** — ChromaDB vector database with player history, tournament records, head-to-head stats. Commentary becomes significantly more specific and contextual.
- **SLM Fine-Tuning** — Fine-tune Phi-3 Mini on sports commentary using QLoRA on our GPU. Custom model, faster inference, no generic outputs.
- **Kubernetes Deployment** — Replace manual `nohup` startup with K8s manifests. Rolling updates, zero downtime, automatic restarts.
- **Graph Database** — Neo4j for player matchup history, surface preferences, performance trends. Natural graph traversal queries.

---

## 💡 What We Learned

**Distributed systems are not complicated — they are precise.** One wrong IP in one config file breaks an entire cluster. One missing environment variable crashes a service.

**Read the error message carefully.** `ZooKeeperClientTimeoutException` tells you exactly what is wrong. `NoBrokersAvailable` means wrong bootstrap addresses. Every problem we hit was explained in the logs.

**Configuration is a first-class concern.** In tutorials you always see `localhost:9092`. In a real multi-machine setup, `advertised.listeners` in Kafka is critical — it is what the broker tells clients to connect to.

**Local AI is more powerful than expected.** Qwen2.5 14B produces broadcast-quality commentary because of prompt engineering — giving the model clear instructions, exact facts, and a persona. Running locally means unlimited inference, zero cost, zero latency from external APIs.

> *This took weeks of work. The network issues took an afternoon. The duplicate broker ID took a full debugging session. The Java path on Kali took longer than it should have. None of this was smooth or easy. But that is the point. Real distributed systems engineering is precise, methodical debugging across multiple moving parts. Every problem we hit and solved is knowledge we now own permanently.*

---

## 🤝 Team

**Sujith** · **Jaswant** · **Joshit**

Built from scratch. Debugged on real hardware. Running in production.

---

## 📄 License

MIT License — feel free to use, modify, and build on this.

---

<div align="center">

**19 services · 6 machines · 1 private network**

</div>
