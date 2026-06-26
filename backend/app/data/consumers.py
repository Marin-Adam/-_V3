"""Kafka consumers for e-commerce data streams with dedup and field normalization.

Architecture:
  KafkaConsumerManager  ← 主入口，管理所有消费者生命周期
  ├── KafkaOrderConsumer       ← ecom.orders topic
  ├── KafkaTrafficConsumer     ← ecom.traffic topic
  ├── KafkaInventoryConsumer   ← ecom.inventory topic
  └── KafkaCompetitorConsumer  ← ecom.competitor topic

降级策略 (via config.DATA_SOURCE):
  "kafka"    → Kafka consumer group
  "polling"  → [预留] 从 PostgreSQL/MySQL 定时轮询
  "generator" → DataGenerator 随机生成（演示/降级）
  "auto"     → 自动检测 Kafka 可达性，不可达则降级

去重策略:
  - Redis SET NX (key=processed:order:{order_id}, TTL=24h)
  - 订单流: 严格去重（Exactly-once 语义）
  - 流量/库存/竞品流: 允许 at-least-once（后续数据覆盖前面）
  - Redis 不可用时自动跳过去重，降级为 at-least-once

==============================================================================
公司接入指南 (Integration Guide)
==============================================================================

将公司 Kafka 消息字段映射到看板统一 schema，只需修改 _normalize_*() 方法中的字段映射表。

示例 — 公司订单消息格式:
  {
    "orderId": "PO-20260618-001",
    "skuCode": "SKU001",
    "skuName": "无线蓝牙耳机 Pro",
    "cat": "数码电子",
    "qty": 2,
    "unitPrice": 299.00,
    "totalPrice": 598.00,
    "salesChannel": "TMALL",       // TMALL/JD/PDD/DOUYIN/MINI_PROGRAM
    "buyerRegion": "EAST",
    "createdAt": "2026-06-18T14:35:00+08:00",
    "userId": "U123456"
  }

只需在 _normalize_order() 中修改映射:
  FIELD_MAP = {
    "order_id": "orderId",        # 左边是看板字段，右边是公司 Kafka 字段
    "product_id": "skuCode",
    "product_name": "skuName",
    ...
  }

==============================================================================
"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from typing import Optional

from loguru import logger

from app.core.config import get_settings

settings = get_settings()

# ============================================================================
# Kafka 连通性检测
# ============================================================================


def _kafka_reachable() -> bool:
    """Quick probe: try a TCP connection to the Kafka bootstrap server."""
    import socket

    host, _, port = settings.KAFKA_BOOTSTRAP_SERVERS.partition(",")
    host = host.strip()
    port = int(port.strip()) if port.strip() else 9092
    try:
        sock = socket.create_connection((host, port), timeout=3)
        sock.close()
        return True
    except Exception:
        return False


# ============================================================================
# Redis 去重辅助
# ============================================================================


class DedupStore:
    """Redis-backed deduplication. Falls back to no-op when Redis is unavailable."""

    def __init__(self):
        self._redis = None
        self._available = False
        self._init_redis()

    def _init_redis(self):
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.Redis(
                host="localhost", port=6379, db=1,
                socket_connect_timeout=2, decode_responses=True,
            )
            self._available = True
            logger.info("Dedup: Redis connected (db=1)")
        except Exception as e:
            logger.warning(f"Dedup: Redis unavailable, skip dedup ({e})")

    async def is_duplicate(self, entity_type: str, entity_id: str) -> bool:
        """Check if this entity has been processed. True = duplicate, skip it."""
        if not self._available or self._redis is None:
            return False
        try:
            key = f"processed:{entity_type}:{entity_id}"
            # SET NX returns True if key was set (first time), False if already exists
            was_set = await self._redis.set(key, "1", nx=True, ex=86400)
            return not was_set
        except Exception:
            return False  # Redis error → don't block the pipeline


# ============================================================================
# Base Kafka Consumer
# ============================================================================


class BaseKafkaConsumer(ABC):
    """Abstract base for Kafka topic consumers with dedup and field normalization."""

    def __init__(self, stream_manager, dedup: DedupStore, store=None):
        self.stream = stream_manager
        self.dedup = dedup
        self.store = store  # EcomDataStore — shared with MCP tools
        self._running = False

    async def start(self):
        """Consume messages in a loop with manual offset commit."""
        self._running = True
        try:
            from aiokafka import AIOKafkaConsumer
        except ImportError:
            logger.error("aiokafka not installed. Run: pip install aiokafka")
            return

        consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=settings.KAFKA_CONSUMER_GROUP,
            enable_auto_commit=False,
            auto_offset_reset="latest",
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            max_poll_records=100,
        )
        await consumer.start()
        logger.info(f"Kafka consumer started: {self.topic}")

        try:
            async for msg in consumer:
                if not self._running:
                    break
                try:
                    await self._process_one(msg)
                    await consumer.commit()
                except Exception:
                    logger.exception(f"Failed to process message offset={msg.offset}, will retry")
                    # Don't commit — Kafka will re-deliver on restart
        finally:
            await consumer.stop()

    async def stop(self):
        self._running = False

    @property
    @abstractmethod
    def topic(self) -> str:
        ...

    @abstractmethod
    async def _process_one(self, msg) -> None:
        ...

    # ------------------------------------------------------------------
    # 字段映射工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _map_fields(raw: dict, field_map: dict[str, str]) -> dict:
        """Map raw Kafka fields to our schema using a field map dict.

        field_map: {our_field: their_field}
        例: {"order_id": "orderId", "product_id": "skuCode"}
        """
        return {our: raw.get(their) for our, their in field_map.items()}


# ============================================================================
# Order Consumer
# ============================================================================


class KafkaOrderConsumer(BaseKafkaConsumer):
    """Consumes ecom.orders topic. Applies strict dedup via Redis SET NX."""

    # ── 公司接入点：修改此映射表以匹配公司的 Kafka 消息字段 ──
    # 左边 = 看板统一字段, 右边 = 公司 Kafka 消息中的字段名
    FIELD_MAP = {
        "order_id": "order_id",       # ← 改成公司的订单ID字段名
        "product_id": "product_id",   # ← 改成公司的 SKU 编码字段名
        "product_name": "product_name",
        "category": "category",
        "quantity": "quantity",
        "unit_price": "unit_price",
        "total_amount": "total_amount",
        "channel": "channel",         # ← 改成公司的销售渠道字段名
        "region": "region",           # ← 改成公司的地区字段名
        "user_id": "user_id",         # ← 改成公司的用户ID字段名
        "timestamp": "timestamp",     # ← 改成公司的订单时间字段名
    }

    # ── 公司接入点：渠道值映射（可选） ──
    # 如果公司的渠道字段使用英文编码，在这里做翻译
    CHANNEL_MAP = {
        # "TMALL": "淘宝",
        # "JD": "京东",
        # "PDD": "拼多多",
        # "DOUYIN": "抖音",
        # "MINI_PROGRAM": "小程序",
    }

    @property
    def topic(self) -> str:
        return settings.KAFKA_TOPIC_ORDERS

    async def _process_one(self, msg) -> None:
        raw = msg.value
        order_id = raw.get("order_id") or raw.get("orderId") or str(msg.offset)

        # Dedup check
        if await self.dedup.is_duplicate("order", order_id):
            return

        order = self._normalize(raw, order_id)

        # Write to shared store (so MCP tools can query it)
        if self.store:
            self.store.add_order(order)

        await self.stream.publish("orders", json.dumps(order, ensure_ascii=False))

    def _normalize(self, raw: dict, order_id: str) -> dict:
        # 用字段映射表转换
        mapped = self._map_fields(raw, self.FIELD_MAP)

        # 渠道值翻译
        raw_channel = mapped.get("channel", "")
        channel = self.CHANNEL_MAP.get(raw_channel, raw_channel or "未知渠道")

        return {
            "order_id": mapped.get("order_id") or order_id,
            "product_id": mapped.get("product_id", "UNKNOWN"),
            "product_name": mapped.get("product_name", "未知商品"),
            "category": mapped.get("category", "未知品类"),
            "quantity": int(mapped.get("quantity", 1)),
            "unit_price": float(mapped.get("unit_price", 0)),
            "total_amount": float(mapped.get("total_amount", 0)),
            "channel": channel,
            "region": mapped.get("region", "未知"),
            "user_id": mapped.get("user_id", ""),
            "timestamp": mapped.get("timestamp") or self._now_iso(),
        }

    @staticmethod
    def _now_iso() -> str:
        from app.core.constants import now_cst
        return now_cst().isoformat()


# ============================================================================
# Traffic Consumer
# ============================================================================


class KafkaTrafficConsumer(BaseKafkaConsumer):
    """Consumes ecom.traffic topic. At-least-once (data is cumulative, self-correcting)."""

    FIELD_MAP = {
        "product_id": "product_id",
        "product_name": "product_name",
        "uv": "uv",
        "pv": "pv",
        "add_cart": "add_cart",
        "timestamp": "timestamp",
    }

    @property
    def topic(self) -> str:
        return settings.KAFKA_TOPIC_TRAFFIC

    async def _process_one(self, msg) -> None:
        raw = msg.value
        mapped = self._map_fields(raw, self.FIELD_MAP)

        pid = mapped.get("product_id", "")
        uv = int(mapped.get("uv", 0))
        pv = int(mapped.get("pv", 0))
        cart = int(mapped.get("add_cart", 0))

        # Write to shared store
        if self.store:
            self.store.update_traffic(pid, uv, pv, cart)

        traffic = {
            "product_id": pid,
            "product_name": mapped.get("product_name", ""),
            "uv": uv, "pv": pv, "add_cart": cart,
            "timestamp": mapped.get("timestamp") or self._now_iso(),
        }
        await self.stream.publish("traffic", json.dumps(traffic, ensure_ascii=False))

    @staticmethod
    def _now_iso() -> str:
        from app.core.constants import now_cst
        return now_cst().isoformat()


# ============================================================================
# Inventory Consumer
# ============================================================================


class KafkaInventoryConsumer(BaseKafkaConsumer):
    """Consumes ecom.inventory topic. Snapshot data, at-least-once is fine."""

    FIELD_MAP = {
        "product_id": "product_id",
        "product_name": "product_name",
        "quantity": "quantity",
        "alert": "alert",
        "timestamp": "timestamp",
    }

    @property
    def topic(self) -> str:
        return settings.KAFKA_TOPIC_INVENTORY

    async def _process_one(self, msg) -> None:
        raw = msg.value
        mapped = self._map_fields(raw, self.FIELD_MAP)
        pid = mapped.get("product_id", "")
        qty = int(mapped.get("quantity", 0))

        # Write to shared store
        if self.store:
            self.store.set_inventory(pid, qty)

        inventory = {
            "product_id": pid,
            "product_name": mapped.get("product_name", ""),
            "quantity": qty,
            "alert": "low_stock" if qty < 20 else ("warning" if qty < 50 else None),
            "timestamp": mapped.get("timestamp") or self._now_iso(),
        }
        await self.stream.publish("inventory", json.dumps(inventory, ensure_ascii=False))

    @staticmethod
    def _now_iso() -> str:
        from app.core.constants import now_cst
        return now_cst().isoformat()


# ============================================================================
# Competitor Consumer
# ============================================================================


class KafkaCompetitorConsumer(BaseKafkaConsumer):
    """Consumes ecom.competitor topic. Low frequency, at-least-once."""

    FIELD_MAP = {
        "product_id": "product_id",
        "product_name": "product_name",
        "our_price": "our_price",
        "competitor_prices": "competitor_prices",
        "timestamp": "timestamp",
    }

    @property
    def topic(self) -> str:
        return settings.KAFKA_TOPIC_COMPETITOR

    async def _process_one(self, msg) -> None:
        raw = msg.value
        mapped = self._map_fields(raw, self.FIELD_MAP)

        snapshot = {
            "product_id": mapped.get("product_id", ""),
            "product_name": mapped.get("product_name", ""),
            "our_price": float(mapped.get("our_price", 0)),
            "competitor_prices": mapped.get("competitor_prices", []),
            "timestamp": mapped.get("timestamp") or self._now_iso(),
        }

        # Write to shared store
        if self.store:
            self.store.add_competitor_snapshot(snapshot)

        await self.stream.publish("competitor", json.dumps(snapshot, ensure_ascii=False))

    @staticmethod
    def _now_iso() -> str:
        from app.core.constants import now_cst
        return now_cst().isoformat()


# ============================================================================
# Kafka Consumer Manager
# ============================================================================


class KafkaConsumerManager:
    """Manages all Kafka consumers lifecycle."""

    def __init__(self, stream_manager, store=None):
        self.stream = stream_manager
        self.store = store  # EcomDataStore — shared with MCP tools
        self.dedup = DedupStore()
        self._consumers: list[BaseKafkaConsumer] = []
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        if not _kafka_reachable():
            logger.warning("Kafka not reachable, skip consumer startup")
            return

        self._consumers = [
            KafkaOrderConsumer(self.stream, self.dedup, self.store),
            KafkaTrafficConsumer(self.stream, self.dedup, self.store),
            KafkaInventoryConsumer(self.stream, self.dedup, self.store),
            KafkaCompetitorConsumer(self.stream, self.dedup, self.store),
        ]

        for c in self._consumers:
            self._tasks.append(asyncio.create_task(c.start()))

        logger.info(f"KafkaConsumerManager started ({len(self._consumers)} consumers)")

    async def stop(self):
        for c in self._consumers:
            await c.stop()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


# ============================================================================
# [预留] Polling Consumer — 从数据库轮询
# ============================================================================
#
# 当公司没有 Kafka 但有 PostgreSQL/MySQL 存订单数据时，取消下方注释并按需修改。
#
# class PollingOrderConsumer:
#     """Periodically poll PostgreSQL/MySQL for new orders.
#
#     使用场景: 公司的订单直接写入关系型数据库，没有 Kafka。
#     实现方式: 记录上次轮询的 max(created_at)，每次只拉取增量数据。
#     """
#
#     def __init__(self, db_session_factory, stream_manager, poll_interval: float = 5.0):
#         self.db = db_session_factory
#         self.stream = stream_manager
#         self._poll_interval = poll_interval
#         self._last_poll_time: Optional[datetime] = None
#         self._running = False
#
#     async def start(self):
#         self._running = True
#         from app.core.constants import now_cst
#
#         # 启动时标记当前时间为起点，只拉之后的新数据
#         self._last_poll_time = now_cst()
#
#         while self._running:
#             try:
#                 async with self.db() as session:
#                     # 查询增量订单（按公司的表结构调整 SQL）
#                     result = await session.execute(
#                         text("""
#                             SELECT order_id, sku, product_name, category,
#                                    qty, unit_price, total_amount,
#                                    channel, region, user_id, created_at
#                             FROM orders
#                             WHERE created_at > :since
#                             ORDER BY created_at ASC
#                             LIMIT 500
#                         """),
#                         {"since": self._last_poll_time}
#                     )
#                     rows = result.fetchall()
#
#                     for row in rows:
#                         order = {
#                             "order_id": row.order_id,
#                             "product_id": row.sku,
#                             "product_name": row.product_name,
#                             "category": row.category,
#                             "quantity": row.qty,
#                             "unit_price": float(row.unit_price),
#                             "total_amount": float(row.total_amount),
#                             "channel": row.channel,
#                             "region": row.region,
#                             "user_id": row.user_id,
#                             "timestamp": row.created_at.isoformat(),
#                         }
#                         await self.stream.publish("orders", json.dumps(order))
#
#                         # 更新游标
#                         if row.created_at > self._last_poll_time:
#                             self._last_poll_time = row.created_at
#
#                     if rows:
#                         logger.debug(f"Polled {len(rows)} new orders")
#
#             except Exception as e:
#                 logger.error(f"Polling error: {e}")
#
#             await asyncio.sleep(self._poll_interval)
#
#     async def stop(self):
#         self._running = False
#
#
# class PollingConsumerManager:
#     """Manages all polling consumers lifecycle.
#
#     在 main.py 中使用:
#         from app.core.database import async_session_factory
#         polling_mgr = PollingConsumerManager(async_session_factory, stream_mgr)
#         await polling_mgr.start()
#     """
#
#     def __init__(self, db_session_factory, stream_manager):
#         self._consumers = [
#             PollingOrderConsumer(db_session_factory, stream_manager, poll_interval=5.0),
#             # 流量/库存/竞品可按相同模式添加
#         ]
#         self._tasks: list[asyncio.Task] = []
#
#     async def start(self):
#         for c in self._consumers:
#             self._tasks.append(asyncio.create_task(c.start()))
#         logger.info(f"PollingConsumerManager started ({len(self._consumers)} pollers)")
#
#     async def stop(self):
#         for c in self._consumers:
#             await c.stop()
#         for t in self._tasks:
#             t.cancel()
#         await asyncio.gather(*self._tasks, return_exceptions=True)
