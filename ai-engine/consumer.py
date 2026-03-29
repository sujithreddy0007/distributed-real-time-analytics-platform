"""
consumer.py — AI Commentary Engine
====================================
Consumes significant tennis/F1 events from Kafka, runs a RAG pipeline using
LangChain + ChromaDB + Ollama (local LLM), and writes generated commentary
sentences to TimescaleDB and pushes them to connected WebSocket clients via Redis.

Pipeline:
    Kafka (tennis-events) → Significance Filter → RAG Retrieval (ChromaDB + GPU)
        → LLM Inference (Ollama Llama3.2 7B, GPU) → TimescaleDB → Redis pub/sub

Prerequisites (on your GPU machine):
    1. Ollama running: `ollama serve` + `ollama pull llama3.2:7b`
    2. ChromaDB running: `chroma run --host localhost --port 8000`
    3. Knowledge base populated: `python seed_knowledge.py`
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import asyncpg
import redis as redis_lib
from kafka import KafkaConsumer
from kafka.errors import KafkaError
from langchain_chroma import Chroma
from langchain_community.llms import Ollama
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_huggingface import HuggingFaceEmbeddings

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [AI-Engine] %(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
KAFKA_BROKERS = ["192.168.1.12:9092", "192.168.1.13:9092", "192.168.1.14:9092"]
KAFKA_TOPIC = "tennis-events"
KAFKA_GROUP_ID = "ai-consumers"

CHROMA_HOST = "localhost"
CHROMA_PORT = 8000
COLLECTION_NAME = "sports_knowledge"

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2:7b"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

TIMESCALE_DSN = "postgresql://analytics_user:changeme@192.168.1.15:5432/sports_analytics"
REDIS_HOST = "192.168.1.14"
REDIS_PORT = 6379


# ── Significance Filter ────────────────────────────────────────────────────────
class SignificanceFilter:
    """
    Determines whether an event warrants AI commentary.
    Only significant moments generate commentary to avoid spamming the feed.
    """

    ACE_MILESTONE_MULTIPLES = {5, 10, 15, 20, 25}
    MIN_ACE_SPEED_THRESHOLD = 210  # km/h — only report very fast aces

    def is_significant(self, event: dict) -> bool:
        """Return True if the event should trigger commentary generation."""
        if event.get("outcome") == "ace":
            ace_count = event.get("ace_count", 0)
            speed = event.get("speed_kmh", 0)
            # Milestone aces OR blazing fast aces
            if ace_count in self.ACE_MILESTONE_MULTIPLES or speed >= self.MIN_ACE_SPEED_THRESHOLD:
                return True

        # TODO: add more significance rules (double faults, momentum swings, set wins)
        return False


# ── RAG Pipeline ───────────────────────────────────────────────────────────────
class RAGCommentaryEngine:
    """
    Orchestrates the full Retrieve-Augment-Generate pipeline for commentary.
    Retrieves relevant player/tournament context from ChromaDB and feeds it
    to the local LLM to generate contextual, specific commentary.
    """

    COMMENTARY_PROMPT = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a professional sports commentator known for precise, exciting, "
            "data-driven commentary. Use the provided context and event data to write "
            "one commentary sentence. Be specific — mention the exact number, speed, "
            "or record. Write in present tense. Maximum 35 words.",
        ),
        (
            "human",
            "Event data: {event_json}\n\nRelevant context:\n{context}\n\n"
            "Write one commentary sentence:",
        ),
    ])

    def __init__(self):
        logger.info("Loading embedding model on GPU...")
        self.embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cuda"},  # GPU acceleration
        )

        logger.info("Connecting to ChromaDB vector store...")
        self.vector_store = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=self.embeddings,
            host=CHROMA_HOST,
            port=CHROMA_PORT,
        )
        self.retriever = self.vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 3},  # Retrieve top-3 most relevant documents
        )

        logger.info(f"Connecting to Ollama ({OLLAMA_MODEL})...")
        self.llm = Ollama(
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_MODEL,
            temperature=0.7,
            num_predict=60,   # Max tokens — keeps output concise
        )

        self.chain = self.COMMENTARY_PROMPT | self.llm | StrOutputParser()

    def generate(self, event: dict) -> str:
        """
        Full RAG pipeline:
        1. Build retrieval query from event
        2. Fetch top-3 relevant documents from ChromaDB
        3. Assemble prompt with event + context
        4. Run LLM inference and return commentary
        """
        query = self._build_query(event)
        docs = self.retriever.invoke(query)
        context = "\n\n".join(d.page_content for d in docs)

        commentary = self.chain.invoke({
            "event_json": json.dumps(event, indent=2),
            "context": context,
        })
        return commentary.strip()

    def _build_query(self, event: dict) -> str:
        player = event.get("player", "")
        tournament = event.get("tournament", "")
        outcome = event.get("outcome", "")
        ace_count = event.get("ace_count", "")
        return f"{player} {outcome} ace {ace_count} {tournament} serve record history"


# ── Database & Redis Writers ───────────────────────────────────────────────────
async def write_commentary_to_db(pool: asyncpg.Pool, event_id: str,
                                  commentary: str, latency_ms: int):
    """Insert generated commentary into the ai_commentary TimescaleDB table."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ai_commentary (timestamp, event_id, commentary_text, latency_ms)
            VALUES ($1, $2, $3, $4)
            """,
            datetime.now(timezone.utc), event_id, commentary, latency_ms,
        )


def publish_to_redis(r: redis_lib.Redis, commentary: str, event: dict):
    """Push new commentary to Redis pub/sub so FastAPI instantly notifies WebSocket clients."""
    payload = json.dumps({
        "type": "commentary",
        "text": commentary,
        "player": event.get("player"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    r.publish("commentary_channel", payload)


# ── Main Consumer Loop ────────────────────────────────────────────────────────
async def main():
    # Initialise connections
    db_pool = await asyncpg.create_pool(TIMESCALE_DSN, min_size=2, max_size=5)
    redis_client = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    sig_filter = SignificanceFilter()
    rag_engine = RAGCommentaryEngine()

    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BROKERS,
        group_id=KAFKA_GROUP_ID,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="latest",
        enable_auto_commit=True,
    )

    logger.info(f"AI Engine listening on topic: {KAFKA_TOPIC} (group: {KAFKA_GROUP_ID})")

    try:
        for message in consumer:
            event = message.value
            if not sig_filter.is_significant(event):
                continue

            logger.info(f"Significant event detected: {event.get('outcome')} "
                        f"#{event.get('ace_count')} at {event.get('speed_kmh')} km/h")

            t_start = time.time()
            commentary = rag_engine.generate(event)
            latency_ms = int((time.time() - t_start) * 1000)

            logger.info(f"[{latency_ms}ms] Generated: {commentary}")

            # Write to DB and Redis concurrently
            await write_commentary_to_db(db_pool, event["event_id"], commentary, latency_ms)
            publish_to_redis(redis_client, commentary, event)

    except KafkaError as e:
        logger.error(f"Kafka error: {e}")
    finally:
        consumer.close()
        await db_pool.close()
        redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())
