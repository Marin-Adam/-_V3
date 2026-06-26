"""Simulated e-commerce data generator (fallback when Kafka is unavailable).

Produces real-time streams by writing into the shared EcomDataStore:
  - Orders: 1 order every 1-5 seconds
  - Traffic: UV/PV/Add-to-cart every 10 seconds
  - Inventory: stock levels every 30 seconds
  - Competitor prices: every 5 minutes
  - Anomaly injection: randomly introduces spikes/drops

When Kafka consumers are active, this generator is not started.
Both Kafka consumers and this generator write to the SAME EcomDataStore,
so MCP tools and DataWarehouse work identically regardless of data source.
"""

import asyncio
import json
import random
import time
from datetime import datetime

from loguru import logger

from app.core.config import get_settings
from app.core.constants import CST, now_cst
from app.data.store import EcomDataStore, PRODUCTS, CHANNELS, REGIONS, COMPETITORS

settings = get_settings()


class DataGenerator:
    """Background task that generates simulated e-commerce data into a shared store."""

    def __init__(self, stream_manager=None, store: EcomDataStore = None):
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self.stream = stream_manager
        self.store = store or EcomDataStore()

        # Initialize with random stock
        for p in PRODUCTS:
            self.store.set_inventory(p["id"], random.randint(50, 500))

    # ── Public properties (backward compat for existing code) ────

    @property
    def orders(self) -> list[dict]:
        return self.store.orders

    @property
    def traffic(self) -> dict:
        return self.store.traffic

    @property
    def inventory(self) -> dict:
        return self.store.inventory

    @property
    def _anomaly_active(self) -> bool:
        return self.store.anomaly_active

    @_anomaly_active.setter
    def _anomaly_active(self, value: bool):
        self.store.anomaly_active = value

    def get_recent_orders(self, minutes: int = 60) -> list[dict]:
        return self.store.get_recent_orders(minutes)

    def get_current_traffic(self) -> dict:
        return self.store.get_current_traffic()

    def get_current_inventory(self) -> dict:
        return self.store.get_current_inventory()

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self):
        self._running = True
        self._tasks = [
            asyncio.create_task(self._generate_orders()),
            asyncio.create_task(self._generate_traffic()),
            asyncio.create_task(self._generate_inventory()),
            asyncio.create_task(self._generate_competitor_data()),
            asyncio.create_task(self._anomaly_controller()),
        ]
        logger.info("DataGenerator started (5 streams → shared store)")

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ── Order Stream ──────────────────────────────────────────────

    async def _generate_orders(self):
        while self._running:
            product = random.choice(PRODUCTS)
            quantity = random.choices([1, 2, 3, 5], weights=[70, 20, 8, 2])[0]
            base_price = product["price"]
            if self.store.anomaly_active:
                base_price *= random.choice([0.5, 0.7, 1.5, 1.8])

            order = {
                "order_id": f"ORD-{int(time.time()*1000)}-{random.randint(100,999)}",
                "product_id": product["id"],
                "product_name": product["name"],
                "category": product["category"],
                "quantity": quantity,
                "unit_price": base_price,
                "total_amount": round(base_price * quantity, 2),
                "channel": random.choice(CHANNELS),
                "region": random.choice(REGIONS),
                "timestamp": now_cst().isoformat(),
            }
            self.store.add_order(order)

            if self.stream:
                await self.stream.publish("orders", json.dumps(order, ensure_ascii=False))

            interval = settings.DATA_GEN_ORDER_INTERVAL * random.uniform(0.5, 2.5)
            await asyncio.sleep(interval)

    # ── Traffic Stream ────────────────────────────────────────────

    async def _generate_traffic(self):
        while self._running:
            for product in PRODUCTS:
                pid = product["id"]
                uv_inc = random.randint(5, 50) if not self.store.anomaly_active else random.randint(2, 15)
                pv_inc = uv_inc * random.randint(2, 5)
                cart_inc = int(uv_inc * random.uniform(0.02, 0.12))

                self.store.update_traffic(pid, uv_inc, pv_inc, cart_inc)

                if self.stream:
                    await self.stream.publish("traffic", json.dumps({
                        "product_id": pid, "product_name": product["name"],
                        "uv": self.store.traffic[pid]["uv"],
                        "pv": self.store.traffic[pid]["pv"],
                        "add_cart": self.store.traffic[pid]["add_cart"],
                        "timestamp": now_cst().isoformat(),
                    }, ensure_ascii=False))

            await asyncio.sleep(settings.DATA_GEN_TRAFFIC_INTERVAL)

    # ── Inventory Stream ──────────────────────────────────────────

    async def _generate_inventory(self):
        while self._running:
            for product in PRODUCTS:
                pid = product["id"]
                sold = random.randint(0, 5)
                old = self.store.inventory.get(pid, 100)
                self.store.set_inventory(pid, max(0, old - sold))

                alert = None
                qty = self.store.inventory[pid]
                if qty < 20:
                    alert = "low_stock"
                elif qty < 50:
                    alert = "warning"

                if self.stream:
                    await self.stream.publish("inventory", json.dumps({
                        "product_id": pid, "product_name": product["name"],
                        "quantity": qty, "alert": alert,
                        "timestamp": now_cst().isoformat(),
                    }, ensure_ascii=False))

            await asyncio.sleep(settings.DATA_GEN_INVENTORY_INTERVAL)

    # ── Competitor Stream ─────────────────────────────────────────

    async def _generate_competitor_data(self):
        while self._running:
            for product in random.sample(PRODUCTS, 3):
                competitor_prices = []
                for comp in COMPETITORS:
                    price = round(product["price"] * random.uniform(1.05, 1.35), 2)
                    if self.store.anomaly_active:
                        price = round(product["price"] * random.uniform(0.70, 1.05), 2)
                    competitor_prices.append({"competitor": comp, "price": price})

                snapshot = {
                    "product_id": product["id"], "product_name": product["name"],
                    "our_price": product["price"], "competitor_prices": competitor_prices,
                    "timestamp": now_cst().isoformat(),
                }
                self.store.add_competitor_snapshot(snapshot)

                if self.stream:
                    await self.stream.publish("competitor", json.dumps(snapshot, ensure_ascii=False))

            await asyncio.sleep(settings.DATA_GEN_COMPETITOR_INTERVAL)

    # ── Anomaly Controller ────────────────────────────────────────

    async def _anomaly_controller(self):
        """Randomly inject anomaly periods to test detection."""
        while self._running:
            await asyncio.sleep(random.randint(120, 300))
            if random.random() < 0.3:
                self.store.anomaly_active = True
                duration = random.randint(30, 90)
                logger.warning(f"Anomaly injected for {duration}s")
                await asyncio.sleep(duration)
                self.store.anomaly_active = False
                logger.info("Anomaly ended")
