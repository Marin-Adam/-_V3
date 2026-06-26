"""Pre-aggregation Job — periodic aggregation for fast dashboard queries.

V3.0: Runs every 5 minutes to pre-compute:
  - agg_region_5min: regional sales aggregation (avoids partition-scan)
  - agg_category_5min: category sales aggregation
  - agg_age_5min: age group distribution

This prevents full-table scans when querying without partition keys.
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from loguru import logger

from app.core.constants import CST, now_cst
from app.data.store import EcomDataStore, PRODUCTS, REGIONS


class PreAggregationJob:
    """Periodic pre-aggregation job for the insights dashboard."""

    def __init__(self, store: EcomDataStore = None, interval_sec: int = 300):
        self.store = store
        self.interval = interval_sec
        self._running = False
        self._task = None

        # In-memory aggregation cache (in production: write to MySQL agg tables)
        self.region_agg: dict[str, dict] = {}
        self.category_agg: dict[str, dict] = {}
        self.age_agg: dict[str, dict] = {}

    async def start(self):
        """Start periodic aggregation."""
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"PreAggregationJob: started (interval={self.interval}s)")

    async def stop(self):
        """Stop the job."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PreAggregationJob: stopped")

    async def _loop(self):
        """Main loop: aggregate every interval_sec seconds."""
        while self._running:
            try:
                await self.run_once()
            except Exception as e:
                logger.error(f"PreAggregationJob: aggregation failed: {e}")
            await asyncio.sleep(self.interval)

    async def run_once(self):
        """Execute one aggregation cycle."""
        if not self.store:
            return

        orders = self.store.get_recent_orders(60)  # last hour
        if not orders:
            logger.debug("PreAggregationJob: no orders to aggregate")
            return

        # ── Region aggregation ────────────────────────────────────
        region_gmv = {}
        region_orders = {}
        for o in orders:
            region = o.get("region", "unknown")
            region_gmv[region] = region_gmv.get(region, 0) + o.get("total_amount", 0)
            region_orders[region] = region_orders.get(region, 0) + 1

        self.region_agg = {
            region: {"gmv": round(gmv, 2), "orders": cnt, "update_time": now_cst().isoformat()}
            for region, gmv in region_gmv.items()
            for cnt in [region_orders[region]]
        }

        # ── Category aggregation ──────────────────────────────────
        cat_gmv = {}
        for o in orders:
            cat = o.get("category", "unknown")
            cat_gmv[cat] = cat_gmv.get(cat, 0) + o.get("total_amount", 0)

        self.category_agg = {
            cat: {"gmv": round(gmv, 2), "update_time": now_cst().isoformat()}
            for cat, gmv in sorted(cat_gmv.items(), key=lambda x: x[1], reverse=True)
        }

        # ── Age group aggregation ─────────────────────────────────
        age_gmv = {}
        for o in orders:
            age = o.get("age_group", "unknown")
            age_gmv[age] = age_gmv.get(age, 0) + o.get("total_amount", 0)

        self.age_agg = {
            age: {"gmv": round(gmv, 2), "update_time": now_cst().isoformat()}
            for age, gmv in sorted(age_gmv.items(), key=lambda x: x[1], reverse=True)
        }

        logger.debug(
            f"PreAggregationJob: aggregated {len(orders)} orders → "
            f"{len(region_gmv)} regions, {len(cat_gmv)} categories, {len(age_gmv)} age groups"
        )

    def get_region_agg(self) -> dict:
        return self.region_agg

    def get_category_agg(self) -> dict:
        return self.category_agg

    def get_age_agg(self) -> dict:
        return self.age_agg


# ── Standalone runner ─────────────────────────────────────────────

async def main():
    """Run pre-aggregation as a standalone service."""
    logger.info("Starting PreAggregationJob standalone...")

    store = EcomDataStore()
    # In standalone mode, we need data — load from demo data or generator
    from app.data.generator import DataGenerator
    from app.data.streams import StreamManager
    stream_mgr = StreamManager()
    gen = DataGenerator(stream_mgr, store=store)
    await gen.start()

    job = PreAggregationJob(store=store)
    await job.start()

    # Run indefinitely
    try:
        while True:
            await asyncio.sleep(10)
            agg = job.get_category_agg()
            if agg:
                logger.info(f"Current category aggregation: {json.dumps(agg, ensure_ascii=False)}")
            else:
                logger.info("Waiting for data...")
    except KeyboardInterrupt:
        await job.stop()
        await gen.stop()


if __name__ == "__main__":
    asyncio.run(main())
