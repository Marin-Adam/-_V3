"""ORM models for metrics, alerts, and skill execution logs."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AlertRecord(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    severity: Mapped[str] = mapped_column(String(8), nullable=False, index=True)  # P0/P1/P2
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)  # gmv_deviation/low_stock/traffic_drop
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    metric_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    deviation_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open/acknowledged/resolved
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column(JSON, default=dict, name="metadata")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SkillExecution(Base):
    __tablename__ = "skill_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(String(16), nullable=False)  # scheduled/manual/event
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/success/failed
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DashboardSnapshot(Base):
    __tablename__ = "dashboard_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gmv: Mapped[float] = mapped_column(Float, default=0)
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    total_uv: Mapped[int] = mapped_column(Integer, default=0)
    conversion_rate: Mapped[float] = mapped_column(Float, default=0)
    snapshot_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
