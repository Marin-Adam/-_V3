"""Dashboard API — real-time metrics and analytics.

Merges memory-based anomaly detection (real-time) with DB-persisted alerts
(confirmed by scheduler) for a complete picture of system health.
"""

from fastapi import APIRouter, Query, Request
from app.data.warehouse import DataWarehouse

router = APIRouter()


@router.get("/overview")
async def get_overview(request: Request):
    """Get real-time dashboard overview: GMV, orders, UV, conversion, + alert count."""
    wh = DataWarehouse(request)
    overview = wh.get_overview()

    # Add open alert count from persisted alerts
    try:
        open_alerts = await wh.get_open_alerts()
        overview["open_alert_count"] = len(open_alerts)
    except Exception:
        overview["open_alert_count"] = 0

    return overview


@router.get("/metrics")
async def get_metrics(request: Request, time_range: str = Query("1h", description="5m/15m/1h/6h/24h")):
    """Get time-series metrics for charts."""
    wh = DataWarehouse(request)
    return {"time_range": time_range, "data": wh.get_metrics(time_range)}


@router.get("/anomalies")
async def get_anomalies(request: Request):
    """Get current active anomalies — merges memory detection + persisted alerts."""
    wh = DataWarehouse(request)

    memory_anomalies = wh.get_anomalies()

    # Also fetch persisted open alerts
    try:
        persisted = await wh.get_open_alerts()
    except Exception:
        persisted = []

    # Merge: persisted first (confirmed), then memory anomalies (dedup by type+timestamp)
    seen = set()
    merged = []
    for a in persisted:
        key = f"{a.get('type', '')}_{a.get('created_at', '')}"
        if key not in seen:
            merged.append(a)
            seen.add(key)

    for a in memory_anomalies:
        key = f"{a.get('type', '')}_{a.get('timestamp', '')}"
        if key not in seen:
            merged.append(a)
            seen.add(key)

    return {"anomalies": merged, "total": len(merged)}


@router.get("/top-products")
async def get_top_products(request: Request, limit: int = Query(10, ge=1, le=50)):
    """Get top-selling products by GMV."""
    wh = DataWarehouse(request)
    return {"products": wh.get_top_products(limit)}
