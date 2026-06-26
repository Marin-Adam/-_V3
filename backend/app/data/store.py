"""Shared in-memory data store for e-commerce entities.

This is the single source of truth that both data producers (Kafka consumers,
DataGenerator) and data consumers (MCP tools, DataWarehouse, AgentEngine)
read from and write to.

Replaces the inline data structures originally embedded in DataGenerator.
"""

import time
from collections import defaultdict
from datetime import datetime
from typing import Optional

from app.core.constants import CST, now_cst


# Product catalog (shared across all modules that need product lookup)
PRODUCTS = [
    {"id": "SKU001", "name": "无线蓝牙耳机 Pro", "category": "数码电子", "price": 299, "cost": 180},
    {"id": "SKU002", "name": "智能手表 S3", "category": "数码电子", "price": 899, "cost": 520},
    {"id": "SKU003", "name": "便携充电宝 20000mAh", "category": "数码电子", "price": 129, "cost": 65},
    {"id": "SKU004", "name": "机械键盘 RGB", "category": "电脑外设", "price": 459, "cost": 280},
    {"id": "SKU005", "name": "电竞鼠标 无线", "category": "电脑外设", "price": 249, "cost": 130},
    {"id": "SKU006", "name": "USB-C 扩展坞 7合1", "category": "电脑外设", "price": 199, "cost": 100},
    {"id": "SKU007", "name": "瑜伽垫 加厚防滑", "category": "运动户外", "price": 89, "cost": 40},
    {"id": "SKU008", "name": "运动水壶 不锈钢", "category": "运动户外", "price": 69, "cost": 30},
    {"id": "SKU009", "name": "空气炸锅 5L", "category": "家用电器", "price": 399, "cost": 220},
    {"id": "SKU010", "name": "扫地机器人 LDS", "category": "家用电器", "price": 1599, "cost": 900},
]

CHANNELS = ["淘宝", "京东", "拼多多", "抖音", "小程序"]
REGIONS = ["华东", "华南", "华北", "西南", "华中"]
COMPETITORS = ["竞品A", "竞品B", "竞品C"]


class EcomDataStore:
    """Thread-safe-ish in-memory store for e-commerce data streams.

    All writes are append-only (orders) or replace (traffic/inventory).
    Reads are lock-free — Python GIL makes this safe for asyncio single-thread.
    """

    def __init__(self):
        # ── Order store ──
        self.orders: list[dict] = []
        self._max_orders = 2000

        # ── Traffic store (cumulative per product) ──
        # pid → {"uv": N, "pv": N, "add_cart": N}
        self.traffic: dict[str, dict] = defaultdict(
            lambda: {"uv": 0, "pv": 0, "add_cart": 0}
        )
        # Initialize with known products
        for p in PRODUCTS:
            self.traffic[p["id"]] = {"uv": 0, "pv": 0, "add_cart": 0}

        # ── Inventory store (pid → current stock) ──
        self.inventory: dict[str, int] = {}
        for p in PRODUCTS:
            self.inventory[p["id"]] = 500  # default initial stock

        # ── Competitor prices (latest window entries, for MCP query) ──
        self.competitor_snapshots: list[dict] = []

        # ── Anomaly injection (only used by DataGenerator fallback) ──
        self._anomaly_active = False

    # ── Order operations ───────────────────────────────────────────

    def add_order(self, order: dict):
        self.orders.append(order)
        if len(self.orders) > self._max_orders:
            self.orders = self.orders[-self._max_orders // 2:]

    def get_recent_orders(self, minutes: int = 60) -> list[dict]:
        """Return orders within the last N minutes."""
        cutoff = now_cst().timestamp() - minutes * 60
        return [o for o in self.orders if _parse_ts(o.get("timestamp", "")) > cutoff]

    # ── Traffic operations ─────────────────────────────────────────

    def update_traffic(self, product_id: str, uv: int = 0, pv: int = 0, add_cart: int = 0):
        """Accumulate traffic counters for a product."""
        if product_id not in self.traffic:
            self.traffic[product_id] = {"uv": 0, "pv": 0, "add_cart": 0}
        self.traffic[product_id]["uv"] += uv
        self.traffic[product_id]["pv"] += pv
        self.traffic[product_id]["add_cart"] += add_cart

    def get_current_traffic(self) -> dict:
        return dict(self.traffic)

    # ── Inventory operations ───────────────────────────────────────

    def set_inventory(self, product_id: str, quantity: int):
        self.inventory[product_id] = quantity

    def get_current_inventory(self) -> dict:
        return dict(self.inventory)

    # ── Competitor operations ──────────────────────────────────────

    def add_competitor_snapshot(self, snapshot: dict):
        self.competitor_snapshots.append(snapshot)
        if len(self.competitor_snapshots) > 200:
            self.competitor_snapshots = self.competitor_snapshots[-100:]

    def get_recent_competitor_snapshots(self, limit: int = 20) -> list[dict]:
        return self.competitor_snapshots[-limit:]

    # ── Anomaly injection (for DataGenerator fallback) ─────────────

    @property
    def anomaly_active(self) -> bool:
        return self._anomaly_active

    @anomaly_active.setter
    def anomaly_active(self, value: bool):
        self._anomaly_active = value


def _parse_ts(ts) -> float:
    """Parse a timestamp string or number to Unix epoch float."""
    if ts is None:
        return 0
    if isinstance(ts, (int, float)):
        return ts if ts < 1e12 else ts / 1000
    try:
        return datetime.fromisoformat(str(ts)).timestamp()
    except Exception:
        return 0
