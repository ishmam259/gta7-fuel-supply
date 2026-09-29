"""Validation of simulator responses. Invalid responses are rejected and raise an alert (brief §11)."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FuelMap = dict[Literal["DIESEL", "PETROL", "OCTANE"], float]


class _M(BaseModel):
    model_config = ConfigDict(extra="allow")


class Instance(_M):
    tick: int = Field(ge=0)
    sim_time: str
    tick_minutes: int = Field(gt=0)
    status: Literal["PAUSED", "RUNNING"]


class Region(_M):
    id: str
    name: str
    demand_factor: float


class Depot(_M):
    id: str
    name: str
    region_id: str
    status: str
    dispatch_capacity_per_tick: float = Field(ge=0)
    capacity: FuelMap
    inventory: FuelMap


class Station(_M):
    id: str
    name: str
    region_id: str
    status: str
    demand_profile: str
    demand_multiplier: float = Field(ge=0)
    capacity: FuelMap
    inventory: FuelMap


class Route(_M):
    id: str
    source_depot_id: str
    destination_station_id: str
    transit_ticks: int = Field(ge=0)
    max_shipment: float = Field(ge=0)
    status: str


class SupplyArrival(_M):
    id: str
    depot_id: str
    fuel_type: str
    quantity: float
    planned_tick: int
    actual_tick: int | None = None
    status: str


class Event(_M):
    id: int
    type: str
    start_tick: int
    end_tick: int | None = None
    status: str
    parameters: dict[str, Any] = {}


class Allocation(_M):
    id: int
    idempotency_key: str
    source_depot_id: str
    destination_station_id: str
    route_id: str
    fuel_type: str
    quantity: float
    created_tick: int
    status: str
    departure_tick: int | None = None
    expected_arrival_tick: int | None = None
    actual_arrival_tick: int | None = None
    failure_reason: str | None = None


class DemandObs(_M):
    station_id: str
    fuel_type: str
    tick: int
    demand_liters: float
    served_liters: float
    unmet_liters: float


class Metrics(_M):
    served_demand_liters: float
    unmet_demand_liters: float
    service_level: float = Field(ge=0, le=1)
    allocation_liters: float
    allocation_failures: int


SCHEMAS: dict[str, type[BaseModel]] = {
    "/v1/instance": Instance,
    "/v1/metrics": Metrics,
    "/v1/regions": Region,
    "/v1/depots": Depot,
    "/v1/stations": Station,
    "/v1/routes": Route,
    "/v1/supply-arrivals": SupplyArrival,
    "/v1/events": Event,
    "/v1/allocations": Allocation,
    "/v1/demand-history": DemandObs,
}
