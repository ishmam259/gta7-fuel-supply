import json
from pathlib import Path

import pytest

from app import intel
from app.intel.models import Snapshot

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_tick24.json"


@pytest.fixture
def snap() -> Snapshot:
    return Snapshot(**json.loads(FIXTURE.read_text()))


def test_forecast_covers_every_station_fuel(snap):
    fc = intel.forecast(snap)
    assert len(fc) == len(snap.stations) * 3
    assert all(len(f.per_tick) == 16 and min(f.per_tick) >= 0 for f in fc)


def test_risk_levels_valid(snap):
    risks = intel.assess_risk(snap, intel.forecast(snap))
    assert {r.level for r in risks} <= {"ok", "watch", "critical", "outage"}
    assert all(0 <= r.stockout_prob <= 1 for r in risks)


def test_plan_respects_limits_under_pressure(snap):
    for st in snap.stations:
        st["inventory"]["OCTANE"] = 200.0
    fc = intel.forecast(snap)
    recs = intel.plan(snap, fc, intel.assess_risk(snap, fc))
    assert recs
    routes = {r["id"]: r for r in snap.routes}
    for rec in recs:
        route = routes[rec.allocation.route_id]
        assert route["destination_station_id"] == rec.station_id
        assert rec.allocation.quantity <= route["max_shipment"]
        assert rec.expected_impact.stockout_prob_after <= rec.expected_impact.stockout_prob_before
    used: dict[str, float] = {}
    for rec in recs:
        used[rec.allocation.source_depot_id] = used.get(rec.allocation.source_depot_id, 0) + rec.allocation.quantity
    caps = {d["id"]: d["dispatch_capacity_per_tick"] for d in snap.depots}
    assert all(q <= caps[d] for d, q in used.items())


def test_fallback_and_simulate_and_genai(snap):
    assert isinstance(intel.fallback_plan(snap), list)
    fc = intel.forecast(snap)
    w = intel.simulate(snap, fc, "station-mirpur", "DIESEL", "depot-gazipur", "route-gazipur-mirpur", 5000)
    assert w.stockout_prob_after <= w.stockout_prob_before
    b = intel.briefing(snap, intel.assess_risk(snap, fc), intel.detect(snap, fc, None))
    assert b["source"] == "template"
