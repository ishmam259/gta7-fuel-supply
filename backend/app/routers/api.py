"""Public API for the operator console. See docs/API_CONTRACT.md."""
import asyncio
import json
import time
from typing import Literal

import psutil
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import col, select

from .. import intel_bridge
from ..db import Alert, Decision, MetricPoint, Recommendation, db_healthy, session
from ..engine import get_engine
from ..metrics import FALLBACK_ACTIVATIONS, REQUEST_WINDOW
from ..security import require_operator

router = APIRouter(prefix="/api")

FUEL = Literal["DIESEL", "PETROL", "OCTANE"]


def _not_found(what: str):
    raise HTTPException(404, detail={"code": "NOT_FOUND", "message": f"{what} not found"})


def _need_snapshot():
    eng = get_engine()
    if eng.snap is None:
        raise HTTPException(503, detail={"code": "NO_STATE_YET", "message": "No simulator state synced yet"})
    return eng


# ---------------------------------------------------------------- health & state
@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/state")
def state():
    return get_engine().state_view()


@router.get("/forecast")
def forecast(station_id: str | None = None, fuel_type: FUEL | None = None):
    out = [f for f in get_engine().forecasts if isinstance(f, dict)]
    if station_id:
        out = [f for f in out if f.get("station_id") == station_id]
    if fuel_type:
        out = [f for f in out if f.get("fuel_type") == fuel_type]
    return out


@router.get("/metrics/history")
def metrics_history(limit: int = Query(500, ge=1, le=5000)):
    with session() as s:
        rows = s.exec(select(MetricPoint).order_by(col(MetricPoint.id).desc()).limit(limit)).all()
    return [{"tick": r.tick, "service_level": r.service_level, "unmet_demand_liters": r.unmet_demand_liters,
             "allocation_liters": r.allocation_liters, "open_alerts": r.open_alerts} for r in reversed(rows)]


# ---------------------------------------------------------------- alerts
def _alerts(status: str, limit: int) -> list[dict]:
    with session() as s:
        q = select(Alert).order_by(col(Alert.id).desc()).limit(limit)
        if status == "open":
            q = q.where(Alert.status == "open")
        return [get_engine().alert_view(a) for a in s.exec(q).all()]


@router.get("/alerts")
def alerts(status: Literal["open", "all"] = "open", limit: int = Query(100, ge=1, le=1000)):
    return _alerts(status, limit)


@router.get("/incidents/{alert_id}/explain")
def explain_incident(alert_id: int):
    eng = _need_snapshot()
    with session() as s:
        a = s.get(Alert, alert_id)
        if a is None:
            _not_found("alert")
        return intel_bridge.explain_incident(eng.alert_view(a), eng.snap)


# ---------------------------------------------------------------- recommendations
def _recs(status: str, limit: int) -> list[dict]:
    with session() as s:
        q = select(Recommendation).order_by(col(Recommendation.id).desc()).limit(limit)
        if status != "all":
            q = q.where(Recommendation.status == status)
        return [get_engine().rec_view(r) for r in s.exec(q).all()]


@router.get("/recommendations")
def recommendations(status: str = "pending", limit: int = Query(100, ge=1, le=1000)):
    return _recs(status, limit)


class SimulateBody(BaseModel):
    station_id: str
    fuel_type: FUEL
    source_depot_id: str
    route_id: str
    quantity: float = Field(gt=0, le=100000)


@router.post("/recommendations/simulate")
def simulate(body: SimulateBody):
    eng = _need_snapshot()
    snap = eng.snap
    route = next((r for r in snap["routes"] if r["id"] == body.route_id), None)
    if (route is None or route["destination_station_id"] != body.station_id
            or route["source_depot_id"] != body.source_depot_id):
        raise HTTPException(422, detail={"code": "ROUTE_MISMATCH", "message": "route does not connect depot and station"})
    return intel_bridge.simulate(snap, body.model_dump())


@router.get("/recommendations/{rec_id}")
def recommendation(rec_id: int, explain: bool = True):
    eng = get_engine()
    with session() as s:
        r = s.get(Recommendation, rec_id)
        if r is None:
            _not_found("recommendation")
        if explain and eng.snap and r.body.get("explanation_source") != "llm":
            text, source = intel_bridge.explain_recommendation(eng.rec_view(r), eng.snap)
            if source == "llm" and text:
                r.body = {**r.body, "explanation": text, "explanation_source": "llm"}
                s.add(r)
                s.commit()
                s.refresh(r)
        return eng.rec_view(r)


class ApproveBody(BaseModel):
    quantity: float | None = Field(default=None, gt=0, le=100000)
    note: str | None = Field(default=None, max_length=500)


@router.post("/recommendations/{rec_id}/approve", dependencies=[Depends(require_operator)])
async def approve(rec_id: int, body: ApproveBody | None = None):
    body = body or ApproveBody()
    try:
        rec = await get_engine().execute(rec_id, actor="operator", quantity=body.quantity, note=body.note)
    except KeyError:
        _not_found("recommendation")
    return get_engine().rec_view(rec)


class RejectBody(BaseModel):
    note: str | None = Field(default=None, max_length=500)


@router.post("/recommendations/{rec_id}/reject", dependencies=[Depends(require_operator)])
def reject(rec_id: int, body: RejectBody | None = None):
    try:
        rec = get_engine().reject(rec_id, (body or RejectBody()).note)
    except KeyError:
        _not_found("recommendation")
    return get_engine().rec_view(rec)


@router.get("/decisions")
def decisions(limit: int = Query(100, ge=1, le=1000)):
    with session() as s:
        rows = s.exec(select(Decision).order_by(col(Decision.id).desc()).limit(limit)).all()
        return [r.model_dump() for r in rows]


# ---------------------------------------------------------------- decision mode
class ModeBody(BaseModel):
    mode: Literal["manual", "assisted"]
    auto_confidence_threshold: float = Field(default=0.8, ge=0, le=1)
    auto_max_quantity: float = Field(default=5000, gt=0, le=20000)


@router.get("/mode")
def get_mode():
    return get_engine().mode


@router.post("/mode", dependencies=[Depends(require_operator)])
def set_mode(body: ModeBody):
    eng = get_engine()
    eng.mode = body.model_dump()
    eng._last_shared = 0.0
    eng.save_shared()
    return eng.mode


# ---------------------------------------------------------------- AI assistant
@router.get("/briefing")
def briefing():
    eng = _need_snapshot()
    return intel_bridge.briefing(eng.snap, eng.risks, _alerts("open", 50))


class AskBody(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@router.post("/assistant")
def assistant(body: AskBody):
    eng = _need_snapshot()
    return intel_bridge.answer(body.question, eng.snap, _alerts("open", 50), _recs("pending", 20))


# ---------------------------------------------------------------- system status
def _counter_total(counter) -> float:
    return sum(s.value for m in counter.collect() for s in m.samples if s.name.endswith("_total"))


_HEALTH_CACHE = {"at": 0.0, "ok": True}


async def _cached_sim_health(eng) -> bool:
    """Probe the simulator at most every 2 s, so heavy traffic on this endpoint doesn't hit the simulator."""
    now = time.monotonic()
    if now - _HEALTH_CACHE["at"] > 2.0:
        _HEALTH_CACHE.update(at=now, ok=await eng.sim.health())
    return _HEALTH_CACHE["ok"]


@router.get("/system/status")
async def system_status():
    eng = get_engine()
    sim_ok = await _cached_sim_health(eng)
    llm = intel_bridge.llm_status()
    if not sim_ok:
        simulator = "down"
    elif eng.degraded or eng.sim.stale or eng.sim.breaker.state != "closed":
        simulator = "degraded"
    else:
        simulator = "healthy"
    comps = {
        "backend_api": "healthy",
        "database": "healthy" if db_healthy() else "down",
        "simulator": simulator,
        "prediction_service": intel_bridge.STATUS.prediction,
        "decision_engine": intel_bridge.STATUS.decision,
        "llm": intel_bridge.STATUS.llm,
    }
    if comps["database"] == "down":
        overall = "down"
    elif any(v != "healthy" for k, v in comps.items() if k != "llm"):
        overall = "degraded"
    else:
        overall = "healthy"
    proc = psutil.Process()
    return {"overall": overall, "components": comps, "circuit_breaker": eng.sim.breaker.state,
            "sse": "connected" if eng.sse_connected else "reconnecting",
            **REQUEST_WINDOW.stats(), "fallback_activations": _counter_total(FALLBACK_ACTIVATIONS),
            "llm_detail": llm, "last_error": eng.sim.last_error, "tick": eng.last_tick,
            "cpu_percent": proc.cpu_percent(interval=None), "memory_mb": round(proc.memory_info().rss / 1e6, 1),
            "uptime_s": int(time.time() - eng.started_at)}


# ---------------------------------------------------------------- simulation control & chaos (operator only)
async def _admin(method: str, path: str, body: dict | None = None):
    code, out = await get_engine().sim.admin(method, path, json=body)
    if code >= 400:
        raise HTTPException(code, detail={"code": "SIMULATOR_ADMIN_ERROR", "message": str(out)[:300]})
    return out


@router.post("/sim/{action}", dependencies=[Depends(require_operator)])
async def sim_control(action: Literal["run", "pause", "step", "reset", "toggle"], request: Request):
    eng = get_engine()
    n = 1
    if action == "step":
        try:
            n = int((await request.json()).get("n", 1))
        except Exception:
            n = 1
        n = max(1, min(n, 200))
    out = None
    for _ in range(n):
        out = await _admin("POST", f"/admin/{action}")
    await eng.sync()
    return {"tick": eng.last_tick, "status": (eng.snap or {}).get("status"), "simulator": out}


@router.post("/chaos/event", dependencies=[Depends(require_operator)])
async def chaos_event(body: dict):
    return await _admin("POST", "/admin/events", body)


@router.post("/chaos/fault", dependencies=[Depends(require_operator)])
async def chaos_fault(body: dict):
    return await _admin("POST", "/admin/faults", body)


@router.post("/chaos/fault/clear", dependencies=[Depends(require_operator)])
async def chaos_fault_clear():
    return await _admin("POST", "/admin/faults/clear")


@router.get("/chaos/events")
async def chaos_events():
    return await _admin("GET", "/admin/events")


@router.get("/chaos/faults")
async def chaos_faults():
    return await _admin("GET", "/admin/faults")


# ---------------------------------------------------------------- live stream
@router.get("/stream")
async def stream(request: Request):
    eng = get_engine()
    q = eng.subscribe()

    async def gen():
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event, data = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            eng.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
