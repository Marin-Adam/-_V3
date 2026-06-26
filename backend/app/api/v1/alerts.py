"""Alerts API — alert management and rules.

Queries both:
  - Real-time memory anomalies (from DataWarehouse.get_anomalies — immediate detection)
  - Persisted alerts (from AlertRecord table — historical & confirmed by scheduler)
"""

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.data.warehouse import DataWarehouse

router = APIRouter()


class ResolveAlertRequest(BaseModel):
    status: str = Field("resolved")


class AlertRuleRequest(BaseModel):
    name: str
    metric: str
    condition: str  # e.g. "deviation > 30%"
    severity: str = "P1"
    enabled: bool = True


@router.get("")
async def list_alerts(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    level: str = Query(None, description="P0/P1/P2"),
):
    """List all alerts — merges real-time anomalies with persisted alert records."""
    wh = DataWarehouse(request)

    # ── 1. Real-time anomalies (from memory-based detection, always fresh) ──
    all_anomalies = wh.get_anomalies()

    # ── 2. Persisted alerts (from scheduler → AlertRecord table) ──
    persisted = await wh.get_open_alerts(severity=level)
    # Merge: persisted alerts first (confirmed by scheduler), then memory anomalies
    seen_ids = {a.get("id", "") for a in persisted if a.get("id")}
    for anomaly in all_anomalies:
        # Anomalies from get_anomalies() don't have persistent IDs;
        # use a compound key to avoid duplicates with persisted alerts
        key = f"{anomaly.get('type')}_{anomaly.get('timestamp', '')}"
        if key not in seen_ids:
            anomaly["id"] = key
            persisted.append(anomaly)
            seen_ids.add(key)

    if level:
        persisted = [a for a in persisted if a.get("severity") == level]

    total = len(persisted)
    start = (page - 1) * page_size
    items = persisted[start:start + page_size]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.put("/{alert_id}")
async def resolve_alert(alert_id: str, request: Request, body: ResolveAlertRequest = None):
    """Mark an alert as resolved. Updates AlertRecord in database."""
    wh = DataWarehouse(request)
    success = await wh.resolve_alert(alert_id)

    if not success:
        # May be a memory-only anomaly (no DB record) — return OK anyway
        logger.debug(f"Alert {alert_id} resolved (no DB record to update, may be memory-only)")

    return {
        "alert_id": alert_id,
        "status": "resolved",
    }


@router.post("/rules")
async def create_alert_rule(rule: AlertRuleRequest):
    """Create a new alert rule."""
    return {"status": "created", "rule": rule.model_dump()}
