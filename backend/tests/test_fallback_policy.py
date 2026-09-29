"""Rule-based fallback policy must always respect simulator limits (guide §5.2)."""
import json
from pathlib import Path

from app import fallback_policy as fb

FIX = Path(__file__).parent / "intel" / "fixtures"


def load(name="snapshot_tick200.json") -> dict:
    return json.loads((FIX / name).read_text())


def test_assess_covers_every_station_fuel():
    snap = load()
    risks = fb.assess(snap)
    assert set(risks) == {s["id"] for s in snap["stations"]}
    for per_fuel in risks.values():
        assert set(per_fuel) == set(fb.FUELS)
        for r in per_fuel.values():
            assert r["level"] in {"ok", "watch", "critical", "outage"}
            assert 0 <= r["stockout_prob"] <= 1


def test_plan_respects_all_simulator_limits():
    snap = load()
    # force shortages so the policy has work to do
    for st in snap["stations"]:
        st["inventory"] = {f: 0.1 * st["capacity"][f] for f in fb.FUELS}
    recs = fb.plan(snap, fb.assess(snap))
    assert recs, "expected recommendations for empty stations"
    routes = {r["id"]: r for r in snap["routes"]}
    depots = {d["id"]: d for d in snap["depots"]}
    used_dispatch: dict[str, float] = {}
    used_inv: dict[tuple[str, str], float] = {}
    for rec in recs:
        a = rec["allocation"]
        r = routes[a["route_id"]]
        st = next(s for s in snap["stations"] if s["id"] == rec["station_id"])
        assert r["destination_station_id"] == rec["station_id"]
        assert r["source_depot_id"] == a["source_depot_id"]
        assert r["status"] == "AVAILABLE"
        assert 0 < a["quantity"] <= r["max_shipment"]
        assert st["inventory"][rec["fuel_type"]] + a["quantity"] <= st["capacity"][rec["fuel_type"]]
        used_dispatch[a["source_depot_id"]] = used_dispatch.get(a["source_depot_id"], 0) + a["quantity"]
        key = (a["source_depot_id"], rec["fuel_type"])
        used_inv[key] = used_inv.get(key, 0) + a["quantity"]
        assert rec["mode"] == "fallback" and rec["requires_human_review"] is True
    for d, used in used_dispatch.items():
        assert used <= depots[d]["dispatch_capacity_per_tick"]
    for (d, f), used in used_inv.items():
        assert used <= depots[d]["inventory"][f]


def test_plan_skips_outage_stations_and_disrupted_routes():
    snap = load()
    for st in snap["stations"]:
        st["inventory"] = {f: 0.0 for f in fb.FUELS}
    snap["stations"][0]["status"] = "OUTAGE"
    for r in snap["routes"]:
        r["status"] = "DISRUPTED"
    recs = fb.plan(snap, fb.assess(snap))
    assert recs == []


def test_detect_flags_disruptions():
    snap = load()
    snap["routes"][0]["status"] = "DISRUPTED"
    snap["depots"][0]["status"] = "CONSTRAINED"
    kinds = {a["kind"] for a in fb.detect(snap, fb.assess(snap))}
    assert {"disruption", "bottleneck"} <= kinds


def test_missing_demand_values_do_not_crash():
    snap = load()
    snap["demand_history"] = [{"station_id": "station-mirpur", "fuel_type": "DIESEL", "tick": 1, "demand_liters": None},
                              {"station_id": "station-mirpur", "fuel_type": "DIESEL", "tick": 2}] + snap["demand_history"][:5]
    rates = fb.demand_rate(snap)
    assert all(v >= 0 for v in rates.values())
    assert fb.plan(snap, fb.assess(snap)) is not None
