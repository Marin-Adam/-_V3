"""Milvus Embedding Job — offline vector generation for product semantic search.

V3.0: Generates BGE-M3 1024-dim embeddings for all products in the catalog.
Runs daily (offline batch, latency-insensitive).

Production flow:
  1. Read product catalog from MySQL
  2. Concatenate: title + description + features + ingredients + target_audience
  3. Generate embedding via BGE-M3 (local GPU) or API
  4. Insert into Milvus collection

Current: Simulated embeddings for demo (placeholder for BGE-M3 model).
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from loguru import logger

from app.data.store import PRODUCTS
from app.core.config import get_settings

settings = get_settings()

# ── Product text builder ──────────────────────────────────────────

def build_product_text(product: dict) -> str:
    """Build the text to embed from product fields."""
    parts = [
        product.get("name", ""),
        product.get("category", ""),
        f"价格: ¥{product.get('price', 0)}",
    ]
    if "description" in product:
        parts.append(product["description"])
    if "features" in product:
        parts.append(product["features"])
    if "target_audience" in product:
        parts.append(product["target_audience"])
    return " ".join(filter(None, parts))


# ── Embedding generator (placeholder) ─────────────────────────────

class EmbeddingGenerator:
    """Vector embedding generator.

    Placeholder: uses random vectors for demo.
    Production: uncomment to load BGE-M3 via sentence-transformers.

    pip install sentence-transformers  # for production
    """

    def __init__(self, dim: int = 1024):
        self.dim = dim
        self._model = None

        # [Production] Load model:
        # try:
        #     from sentence_transformers import SentenceTransformer
        #     self._model = SentenceTransformer("BAAI/bge-m3")
        #     logger.info(f"EmbeddingGenerator: BGE-M3 loaded ({self.dim}d)")
        # except Exception as e:
        #     logger.warning(f"EmbeddingGenerator: model unavailable ({e}), using random vectors")

    def encode(self, text: str) -> list[float]:
        """Generate embedding for a text."""
        if self._model:
            return self._model.encode(text).tolist()

        # Placeholder: deterministic-ish random based on text hash
        import hashlib
        import random
        seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        return [round(rng.uniform(-1, 1), 6) for _ in range(self.dim)]


# ── Milvus client (placeholder) ───────────────────────────────────

class MilvusClient:
    """Milvus vector database client.

    Placeholder: prints what would be inserted.
    Production: uncomment to use PyMilvus SDK.
    """

    def __init__(self):
        self._connected = False

        # [Production] Connect:
        # try:
        #     from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType
        #     connections.connect(host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)
        #     self._connected = True
        #     logger.info(f"Milvus: connected to {settings.MILVUS_HOST}:{settings.MILVUS_PORT}")
        # except Exception as e:
        #     logger.warning(f"Milvus: connection failed ({e})")

    def insert(self, collection: str, data: list[dict]):
        """Insert vectors into Milvus collection."""
        if self._connected:
            # [Production] Actual insert
            pass
        else:
            logger.info(f"Milvus [placeholder]: would insert {len(data)} vectors into '{collection}'")
            for item in data[:3]:
                logger.debug(f"  {item['product_id']}: {item['text'][:60]}... (vector[{len(item['embedding'])}])")


# ── Main job ──────────────────────────────────────────────────────

async def run_embedding_job():
    """Run one embedding generation cycle."""
    logger.info("Milvus Embedding Job: starting...")
    start = time.time()

    generator = EmbeddingGenerator(dim=1024)
    milvus = MilvusClient()

    vectors = []
    for product in PRODUCTS:
        text = build_product_text(product)
        embedding = generator.encode(text)
        vectors.append({
            "product_id": product["id"],
            "category": product["category"],
            "price": product["price"],
            "text": text,
            "embedding": embedding,
        })

    milvus.insert(collection=settings.MILVUS_COLLECTION, data=vectors)

    elapsed = time.time() - start
    logger.info(f"Milvus Embedding Job: {len(vectors)} products embedded in {elapsed:.1f}s")
    return vectors


if __name__ == "__main__":
    asyncio.run(run_embedding_job())
