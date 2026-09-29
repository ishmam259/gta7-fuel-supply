"""SQLite persistence: recommendations, decision audit, alerts, metrics history."""
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, Session, SQLModel, create_engine, select, text

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Recommendation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    tick: int = Field(index=True)
    status: str = Field(default="pending", index=True)  # pending|approved|executed|rejected|failed|superseded
    station_id: str = Field(index=True)
    fuel_type: str
    mode: str = "heuristic"  # optimizer|heuristic|fallback
    confidence: float = 0.0
    requires_human_review: bool = True
    body: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    sim_allocation_id: int | None = None
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Decision(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    tick: int
    actor: str  # operator|autopilot|system
    action: str  # approve|reject|execute|fallback|cancel
    recommendation_id: int | None = None
    result: str = "OK"
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Alert(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    tick: int = Field(index=True)
    severity: str  # info|warning|critical
    kind: str = Field(index=True)
    entity: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    dedupe_key: str = Field(index=True)
    title: str
    detail: str = ""
    status: str = Field(default="open", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


class SharedState(SQLModel, table=True):
    """Latest engine state, written by the engine every sync, read by API replicas."""
    id: int = Field(default=1, primary_key=True)
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=utcnow)


class MetricPoint(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    tick: int = Field(index=True)
    service_level: float
    unmet_demand_liters: float
    allocation_liters: float
    open_alerts: int
    created_at: datetime = Field(default_factory=utcnow)


_engine = None


def engine():
    global _engine
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite:///"):
            path = url.removeprefix("sqlite:///")
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if url.startswith("sqlite"):
            _engine = create_engine(url, connect_args={"check_same_thread": False})
        else:
            _engine = create_engine(url, pool_size=10, max_overflow=10, pool_pre_ping=True)
    return _engine


def init_db() -> None:
    SQLModel.metadata.create_all(engine())


def session() -> Session:
    return Session(engine())


def db_healthy() -> bool:
    try:
        with session() as s:
            s.connection().execute(text("SELECT 1"))
        return True
    except Exception:
        return False
