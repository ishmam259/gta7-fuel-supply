"""Scenario presets, decision replay/export, and the with-vs-without benchmark."""
import asyncio
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import col, select

from .. import benchmark, scenarios
from ..db import Alert, Decision, MetricPoint, Recommendation, session
from ..engine import get_engine
from ..security import require_operator

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- scenario configuration
@router.get("/scenarios")
def list_scenarios():
    return {"scenarios": [{"name": k, "title": v["title"], "description": v["description"], "events": v["events"]}
                          for k, v in scenarios.SCENARIOS.items()],
            "faults": [{"name": k, "title": v["title"], "body": v["body"]} for k, v in scenarios.FAULTS.items()]}


@router.post("/scenarios/{name}/run", dependencies=[Depends(require_operator)])
async def run_scenario(name: str):
    if name not in scenarios.SCENARIOS:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": f"unknown scenario {name}"})
    eng = get_engine()
    tick = eng.last_tick or 0
    created = []
    for body in scenarios.events_for(name, tick):
        code, out = await eng.sim.admin("POST", "/admin/events", json=body)
        if code >= 400:
            raise HTTPException(code, detail={"code": "SIMULATOR_ADMIN_ERROR", "message": str(out)[:300]})
        created.append(out)
    return {"scenario": name, "anchored_at_tick": tick, "events": created}


@router.post("/faults/presets/{name}", dependencies=[Depends(require_operator)])
async def run_fault(name: str):
    if name not in scenarios.FAULTS:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": f"unknown fault preset {name}"})
    code, out = await get_engine().sim.admin("POST", "/admin/faults", json=scenarios.FAULTS[name]["body"])
    if code >= 400:
        raise HTTPException(code, detail={"code": "SIMULATOR_ADMIN_ERROR", "message": str(out)[:300]})
    return {"fault": name, "result": out}


# ---------------------------------------------------------------- decision audit export & replay
def _decision_rows(limit: int) -> list[dict]:
    with session() as s:
        decisions = s.exec(select(Decision).order_by(col(Decision.id).desc()).limit(limit)).all()
        recs = {r.id: r for r in s.exec(select(Recommendation).where(
            col(Recommendation.id).in_([d.recommendation_id for d in decisions if d.recommendation_id]))).all()}
    rows = []
    for d in decisions:
        r = recs.get(d.recommendation_id)
        a = (r.body.get("allocation") or {}) if r else {}
        imp = (r.body.get("expected_impact") or {}) if r else {}
        rows.append({"decision_id": d.id, "tick": d.tick, "created_at": d.created_at.isoformat(),
                     "actor": d.actor, "action": d.action, "result": d.result, "note": d.note or "",
                     "recommendation_id": d.recommendation_id, "station_id": r.station_id if r else "",
                     "fuel_type": r.fuel_type if r else "", "source_depot_id": a.get("source_depot_id", ""),
                     "route_id": a.get("route_id", ""), "quantity": a.get("quantity", ""),
                     "mode": r.mode if r else "", "confidence": r.confidence if r else "",
                     "risk_before": imp.get("stockout_prob_before", ""), "risk_after": imp.get("stockout_prob_after", ""),
                     "sim_allocation_id": r.sim_allocation_id if r else "",
                     "failure_reason": (r.failure_reason or "") if r else ""})
    return rows


@router.get("/decisions/export")
def export_decisions(format: str = Query("csv", pattern="^(csv|json)$"), limit: int = Query(5000, ge=1, le=50000)):
    rows = _decision_rows(limit)
    if format == "json":
        return rows
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=gta7_decision_audit.csv"})


@router.get("/replay")
def replay(from_tick: int = Query(0, ge=0), to_tick: int | None = Query(None, ge=0)):
    """Tick-by-tick timeline of what the platform saw and did (simulation replay)."""
    hi = to_tick if to_tick is not None else 10**9
    with session() as s:
        metrics = s.exec(select(MetricPoint).where(MetricPoint.tick >= from_tick, MetricPoint.tick <= hi)
                         .order_by(MetricPoint.id)).all()
        alerts = s.exec(select(Alert).where(Alert.tick >= from_tick, Alert.tick <= hi).order_by(Alert.id)).all()
        recs = s.exec(select(Recommendation).where(Recommendation.tick >= from_tick, Recommendation.tick <= hi)
                      .order_by(Recommendation.id)).all()
        decs = s.exec(select(Decision).where(Decision.tick >= from_tick, Decision.tick <= hi)
                      .order_by(Decision.id)).all()
    timeline: dict[int, dict] = {}

    def at(t: int) -> dict:
        return timeline.setdefault(t, {"tick": t, "metrics": None, "alerts": [], "recommendations": [], "decisions": []})

    for m in metrics:
        at(m.tick)["metrics"] = {"service_level": m.service_level, "unmet_demand_liters": m.unmet_demand_liters,
                                 "allocation_liters": m.allocation_liters, "open_alerts": m.open_alerts}
    for a in alerts:
        at(a.tick)["alerts"].append({"id": a.id, "severity": a.severity, "kind": a.kind, "title": a.title,
                                     "status": a.status})
    for r in recs:
        at(r.tick)["recommendations"].append({"id": r.id, "station_id": r.station_id, "fuel_type": r.fuel_type,
                                              "quantity": (r.body.get("allocation") or {}).get("quantity"),
                                              "status": r.status, "confidence": r.confidence})
    for d in decs:
        at(d.tick)["decisions"].append({"id": d.id, "actor": d.actor, "action": d.action,
                                        "recommendation_id": d.recommendation_id, "result": d.result})
    return [timeline[t] for t in sorted(timeline)]


# ---------------------------------------------------------------- with vs without benchmark
class BenchmarkBody(BaseModel):
    scenario: str | None = "combined_crisis"
    ticks: int = Field(default=96, ge=8, le=400)


@router.post("/benchmark", dependencies=[Depends(require_operator)])
async def start_benchmark(body: BenchmarkBody):
    if benchmark.STATE["status"] == "running":
        raise HTTPException(409, detail={"code": "BENCHMARK_RUNNING", "message": "a benchmark is already running"})
    if body.scenario and body.scenario not in scenarios.SCENARIOS:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": f"unknown scenario {body.scenario}"})
    eng = get_engine()
    eng.mode = {**eng.mode, "mode": "manual"}  # the live engine must not act while the benchmark drives the sim
    asyncio.create_task(benchmark.run_in_background(body.scenario, body.ticks))
    return {"status": "started", "scenario": body.scenario, "ticks": body.ticks,
            "note": "resets the simulator; poll GET /api/benchmark"}


@router.get("/benchmark")
def get_benchmark():
    return benchmark.latest()
