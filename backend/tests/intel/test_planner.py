import json
from pathlib import Path

import pytest

import app.intel.planner as planner
from app.intel.forecast import forecast
from app.intel.models import AllocationPlan, Snapshot
from app.intel.planner import MIN_QTY, ROUND_TO, fallback_plan, plan, simulate, violations
from app.intel.risk import assess_risk

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text())


def run(raw: dict):
    s = Snapshot(**raw)
    fc = forecast(s)
    return s, plan(s, fc, assess_risk(s, fc))


def stations_served(recs):
    return {r.station_id for r in recs}


@pytest.fixture
def healthy() -> dict:
    return load("snapshot_tick24")


@pytest.fixture
def scarce() -> dict:
    return load("snapshot_tick200")  # every station empty: more need than dispatch capacity


# ---- simulator rules (guide §5.2) ----
@pytest.mark.parametrize("name", ["snapshot_tick24", "snapshot_tick200"])
def test_every_plan_is_legal(name):
    s, recs = run(load(name))
    assert recs and violations(s, recs) == []
    for r in recs:
        assert r.allocation.quantity >= MIN_QTY and r.allocation.quantity % ROUND_TO == 0
        assert r.mode == "optimizer"


def test_live_pair_plan_is_legal():
    s, recs = run(load("pair_live")["now"])  # has real PENDING/ARRIVED allocations
    assert violations(s, recs) == []


def test_dispatch_capacity_counts_allocations_already_made(scarce):
    t = scarce["tick"]
    scarce["allocations"] = [{"id": 99, "source_depot_id": "depot-gazipur", "destination_station_id": "station-mirpur",
                              "route_id": "route-gazipur-mirpur", "fuel_type": "DIESEL", "quantity": 10000,
                              "created_tick": t, "status": "PENDING", "expected_arrival_tick": None}]
    s, recs = run(scarce)
    assert sum(r.allocation.quantity for r in recs if r.allocation.source_depot_id == "depot-gazipur") <= 2000
    assert violations(s, recs) == []


def test_violations_catches_illegal_batch(healthy):
    s, recs = run(healthy)
    bad = recs[0].model_copy(deep=True)
    bad.allocation = AllocationPlan(source_depot_id="depot-patiya", route_id="route-gazipur-tongi", quantity=99999, eta_tick=0)
    errs = " ".join(violations(s, [bad]))
    assert "ROUTE_MISMATCH" in errs and "ROUTE_CAPACITY_EXCEEDED" in errs


# ---- quality ----
def test_healthy_network_one_targeted_rec(healthy):
    _, recs = run(healthy)
    [r] = recs
    assert (r.station_id, r.fuel_type) == ("station-tongi", "DIESEL")
    assert r.expected_impact.stockout_prob_before > 0.9 and r.expected_impact.stockout_prob_after < 0.05
    assert r.expected_impact.unmet_liters_avoided > 0
    assert r.confidence >= 0.8 and not r.requires_human_review


def test_scarcity_is_shared_fairly(scarce):
    _, recs = run(scarce)
    assert stations_served(recs) == {st["id"] for st in scarce["stations"]}   # nobody left out
    per_depot: dict[str, float] = {}
    for r in recs:
        per_depot[r.allocation.source_depot_id] = per_depot.get(r.allocation.source_depot_id, 0) + r.allocation.quantity
    caps = {d["id"]: d["dispatch_capacity_per_tick"] for d in scarce["depots"]}
    assert all(per_depot[d] >= 0.9 * caps[d] for d in caps)                     # capacity is actually used
    assert all(r.expected_impact.unmet_liters_avoided > 0 for r in recs)


def test_no_plan_when_everything_is_fine(healthy):
    for st in healthy["stations"]:
        st["inventory"] = {f: st["capacity"][f] * 0.95 for f in st["capacity"]}
    assert run(healthy)[1] == []


# ---- disruptions ----
def test_disrupted_route_uses_backup_depot(healthy):
    for st in healthy["stations"]:
        if st["id"] == "station-mirpur":
            st["inventory"]["DIESEL"] = 500
    next(r for r in healthy["routes"] if r["id"] == "route-gazipur-mirpur")["status"] = "DISRUPTED"
    s, recs = run(healthy)
    [r] = [x for x in recs if x.station_id == "station-mirpur"]
    assert r.allocation.route_id == "route-patiya-mirpur"
    assert any("unavailable" in sig for sig in r.signals)
    assert violations(s, recs) == []


def test_closed_depot_never_used_constrained_depot_allowed(scarce):
    scarce["depots"][0]["status"] = "CLOSED"       # gazipur
    scarce["depots"][1]["status"] = "CONSTRAINED"  # patiya still ships
    s, recs = run(scarce)
    assert recs and all(r.allocation.source_depot_id == "depot-patiya" for r in recs)
    assert violations(s, recs) == []


def test_station_outage_gets_nothing(scarce):
    scarce["stations"][0]["status"] = "OUTAGE"
    _, recs = run(scarce)
    assert scarce["stations"][0]["id"] not in stations_served(recs)


def test_depot_low_stock_is_respected(scarce):
    for d in scarce["depots"]:
        d["inventory"]["OCTANE"] = 800
    s, recs = run(scarce)
    for dep in ("depot-gazipur", "depot-patiya"):
        assert sum(r.allocation.quantity for r in recs if r.fuel_type == "OCTANE" and r.allocation.source_depot_id == dep) <= 800
    assert violations(s, recs) == []


def test_alternatives_are_other_legal_routes(healthy):
    for st in healthy["stations"]:
        if st["id"] == "station-mirpur":
            st["inventory"]["PETROL"] = 400
    s, recs = run(healthy)
    mine = [x for x in recs if (x.station_id, x.fuel_type) == ("station-mirpur", "PETROL")]
    main = next(x for x in mine if x.allocation.route_id == "route-gazipur-mirpur")  # fastest route first
    assert [a.route_id for a in main.alternatives] == ["route-patiya-mirpur"]
    # need is bigger than one route's max, so the second route may carry the rest
    assert sum(x.allocation.quantity for x in mine) > 7000 and violations(s, recs) == []


# ---- fallbacks ----
def test_optimizer_failure_falls_back_to_heuristic(scarce, monkeypatch):
    monkeypatch.setattr(planner, "_solve_lp", lambda *a: (_ for _ in ()).throw(RuntimeError("solver down")))
    s, recs = run(scarce)
    assert recs and {r.mode for r in recs} == {"heuristic"} and violations(s, recs) == []


def test_fallback_plan_without_forecaster(scarce, monkeypatch):
    import sys
    monkeypatch.setattr(sys.modules["app.intel.forecast"], "forecast", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("forecast broken")))
    s = Snapshot(**scarce)
    recs = fallback_plan(s)
    assert recs and violations(s, recs) == []
    assert all(r.mode == "fallback" and r.requires_human_review for r in recs)


# ---- what-if ----
def test_simulate(healthy):
    s = Snapshot(**healthy)
    w = simulate(s, forecast(s), "station-tongi", "DIESEL", "depot-gazipur", "route-gazipur-tongi", 5000)
    assert w.stockout_prob_after < w.stockout_prob_before
    assert len(w.projection_with) == 16 and w.projection_with[-1].inventory > w.projection_without[-1].inventory
    with pytest.raises(ValueError):
        simulate(s, forecast(s), "station-tongi", "DIESEL", "depot-patiya", "route-gazipur-tongi", 5000)
