"""End to end through the backend's intel_bridge: the exact path production uses (dict snapshots in, dicts out)."""
import copy
import json
from pathlib import Path

import pytest

from app import intel_bridge as bridge
from app.intel import genai
from app.intel.models import RecommendationDraft, Snapshot
from app.intel.planner import violations

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setattr(genai, "_cfg", lambda: {k: "" for k in genai.FIELDS})
    genai._cache.clear()


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


def crisis(raw: dict) -> dict:
    """Combined crisis on the healthy network: Dhaka demand spike, Gazipur-Mirpur route down,
    delayed Gazipur supply, Patiya constrained, Mirpur petrol nearly empty."""
    raw = copy.deepcopy(raw)
    for st in raw["stations"]:
        if st["region_id"] == "region-dhaka":
            st["demand_multiplier"] = 1.8
    next(st for st in raw["stations"] if st["id"] == "station-mirpur")["inventory"]["PETROL"] = 900
    next(r for r in raw["routes"] if r["id"] == "route-gazipur-mirpur")["status"] = "DISRUPTED"
    next(d for d in raw["depots"] if d["id"] == "depot-patiya")["status"] = "CONSTRAINED"
    sup = next(a for a in raw["supply_arrivals"] if a["depot_id"] == "depot-gazipur" and a["status"] == "SCHEDULED")
    sup["status"], sup["planned_tick"] = "DELAYED", sup["planned_tick"] + 8
    raw["events"] = [
        {"id": 3, "type": "demand_spike", "start_tick": 20, "end_tick": 40, "status": "ACTIVE",
         "parameters": {"region_ids": ["region-dhaka"], "multiplier": 1.8}},
        {"id": 4, "type": "route_disruption", "start_tick": 22, "end_tick": 34, "status": "ACTIVE",
         "parameters": {"route_ids": ["route-gazipur-mirpur"]}},
    ]
    raw["metrics"] = {"service_level": 0.97, "unmet_demand_liters": 820}
    return raw


def legal(snap: dict, recs: list[dict]) -> list[str]:
    return violations(Snapshot(**snap), [RecommendationDraft(**r) for r in recs])


def test_healthy_pipeline_uses_intel_not_fallback():
    snap = load("snapshot_tick24")
    out = bridge.run_pipeline(snap, None)
    assert out["fallback_used"] is False and bridge.STATUS.prediction == "healthy"
    assert out["mape"] is not None and out["mape"] < 0.2
    assert out["risks"]["station-tongi"]["DIESEL"]["level"] == "watch"
    assert out["recommendations"] and {r["mode"] for r in out["recommendations"]} == {"optimizer"}
    assert all(0 <= v["stockout_prob"] <= 1 for fm in out["risks"].values() for v in fm.values())
    assert legal(snap, out["recommendations"]) == []


def test_combined_crisis_end_to_end():
    snap = crisis(load("snapshot_tick24"))
    out = bridge.run_pipeline(snap, None)
    kinds = {(a["kind"], a["entity"]["type"]) for a in out["alerts"]}
    assert {("shortage_risk", "station"), ("anomalous_demand", "station"), ("disruption", "route"),
            ("disruption", "supply"), ("bottleneck", "depot"), ("disruption", "system")} <= kinds
    assert legal(snap, out["recommendations"]) == []
    mirpur = next(r for r in out["recommendations"] if (r["station_id"], r["fuel_type"]) == ("station-mirpur", "PETROL"))
    assert mirpur["allocation"]["route_id"] == "route-patiya-mirpur"               # backup depot
    assert mirpur["expected_impact"]["stockout_prob_after"] < mirpur["expected_impact"]["stockout_prob_before"]
    text = " ".join(mirpur["signals"])
    assert "demand 1.8x" in text and "unavailable" in text and "constrained" in text
    # genai through the bridge, with the dicts the API layer passes
    rec = {"id": 1, "status": "pending", **mirpur}
    expl, src = bridge.explain_recommendation(rec, snap)
    assert src == "template" and "Mirpur" in expl
    alert = {"id": 7, "status": "open", **next(a for a in out["alerts"] if a["entity"]["type"] == "route")}
    assert bridge.explain_incident(alert, snap)["source"] == "template"
    alerts = [{"id": i, **a} for i, a in enumerate(out["alerts"])]
    b = bridge.briefing(snap, out["risks"], alerts)
    assert b["source"] == "template" and "service level 97%" in b["summary"]
    ans = bridge.answer("why is mirpur petrol at risk?", snap, alerts, [rec])
    assert ans["evidence"] and all(e.startswith("alert:") for e in ans["evidence"])


def test_pipeline_with_previous_snapshot_live_pair():
    pair = load("pair_live")
    out = bridge.run_pipeline(pair["now"], pair["prev"])
    assert out["fallback_used"] is False
    assert not [a for a in out["alerts"] if a["kind"] == "inventory_anomaly"]     # real data: no false alarm
    assert legal(pair["now"], out["recommendations"]) == []


def test_what_if_through_bridge():
    snap = load("snapshot_tick24")
    body = {"station_id": "station-tongi", "fuel_type": "DIESEL", "source_depot_id": "depot-gazipur",
            "route_id": "route-gazipur-tongi", "quantity": 5000}
    w = bridge.simulate(snap, body)
    assert "source" not in w and w["stockout_prob_after"] < w["stockout_prob_before"]
    # mismatched route: intel raises, bridge falls back instead of crashing
    w = bridge.simulate(snap, {**body, "source_depot_id": "depot-patiya"})
    assert w["source"] == "fallback"


def test_deterministic():
    snap = crisis(load("snapshot_tick24"))
    a, b = bridge.run_pipeline(snap, None), bridge.run_pipeline(copy.deepcopy(snap), None)
    assert a["recommendations"] == b["recommendations"] and a["alerts"] == b["alerts"]


def test_messy_simulator_data_does_not_crash():
    snap = load("snapshot_tick24")
    snap["routes"].append({"id": "route-ghost", "status": "AVAILABLE"})     # missing fields
    snap["allocations"].append({"id": 5, "status": "IN_TRANSIT"})           # half an allocation
    snap["demand_history"][0]["demand_liters"] = None
    assert Snapshot(**snap).dropped_rows == 3                                # the 3 broken rows are removed
    out = bridge.run_pipeline(snap, None)
    assert out["fallback_used"] is False and legal(snap, out["recommendations"]) == []  # intel itself copes
