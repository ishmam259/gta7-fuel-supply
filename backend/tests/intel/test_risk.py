import json
from pathlib import Path

import pytest

from app.intel.forecast import forecast
from app.intel.models import Snapshot
from app.intel.risk import assess_risk

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_tick200.json"
KEY = ("station-mirpur", "DIESEL")


@pytest.fixture
def raw() -> dict:
    return json.loads(FIXTURE.read_text())


def _risk(raw: dict, key=KEY):
    s = Snapshot(**raw)
    return next(r for r in assess_risk(s, forecast(s)) if (r.station_id, r.fuel_type) == key)


def _set_inv(raw: dict, liters: float, key=KEY):
    next(st for st in raw["stations"] if st["id"] == key[0])["inventory"][key[1]] = liters


def test_levels_follow_inventory(raw):
    _set_inv(raw, 0)
    assert _risk(raw).level == "outage" and _risk(raw).stockout_hours == 0
    _set_inv(raw, 150)            # ~2-3 ticks of night demand
    r = _risk(raw)
    assert r.level == "critical" and r.stockout_hours < 4 and r.stockout_prob > 0.9
    _set_inv(raw, 14000)          # nearly full tank
    r = _risk(raw)
    assert r.level == "ok" and r.stockout_prob < 0.01 and r.stockout_hours > 24


def test_prob_monotonic_in_inventory(raw):
    probs = []
    for inv in (100, 300, 600, 900, 2000):
        _set_inv(raw, inv)
        probs.append(_risk(raw).stockout_prob)
    assert probs == sorted(probs, reverse=True)


def test_station_outage_status(raw):
    _set_inv(raw, 10000)
    next(st for st in raw["stations"] if st["id"] == KEY[0])["status"] = "OUTAGE"
    assert _risk(raw).level == "outage"


@pytest.mark.parametrize("status,eta", [("IN_TRANSIT", 202), ("PENDING", None)])
def test_incoming_shipment_lowers_risk(raw, status, eta):
    _set_inv(raw, 150)
    before = _risk(raw)
    raw["allocations"] = [{
        "id": 1, "source_depot_id": "depot-gazipur", "destination_station_id": KEY[0],
        "route_id": "route-gazipur-mirpur", "fuel_type": "DIESEL", "quantity": 5000,
        "created_tick": 200, "expected_arrival_tick": eta, "status": status,
    }]
    after = _risk(raw)
    assert after.next_supply_eta_tick == (eta or 203)  # pending: created 200 + depart 1 + transit 2
    assert after.incoming_liters == 5000
    assert after.stockout_prob < before.stockout_prob
    assert after.stockout_hours > before.stockout_hours


def test_arrived_or_failed_shipments_ignored(raw):
    _set_inv(raw, 150)
    raw["allocations"] = [{"id": 1, "destination_station_id": KEY[0], "route_id": "route-gazipur-mirpur",
                           "fuel_type": "DIESEL", "quantity": 5000, "status": s} for s in ("ARRIVED", "FAILED")]
    assert _risk(raw).incoming_liters == 0


def test_depot_supply_eta_includes_delayed(raw):
    for a in raw["supply_arrivals"]:
        if a["status"] != "ARRIVED":
            a["status"] = "ARRIVED"
    raw["supply_arrivals"].append({"id": "supply-x", "depot_id": "depot-gazipur", "fuel_type": "DIESEL",
                                   "quantity": 12000, "planned_tick": 206, "status": "DELAYED"})
    r = _risk(raw)
    assert r.depot_supply_eta_tick == 206 and r.depot_supply_delayed
    # overdue delayed supply is expected next tick, never in the past
    raw["supply_arrivals"][-1]["planned_tick"] = 190
    assert _risk(raw).depot_supply_eta_tick == 201
