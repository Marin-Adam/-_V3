"""Data warehouse — aggregation queries over generated data streams."""

import json
from typing import Optional

from fastapi import Request

from app.core.constants import CST, now_cst


class DataWarehouse:
    """Provides aggregated analytics over in-memory data streams.

    In production this would query a real data warehouse (ClickHouse, etc).
    For the MVP, it reads from the DataGenerator's in-memory state.
    """

    def __init__(self, request: Optional[Request] = None):
        self._gen = None
        self._streams = None
        self._store = None
        if request and hasattr(request.app.state, "data_generator"):
            self._gen = request.app.state.data_generator
            self._streams = request.app.state.stream_manager
            self._store = request.app.state.data_store if hasattr(request.app.state, "data_store") else None

    # ── Data access helpers ─────────────────────────────────────

    def _get_orders(self, minutes: int) -> list[dict]:
        """Best-effort: store → generator → empty."""
        if self._store:
            return self._store.get_recent_orders(minutes)
        if self._gen:
            return self._gen.get_recent_orders(minutes)
        return []

    def _get_traffic(self) -> dict:
        if self._store:
            return self._store.get_current_traffic()
        if self._gen:
            return self._gen.get_current_traffic()
        return {}

    def _get_inventory(self) -> dict:
        if self._store:
            return self._store.get_current_inventory()
        if self._gen:
            return self._gen.inventory
        return {}

    @property
    def _anomaly_flag(self) -> bool:
        if self._store:
            return self._store.anomaly_active
        if self._gen:
            return self._gen._anomaly_active
        return False

    # ── Dashboard Overview ────────────────────────────────────────

    def get_overview(self) -> dict:
        """Real-time dashboard overview metrics."""
        recent_orders = self._get_orders(60)
        if not recent_orders and not self._gen:
            return _empty_overview()

        total_gmv = sum(o["total_amount"] for o in recent_orders)
        order_count = len(recent_orders)

        traffic = self._get_traffic()
        total_cumulative_uv = sum(t["uv"] for t in traffic.values())
        total_pv = sum(t["pv"] for t in traffic.values())
        total_cart = sum(t["add_cart"] for t in traffic.values())

        # Use stream window to estimate UV within the same 60-min window as orders.
        # Traffic data is cumulative per product — we compute per-product UV delta
        # between the earliest and latest event in the traffic window, then sum.
        if self._streams:
            traffic_window = self._streams.get_window("traffic", limit=1000)
            if len(traffic_window) >= 2:
                # Group by product_id, track first and last cumulative UV per product
                product_uv_range: dict[str, dict[str, int]] = {}
                for event in traffic_window:
                    pid = event.get("product_id") if isinstance(event, dict) else None
                    uv = event.get("uv", 0) if isinstance(event, dict) else 0
                    if pid:
                        if pid not in product_uv_range:
                            product_uv_range[pid] = {"first": uv, "last": uv}
                        else:
                            product_uv_range[pid]["last"] = uv
                total_uv = sum(
                    max(0, v["last"] - v["first"])
                    for v in product_uv_range.values()
                )
                # Fall back to cumulative UV if delta is zero (window too short)
                if total_uv == 0:
                    total_uv = total_cumulative_uv
            else:
                total_uv = total_cumulative_uv
        else:
            total_uv = total_cumulative_uv
        conversion = round(order_count / total_uv * 100, 2) if total_uv > 0 else 0

        # Channel breakdown
        channel_gmv = {}
        for o in recent_orders:
            ch = o["channel"]
            channel_gmv[ch] = channel_gmv.get(ch, 0) + o["total_amount"]

        # Category breakdown
        cat_gmv = {}
        for o in recent_orders:
            cat = o["category"]
            cat_gmv[cat] = cat_gmv.get(cat, 0) + o["total_amount"]

        return {
            "gmv": round(total_gmv, 2),
            "order_count": order_count,
            "total_uv": total_uv,
            "total_pv": total_pv,
            "conversion_rate": conversion,
            "add_cart_count": total_cart,
            "channel_breakdown": channel_gmv,
            "category_breakdown": cat_gmv,
            "anomaly_active": self._anomaly_flag,
            "timestamp": now_cst().isoformat(),
        }

    # ── Metrics Time Series ───────────────────────────────────────

    def get_metrics(self, time_range: str = "1h") -> list[dict]:
        """Get time-series metrics for charting.

        Returns data points at 5-minute intervals, zero-filling empty slots.
        """
        from datetime import timedelta

        minutes = {"5m": 5, "15m": 15, "1h": 60, "6h": 360, "24h": 1440}.get(time_range, 60)
        orders = self._get_orders(minutes)

        bucket_minutes = 5
        now = now_cst().replace(second=0, microsecond=0)

        # Generate buckets by subtracting timedelta (avoids negative minute bug)
        all_buckets = {}
        for i in range(minutes // bucket_minutes):
            bucket_time = now - timedelta(minutes=i * bucket_minutes)
            bucket_time = bucket_time.replace(
                minute=(bucket_time.minute // bucket_minutes) * bucket_minutes,
                second=0, microsecond=0
            )
            key = bucket_time.strftime("%Y-%m-%dT%H:%M")
            if key not in all_buckets:
                all_buckets[key] = {"time": key, "gmv": 0, "orders": 0}

        # Aggregate orders into buckets
        for o in orders:
            ts_str = o.get("timestamp", "")
            if not ts_str or len(ts_str) < 16:
                continue
            try:
                from datetime import datetime
                parsed = datetime.strptime(ts_str[:16], "%Y-%m-%dT%H:%M")
                rounded = (parsed.minute // bucket_minutes) * bucket_minutes
                bucket_key = parsed.replace(minute=rounded, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
                if bucket_key in all_buckets:
                    all_buckets[bucket_key]["gmv"] += o.get("total_amount", 0)
                    all_buckets[bucket_key]["orders"] += 1
            except Exception:
                pass

        return sorted(all_buckets.values(), key=lambda x: x["time"])

    # ── Anomalies ─────────────────────────────────────────────────

    def get_anomalies(self) -> list[dict]:
        """Detect current anomalies from data streams."""
        anomalies = []

        # GMV anomaly check
        recent_5m = self._get_orders(5)
        recent_60m = self._get_orders(60)
        gmv_5m = sum(o["total_amount"] for o in recent_5m)
        expected_5m = sum(o["total_amount"] for o in recent_60m) / 12 if recent_60m else 1

        if expected_5m > 0:
            deviation = (gmv_5m - expected_5m) / expected_5m
            if abs(deviation) > 0.3:
                severity = "P0" if abs(deviation) > 0.5 else "P1"
                anomalies.append({
                    "type": "gmv_deviation",
                    "severity": severity,
                    "description": f"GMV 5分钟均值偏离{'上升' if deviation > 0 else '下降'}{abs(deviation)*100:.0f}%",
                    "current_value": round(gmv_5m, 2),
                    "expected_value": round(expected_5m, 2),
                    "deviation_pct": round(deviation * 100, 1),
                    "timestamp": now_cst().isoformat(),
                })

        # Low stock alerts
        product_names = {p["id"]: p["name"] for p in _PRODUCTS_CACHE}
        inventory = self._get_inventory()
        for pid, qty in inventory.items():
            if qty < 20:
                pname = product_names.get(pid, pid)
                anomalies.append({
                    "type": "low_stock",
                    "severity": "P1" if qty < 10 else "P2",
                    "description": f"库存预警: {pname} ({pid}) 仅剩 {qty} 件",
                    "product_id": pid,
                    "current_stock": qty,
                    "timestamp": now_cst().isoformat(),
                })

        return anomalies[:10]  # Top 10

    # ── Top Products ──────────────────────────────────────────────

    def get_top_products(self, limit: int = 10) -> list[dict]:
        recent = self._get_orders(60)
        if not recent:
            return []
        product_gmv = {}
        product_orders = {}
        for o in recent:
            pid = o["product_id"]
            product_gmv[pid] = product_gmv.get(pid, 0) + o["total_amount"]
            product_orders[pid] = product_orders.get(pid, 0) + 1

        results = []
        for pid, gmv in sorted(product_gmv.items(), key=lambda x: x[1], reverse=True)[:limit]:
            results.append({
                "product_id": pid,
                "product_name": next((p["name"] for p in _PRODUCTS_CACHE if p["id"] == pid), pid),
                "gmv": round(gmv, 2),
                "orders": product_orders[pid],
            })
        return results

    # ── Alert Persistence ──────────────────────────────────────────

    async def save_alert(self, alert_dict: dict) -> Optional[str]:
        """Persist an alert to the AlertRecord table. Returns alert_id."""
        import uuid
        from app.models.metrics import AlertRecord
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as session:
                alert = AlertRecord(
                    severity=alert_dict.get("severity", "P2"),
                    alert_type=alert_dict.get("type", "unknown"),
                    title=alert_dict.get("title", alert_dict.get("description", "")),
                    description=alert_dict.get("description", ""),
                    metric_value=alert_dict.get("current_value"),
                    expected_value=alert_dict.get("expected_value"),
                    deviation_pct=alert_dict.get("deviation_pct"),
                    status="open",
                )
                session.add(alert)
                await session.commit()
                await session.refresh(alert)
                logger.info(f"Alert saved: {alert.id} [{alert.severity}] {alert.title}")
                return str(alert.id)
        except Exception as e:
            logger.error(f"Failed to save alert: {e}")
            return None

    async def resolve_alert(self, alert_id: str) -> bool:
        """Mark an alert as resolved."""
        from datetime import datetime, timezone
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as session:
                from sqlalchemy import update
                from app.models.metrics import AlertRecord
                stmt = (
                    update(AlertRecord)
                    .where(AlertRecord.id == alert_id)
                    .values(status="resolved", resolved_at=datetime.now(timezone.utc))
                )
                result = await session.execute(stmt)
                await session.commit()
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to resolve alert {alert_id}: {e}")
            return False

    async def get_open_alerts(self, severity: str = None) -> list[dict]:
        """Query open (unresolved) alerts, optionally filtered by severity."""
        from app.models.metrics import AlertRecord
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as session:
                from sqlalchemy import select
                stmt = select(AlertRecord).where(AlertRecord.status == "open")
                if severity:
                    stmt = stmt.where(AlertRecord.severity == severity)
                stmt = stmt.order_by(AlertRecord.created_at.desc()).limit(50)
                result = await session.execute(stmt)
                alerts = result.scalars().all()
                return [
                    {
                        "id": str(a.id),
                        "severity": a.severity,
                        "type": a.alert_type,
                        "title": a.title,
                        "description": a.description,
                        "deviation_pct": a.deviation_pct,
                        "status": a.status,
                        "created_at": a.created_at.isoformat() if a.created_at else None,
                    }
                    for a in alerts
                ]
        except Exception as e:
            logger.error(f"Failed to query open alerts: {e}")
            return []

    def get_rolling_baseline(self, minutes: int = 60) -> float:
        """Compute rolling-average GMV over the given window for anomaly baseline.

        Used by AgentEngine (instead of the old hardcoded hourly_avg=100).
        Returns average GMV per 5-minute bucket over the window.
        """
        orders = self._get_orders(minutes)
        if not orders:
            return 0.0

        total_gmv = sum(o["total_amount"] for o in orders)
        buckets = max(1, minutes / 5)  # number of 5-min buckets in the window
        return round(total_gmv / buckets, 2)


# Product name lookup cache
_PRODUCTS_CACHE = [
    {"id": "SKU001", "name": "无线蓝牙耳机 Pro"},
    {"id": "SKU002", "name": "智能手表 S3"},
    {"id": "SKU003", "name": "便携充电宝 20000mAh"},
    {"id": "SKU004", "name": "机械键盘 RGB"},
    {"id": "SKU005", "name": "电竞鼠标 无线"},
    {"id": "SKU006", "name": "USB-C 扩展坞 7合1"},
    {"id": "SKU007", "name": "瑜伽垫 加厚防滑"},
    {"id": "SKU008", "name": "运动水壶 不锈钢"},
    {"id": "SKU009", "name": "空气炸锅 5L"},
    {"id": "SKU010", "name": "扫地机器人 LDS"},
]


def _empty_overview() -> dict:
    return {
        "gmv": 0, "order_count": 0, "total_uv": 0, "total_pv": 0,
        "conversion_rate": 0, "add_cart_count": 0,
        "channel_breakdown": {}, "category_breakdown": {},
        "anomaly_active": False, "timestamp": now_cst().isoformat(),
    }
