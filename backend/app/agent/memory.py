"""Long-term memory for the Agent — stores analysis history and user preferences.

Uses PostgreSQL full-text search (pgvector tsvector) for recalling past analyses.
When an embedding service becomes available, swap _search_fts → _search_vector
to upgrade from keyword search to semantic search.

Storage table (created by init_db / SQLAlchemy):
  agent_memories(id TEXT PK, content TEXT, search_vector tsvector, metadata JSONB,
                 embedding vector(384), created_at TIMESTAMPTZ)

==============================================================================
Embedding 升级路径 (Upgrade Path)
==============================================================================

当前: PostgreSQL 全文检索 (tsvector + ts_rank)
  - 优点: 零额外依赖，中文分词可用 jieba 或 simple 配置
  - 缺点: 只能关键词匹配，"销售额暴跌" 搜不到 "GMV 下降"

升级到向量检索只需三步:
  1. 取消 _embed() 方法中的注释，加载 sentence-transformers 模型
  2. 将 search() 中的 _search_fts 改为 _search_vector
  3. 在 store() 中取消 embedding 生成代码的注释

模型推荐: BAAI/bge-small-zh-v1.5 (384维, ~100MB, 中文语义检索 SOTA)
  pip install sentence-transformers
  model = SentenceTransformer('BAAI/bge-small-zh-v1.5')

==============================================================================
"""

import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger
from sqlalchemy import text

from app.core.config import get_settings

settings = get_settings()


@dataclass
class MemoryItem:
    id: str
    content: str
    metadata: dict = field(default_factory=dict)
    embedding: Optional[list[float]] = None
    timestamp: float = field(default_factory=time.time)


class AgentMemory:
    """Stores and retrieves past analysis results using PostgreSQL full-text search.

    Upgrade-ready: swap _search_fts → _search_vector when embedding is available.
    """

    def __init__(self):
        self._max_items = 100
        self._table_ready = False

        # [预留] Embedding 模型 — 取消注释以启用向量检索
        # self._embed_model = None
        # try:
        #     from sentence_transformers import SentenceTransformer
        #     self._embed_model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
        #     logger.info("Agent memory: embedding model loaded (bge-small-zh)")
        # except Exception as e:
        #     logger.warning(f"Agent memory: embedding model unavailable ({e}), using FTS")

    # ── Public API ──────────────────────────────────────────────────────

    async def store(self, content: str, metadata: dict = None):
        """Store an analysis result in PostgreSQL with full-text indexing."""
        item = MemoryItem(
            id=f"mem-{int(time.time()*1000)}",
            content=content,
            metadata=metadata or {},
        )

        # [预留] 生成 embedding — 取消注释以启用向量检索
        # if self._embed_model:
        #     item.embedding = self._embed_model.encode(content).tolist()

        await self._store_pg(item)

    async def search(self, query: str, top_k: int = 5) -> list[MemoryItem]:
        """Search for similar past analyses.

        Current: PostgreSQL full-text search (keywords).
        Future:  Uncomment _search_vector to use semantic vector search.
        """
        return await self._search_fts(query, top_k)
        # [预留] 向量检索 — 取消下行注释，注释上行以切换
        # return await self._search_vector(query, top_k)

    # ── PostgreSQL Full-Text Search ─────────────────────────────────────

    async def _store_pg(self, item: MemoryItem):
        """Insert into agent_memories with tsvector update."""
        try:
            from app.core.database import async_session_factory
            async with async_session_factory() as session:
                import json as _json
                stmt = text("""
                    INSERT INTO agent_memories (id, content, search_vector, metadata, created_at)
                    VALUES (:id, :content, to_tsvector('simple', :content), :metadata, now())
                    ON CONFLICT (id) DO UPDATE
                    SET content = EXCLUDED.content,
                        search_vector = EXCLUDED.search_vector,
                        metadata = EXCLUDED.metadata
                """)
                await session.execute(stmt, {
                    "id": item.id,
                    "content": item.content,
                    "metadata": _json.dumps(item.metadata, ensure_ascii=False),
                })
                await session.commit()

                # Prune old entries
                count_result = await session.execute(text("SELECT count(*) FROM agent_memories"))
                total = count_result.scalar()
                if total and total > self._max_items:
                    await session.execute(
                        text("DELETE FROM agent_memories WHERE id IN ("
                             "SELECT id FROM agent_memories ORDER BY created_at ASC "
                             "LIMIT :excess)"),
                        {"excess": total - self._max_items},
                    )
                    await session.commit()

        except Exception as e:
            logger.warning(f"Agent memory store failed: {e}")

    async def _search_fts(self, query: str, top_k: int = 5) -> list[MemoryItem]:
        """Keyword search using PostgreSQL full-text search (tsquery)."""
        try:
            from app.core.database import async_session_factory
            async with async_session_factory() as session:
                # Convert user query to tsquery.  simple config = no language-specific
                # stemming, which works well for mixed Chinese/English content.
                result = await session.execute(
                    text("""
                        SELECT id, content, metadata, created_at,
                               ts_rank(search_vector, plainto_tsquery('simple', :query)) AS rank
                        FROM agent_memories
                        WHERE search_vector @@ plainto_tsquery('simple', :query)
                        ORDER BY rank DESC
                        LIMIT :limit
                    """),
                    {"query": query, "limit": top_k},
                )
                rows = result.fetchall()
                return [
                    MemoryItem(
                        id=r.id, content=r.content,
                        metadata=r.metadata or {},
                        timestamp=r.created_at.timestamp() if r.created_at else time.time(),
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.warning(f"Agent memory search failed: {e}")
            return []

    # ── [预留] Vector Search ────────────────────────────────────────────
    #
    # async def _search_vector(self, query: str, top_k: int = 5) -> list[MemoryItem]:
    #     """Semantic search using pgvector cosine distance.
    #
    #     Prerequisite: embedding model loaded in __init__.
    #     """
    #     if not self._embed_model:
    #         return await self._search_fts(query, top_k)
    #
    #     query_embedding = self._embed_model.encode(query).tolist()
    #     try:
    #         async with async_session_factory() as session:
    #             result = await session.execute(
    #                 text("""
    #                     SELECT id, content, metadata, created_at,
    #                            1 - (embedding <=> :query_vec::vector) AS similarity
    #                     FROM agent_memories
    #                     WHERE embedding IS NOT NULL
    #                     ORDER BY embedding <=> :query_vec::vector
    #                     LIMIT :limit
    #                 """),
    #                 {"query_vec": str(query_embedding), "limit": top_k},
    #             )
    #             rows = result.fetchall()
    #             return [
    #                 MemoryItem(
    #                     id=r.id, content=r.content,
    #                     metadata=r.metadata or {},
    #                     timestamp=r.created_at.timestamp() if r.created_at else time.time(),
    #                 )
    #                 for r in rows
    #             ]
    #     except Exception as e:
    #         logger.warning(f"Vector search failed, fallback to FTS: {e}")
    #         return await self._search_fts(query, top_k)
    #
    # async def _embed(self, text: str) -> list[float]:
    #     """Generate embedding vector for a text.
    #
    #     Alternatives:
    #       - 本地模型: SentenceTransformer('BAAI/bge-small-zh-v1.5')
    #       - 公司 API: httpx.post('http://embedding-service/v1/embeddings', json={...})
    #     """
    #     if self._embed_model:
    #         return self._embed_model.encode(text).tolist()
    #     return []
