"""Pydantic models shared between backend core and intel.

Field names match docs/API_CONTRACT.md so the backend can store/return them unchanged.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FuelType = Literal["DIESEL", "PETROL", "OCTANE"]
RiskLevel = Literal["ok", "watch", "critical", "outage"]
Severity = Literal["info", "warning", "critical"]
AlertKind = Literal[
    "shortage_risk", "anomalous_demand", "inventory_anomaly", "bottleneck", "disruption",
    "integration_failure", "low_confidence", "fallback", "recovery",
]
PlanMode = Literal["optimizer", "heuristic", "fallback"]


class Snapshot(BaseModel):
    tick: int
    sim_time: datetime
    tick_minutes: int = 15
    depots: list[dict] = Field(default_factory=list)
    stations: list[dict] = Field(default_factory=list)
    routes: list[dict] = Field(default_factory=list)
    allocations: list[dict] = Field(default_factory=list)
    supply_arrivals: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    demand_history: list[dict] = Field(default_factory=list)
    regions: list[dict] = Field(default_factory=list)  # optional, /v1/regions


class Forecast(BaseModel):
    station_id: str
    fuel_type: FuelType
    horizon_ticks: int = 16
    per_tick: list[float]
    lower: list[float]
    upper: list[float]
    mape_recent: float | None = None
    residual_std: float = 0.0


class Risk(BaseModel):
    station_id: str
    fuel_type: FuelType
    level: RiskLevel
    stockout_hours: float
    stockout_prob: float
    current_inventory: float = 0.0
    next_supply_eta_tick: int | None = None      # next shipment reaching the station
    incoming_liters: float = 0.0                 # PENDING + IN_TRANSIT to the station
    depot_supply_eta_tick: int | None = None     # next supply arrival at a depot that serves this station
    depot_supply_delayed: bool = False           # that upstream supply is DELAYED


class AlertEntity(BaseModel):
    type: Literal["station", "depot", "route", "supply", "system"]
    id: str
    fuel_type: FuelType | None = None


class AlertDraft(BaseModel):
    tick: int
    severity: Severity
    kind: AlertKind
    entity: AlertEntity
    title: str
    detail: str = ""
    code: str = ""  # sub-type within kind, e.g. "dispatch" / "low_stock" for bottleneck

    @property
    def key(self) -> str:
        """Stable identity for de-duplicating / resolving the same condition across ticks."""
        return f"{self.kind}:{self.entity.type}:{self.entity.id}:{self.entity.fuel_type or ''}:{self.code}"


class AllocationPlan(BaseModel):
    source_depot_id: str
    route_id: str
    quantity: float
    eta_tick: int


class Alternative(AllocationPlan):
    stockout_prob_after: float


class Situation(BaseModel):
    current_inventory: float
    expected_demand_next_4h: float
    projected_stockout_hours: float


class ExpectedImpact(BaseModel):
    stockout_prob_before: float
    stockout_prob_after: float
    unmet_liters_avoided: float


class RecommendationDraft(BaseModel):
    tick: int
    mode: PlanMode
    station_id: str
    fuel_type: FuelType
    allocation: AllocationPlan
    situation: Situation
    expected_impact: ExpectedImpact
    confidence: float
    requires_human_review: bool = False
    signals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    explanation: str = ""


class ProjectionPoint(BaseModel):
    tick: int
    inventory: float


class WhatIf(BaseModel):
    projection_without: list[ProjectionPoint]
    projection_with: list[ProjectionPoint]
    stockout_prob_before: float
    stockout_prob_after: float
