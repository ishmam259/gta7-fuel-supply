"""API + executor tests with a fake simulator (no network). Covers operator-key protection,
the approve/reject flow, idempotency keys, and mapping of simulator error codes."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIX = Path(__file__).parent / "intel" / "fixtures" / "snapshot_tick200.json"


class FakeSim:
    """Stands in for SimClient inside the engine."""

    def __init__(self):
        self.posted: list[dict] = []
        self.next_response = (201, None)
        self.stale = False
        self.last_error = None

        class B:
            state = "closed"
        self.breaker = B()

    async def post_allocation(self, body):
        self.posted.append(body)
        code, resp = self.next_response
        return code, resp or {"id": len(self.posted), **body, "status": "PENDING"}

    async def health(self):
        return True

    async def admin(self, method, path, json=None):
        return 200, {"ok": True}

    async def close(self):
        pass


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("OPERATOR_KEY", "test-key")
    from app import config, db, engine as engine_mod
    config.get_settings.cache_clear()
    db._engine = None

    async def no_start(self):
        return None

    monkeypatch.setattr(engine_mod.Engine, "start", no_start)
    from app.main import app
    with TestClient(app) as c:
        eng = engine_mod.engine
        eng.sim = FakeSim()
        snap = json.loads(FIX.read_text())
        snap.update(metrics={"served_demand_liters": 1, "unmet_demand_liters": 0, "service_level": 1.0,
                             "allocation_liters": 0, "allocation_failures": 0}, status="PAUSED")
        eng.snap, eng.last_tick = snap, snap["tick"]
        eng._store_recommendations(snap, [{
            "station_id": "station-mirpur", "fuel_type": "OCTANE", "mode": "heuristic", "confidence": 0.9,
            "allocation": {"source_depot_id": "depot-gazipur", "route_id": "route-gazipur-mirpur",
                           "quantity": 4000, "eta_tick": snap["tick"] + 3},
        }])
        yield c, eng
    config.get_settings.cache_clear()
    db._engine = None


def test_health_and_state(client):
    c, _ = client
    assert c.get("/api/health").json() == {"status": "ok"}
    assert c.get("/api/state").json()["instance"]["tick"] == 200


def test_approve_requires_operator_key(client):
    c, eng = client
    rid = c.get("/api/recommendations").json()[0]["id"]
    assert c.post(f"/api/recommendations/{rid}/approve").status_code == 401
    assert c.post(f"/api/recommendations/{rid}/approve", headers={"X-Operator-Key": "wrong"}).status_code == 401
    assert eng.sim.posted == []


def test_approve_executes_with_idempotency_key(client):
    c, eng = client
    rid = c.get("/api/recommendations").json()[0]["id"]
    r = c.post(f"/api/recommendations/{rid}/approve", headers={"X-Operator-Key": "test-key"}, json={"note": "ok"}).json()
    assert r["status"] == "executed" and r["sim_allocation_id"] == 1
    assert eng.sim.posted[0]["idempotency_key"] == f"gta7-rec{rid}-q4000"
    # approving again does not ship twice
    c.post(f"/api/recommendations/{rid}/approve", headers={"X-Operator-Key": "test-key"})
    assert len(eng.sim.posted) == 1
    d = c.get("/api/decisions").json()[0]
    assert d["actor"] == "operator" and d["result"] == "OK"


def test_simulator_rejection_marks_failed_with_reason(client):
    c, eng = client
    eng.sim.next_response = (409, {"detail": {"code": "ROUTE_DISRUPTED", "message": "route down"}})
    rid = c.get("/api/recommendations").json()[0]["id"]
    r = c.post(f"/api/recommendations/{rid}/approve", headers={"X-Operator-Key": "test-key"}).json()
    assert r["status"] == "failed" and r["failure_reason"].startswith("ROUTE_DISRUPTED")


def test_fault_keeps_recommendation_pending_for_retry(client):
    c, eng = client
    eng.sim.next_response = (503, {"error": {"code": "FAULT_INJECTED", "message": "down"}})
    rid = c.get("/api/recommendations").json()[0]["id"]
    r = c.post(f"/api/recommendations/{rid}/approve", headers={"X-Operator-Key": "test-key"}).json()
    assert r["status"] == "pending" and "FAULT_INJECTED" in r["failure_reason"]


def test_reject_and_input_validation(client):
    c, _ = client
    rid = c.get("/api/recommendations").json()[0]["id"]
    assert c.post(f"/api/recommendations/{rid}/reject", headers={"X-Operator-Key": "test-key"},
                  json={"note": "no"}).json()["status"] == "rejected"
    bad = c.post("/api/recommendations/simulate", json={"station_id": "station-mirpur", "fuel_type": "JETFUEL",
                                                        "source_depot_id": "x", "route_id": "y", "quantity": -5})
    assert bad.status_code == 422
    mism = c.post("/api/recommendations/simulate", json={"station_id": "station-tongi", "fuel_type": "DIESEL",
                                                         "source_depot_id": "depot-gazipur",
                                                         "route_id": "route-gazipur-mirpur", "quantity": 1000})
    assert mism.status_code == 422 and mism.json()["detail"]["code"] == "ROUTE_MISMATCH"


def test_system_status_and_metrics(client):
    c, _ = client
    s = c.get("/api/system/status").json()
    assert s["components"]["database"] == "healthy" and "p95_latency_ms" in s
    assert "gta7_" in c.get("/metrics").text


def test_distinct_alert_codes_on_same_entity_stay_separate(client):
    c, eng = client
    ent = {"type": "depot", "id": "depot-gazipur"}
    k1 = eng._raise_alert("warning", "bottleneck", ent, "Dispatch saturated", code="dispatch")
    k2 = eng._raise_alert("warning", "bottleneck", ent, "Low diesel stock", code="low_stock")
    k3 = eng._raise_alert("warning", "bottleneck", ent, "Dispatch saturated", code="dispatch")
    assert k1 != k2 and k1 == k3
    titles = [a["title"] for a in c.get("/api/alerts").json() if a["kind"] == "bottleneck"]
    assert sorted(titles) == ["Dispatch saturated", "Low diesel stock"]
    assert "llm_detail" in c.get("/api/system/status").json()


def test_same_recommendation_is_refreshed_not_duplicated(client):
    c, eng = client
    snap = eng.snap
    base = {"station_id": "station-mirpur", "fuel_type": "OCTANE", "mode": "heuristic", "confidence": 0.7,
            "allocation": {"source_depot_id": "depot-gazipur", "route_id": "route-gazipur-mirpur",
                           "quantity": 4000, "eta_tick": snap["tick"] + 3},
            "signals": ["Gazipur Depot constrained"]}
    eng._store_recommendations(snap, [base])
    recs = c.get("/api/recommendations").json()
    assert len(recs) == 1
    assert recs[0]["signals"] == ["Gazipur Depot constrained"] and recs[0]["confidence"] == 0.7


def test_approval_blocked_when_availability_changed(client):
    c, eng = client
    rid = c.get("/api/recommendations").json()[0]["id"]
    for r in eng.snap["routes"]:
        if r["id"] == "route-gazipur-mirpur":
            r["status"] = "DISRUPTED"
    r = c.post(f"/api/recommendations/{rid}/approve", headers={"X-Operator-Key": "test-key"}).json()
    assert r["status"] == "failed" and r["failure_reason"].startswith("AVAILABILITY_CHANGED")
    assert "DISRUPTED" in r["failure_reason"]
    assert eng.sim.posted == []  # nothing doomed was sent to the simulator


def test_concurrent_approvals_are_serialized(client):
    import asyncio
    c, eng = client
    rid = c.get("/api/recommendations").json()[0]["id"]

    async def both():
        return await asyncio.gather(eng.execute(rid), eng.execute(rid))

    a, b = asyncio.run(both())
    assert len(eng.sim.posted) == 1  # second approval sees the first one's result
    assert a.status == b.status == "executed"


def test_back_to_back_approvals_respect_dispatch_capacity(client):
    c, eng = client
    snap = eng.snap
    gaz = next(d for d in snap["depots"] if d["id"] == "depot-gazipur")
    gaz["dispatch_capacity_per_tick"] = 5000
    for a in snap["allocations"]:
        a["status"] = "ARRIVED"
    drafts = [{"station_id": st, "fuel_type": "DIESEL", "mode": "heuristic", "confidence": 0.9,
               "allocation": {"source_depot_id": "depot-gazipur", "route_id": rt, "quantity": 3000, "eta_tick": snap["tick"] + 2}}
              for st, rt in (("station-mirpur", "route-gazipur-mirpur"), ("station-tongi", "route-gazipur-tongi"))]
    for st in snap["stations"]:
        st["inventory"]["DIESEL"] = 0
    eng._store_recommendations(snap, drafts)
    ids = [r["id"] for r in c.get("/api/recommendations").json() if r["fuel_type"] == "DIESEL"]
    res = [c.post(f"/api/recommendations/{i}/approve", headers={"X-Operator-Key": "test-key"}).json() for i in ids]
    assert sorted(r["status"] for r in res) == ["executed", "failed"]
    blocked = next(r for r in res if r["status"] == "failed")
    assert "dispatch capacity" in blocked["failure_reason"]
    assert len(eng.sim.posted) == 1  # the second one was stopped before reaching the simulator


def test_stale_pending_recommendation_is_retired(client):
    c, eng = client
    snap = eng.snap
    rid = c.get("/api/recommendations").json()[0]["id"]
    for r in snap["routes"]:
        if r["id"] == "route-gazipur-mirpur":
            r["status"] = "DISRUPTED"
    eng._store_recommendations(snap, [])  # next tick: planner proposes nothing for that card
    assert all(r["id"] != rid for r in c.get("/api/recommendations").json())
    old = next(r for r in c.get("/api/recommendations?status=superseded").json() if r["id"] == rid)
    assert "DISRUPTED" in old["failure_reason"]
