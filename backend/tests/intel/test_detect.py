import copy
import json
from pathlib import Path

import pytest

from app.intel.detect import detect
from app.intel.forecast import forecast
from app.intel.models import Snapshot

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def pair() -> dict:
    return json.loads((FIX / "pair_live.json").read_text())


@pytest.fixture
def raw() -> dict:
    return json.loads((FIX / "snapshot_tick24.json").read_text())  # healthy network


def run(now: dict, prev: dict | None = None):
    s = Snapshot(**now)
    return detect(s, forecast(s), Snapshot(**prev) if prev else None)


def kinds(alerts, kind):
    return [a for a in alerts if a.kind == kind]


def test_healthy_network_is_quiet(raw):
    alerts = run(raw)
    assert all(a.severity != "critical" for a in alerts)
    assert not kinds(alerts, "disruption") and not kinds(alerts, "anomalous_demand")


def test_keys_unique(pair):
    alerts = run(pair["now"], pair["prev"])
    assert len({a.key for a in alerts}) == len(alerts)


# ---- inventory accounting (real simulator snapshots) ----
@pytest.mark.parametrize("prev", ["prev", "mid"])
def test_no_false_inventory_anomaly_on_live_data(pair, prev):
    assert not kinds(run(pair["now"], pair[prev]), "inventory_anomaly")


def test_station_leak_detected(pair):
    now = copy.deepcopy(pair["now"])
    st = next(x for x in now["stations"] if x["id"] == "station-coxsbazar")
    st["inventory"]["DIESEL"] -= 1500
    [a] = kinds(run(now, pair["prev"]), "inventory_anomaly")
    assert a.entity.id == "station-coxsbazar" and a.entity.fuel_type == "DIESEL" and "drop" in a.title


def test_depot_leak_detected(pair):
    now = copy.deepcopy(pair["now"])
    next(d for d in now["depots"] if d["id"] == "depot-gazipur")["inventory"]["OCTANE"] -= 4000
    [a] = kinds(run(now, pair["prev"]), "inventory_anomaly")
    assert a.entity.type == "depot" and a.entity.id == "depot-gazipur"


def test_no_prev_no_inventory_check(pair):
    assert not kinds(run(pair["now"]), "inventory_anomaly")


# ---- demand ----
def test_demand_zscore_spike(raw):
    last = max(h["tick"] for h in raw["demand_history"])
    row = next(h for h in raw["demand_history"] if h["tick"] == last and h["station_id"] == "station-tongi" and h["fuel_type"] == "DIESEL")
    row["demand_liters"] *= 3
    [a] = [x for x in kinds(run(raw), "anomalous_demand") if x.entity.fuel_type]
    assert a.entity.id == "station-tongi" and a.severity == "critical"


def test_demand_multiplier_alert(raw):
    raw["stations"][0]["demand_multiplier"] = 1.8
    alerts = kinds(run(raw), "anomalous_demand")
    assert any(a.code == "multiplier" and a.entity.id == raw["stations"][0]["id"] for a in alerts)


# ---- bottlenecks ----
def test_dispatch_saturation(raw):
    raw["allocations"] = [{"id": i, "source_depot_id": "depot-gazipur", "destination_station_id": "station-mirpur",
                           "route_id": "route-gazipur-mirpur", "fuel_type": "DIESEL", "quantity": 5500,
                           "created_tick": raw["tick"], "status": "PENDING"} for i in (1, 2)]
    assert any(a.code == "dispatch" and a.entity.id == "depot-gazipur" for a in kinds(run(raw), "bottleneck"))


def test_constrained_depot(raw):
    raw["depots"][1]["status"] = "CONSTRAINED"
    alerts = run(raw)
    assert any(a.code == "constrained" for a in kinds(alerts, "bottleneck"))
    assert not any(a.entity.type == "depot" for a in kinds(alerts, "disruption"))  # still shippable


def test_low_depot_stock(raw):
    next(d for d in raw["depots"] if d["id"] == "depot-patiya")["inventory"]["OCTANE"] = 300
    [a] = [x for x in kinds(run(raw), "bottleneck") if x.code == "low_stock"]
    assert a.entity.id == "depot-patiya" and a.entity.fuel_type == "OCTANE" and a.severity == "critical"


# ---- disruptions ----
def test_route_disruption_with_and_without_alternative(raw):
    routes = {r["id"]: r for r in raw["routes"]}
    routes["route-gazipur-mirpur"]["status"] = "DISRUPTED"       # mirpur still has route-patiya-mirpur
    routes["route-gazipur-tongi"]["status"] = "DISRUPTED"        # tongi has no other route
    by_id = {a.entity.id: a for a in kinds(run(raw), "disruption")}
    assert by_id["route-gazipur-mirpur"].severity == "warning" and "route-patiya-mirpur" in by_id["route-gazipur-mirpur"].detail
    assert by_id["route-gazipur-tongi"].severity == "critical"


def test_outages_events_and_delays(raw):
    raw["stations"][2]["status"] = "OUTAGE"
    raw["depots"][0]["status"] = "CLOSED"
    raw["events"] = [{"id": 7, "type": "demand_spike", "start_tick": 20, "end_tick": 40, "status": "ACTIVE",
                      "parameters": {"region_ids": ["region-dhaka"], "multiplier": 1.8}}]
    sup = next(a for a in raw["supply_arrivals"] if a["status"] == "SCHEDULED")
    sup["status"], sup["planned_tick"] = "DELAYED", sup["planned_tick"] + 4
    ids = {(a.entity.type, a.entity.id) for a in kinds(run(raw), "disruption")}
    assert ("station", raw["stations"][2]["id"]) in ids
    assert ("depot", raw["depots"][0]["id"]) in ids
    assert ("system", "event-7") in ids
    assert ("supply", sup["id"]) in ids


def test_broken_input_does_not_crash(raw):
    raw["routes"].append({"id": "weird"})  # missing fields
    raw["depots"][0]["capacity"] = {}
    assert isinstance(run(raw, raw), list)
