"""Operations engine: Observe -> Detect -> Predict -> Decide -> (Simulate) -> Act -> Monitor -> Recover.

- Poll loop + SSE listener keep a validated snapshot of the simulator (REST is truth, SSE only wakes us up).
- On simulator failure: degraded mode (serve cached state, pause auto-execution), recovery when it comes back.
- Each new tick runs the intelligence pipeline, persists alerts/recommendations, and auto-executes only
  when mode == "assisted" and the recommendation is high-confidence and small (human review otherwise).
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import httpx
from sqlmodel import select

from . import intel_bridge
from .config import get_settings
from .db import Alert, Decision, MetricPoint, Recommendation, session, utcnow
from .logging_setup import log_event
from .metrics import (ALERTS_RAISED, DECISIONS, DEGRADED, DEPOT_INVENTORY, MODEL_CONFIDENCE, OPEN_ALERTS,
                      PENDING_RECS, PIPELINE_SECONDS, PREDICTION_MAPE, RECOMMENDATIONS, RECOVERIES,
                      SERVICE_LEVEL, SHORTAGE_ALERTS, SIM_TICK, SSE_CONNECTED, STATION_INVENTORY, UNMET_LITERS)
from .sim_client import InvalidSimulatorResponse, SimClient, SimulatorUnavailable

log = logging.getLogger("gta7.engine")

LIST_ENDPOINTS = {
    "regions": "/v1/regions", "depots": "/v1/depots", "stations": "/v1/stations", "routes": "/v1/routes",
    "supply_arrivals": "/v1/supply-arrivals", "events": "/v1/events", "allocations": "/v1/allocations",
}
AUTO_RESOLVE_KINDS = {"shortage_risk", "disruption", "bottleneck", "integration_failure", "stale_data"}


async def fetch_snapshot(sim: SimClient, inst: dict, history_limit: int = 2000) -> dict:
    """Read the whole world via REST (validated). Shared by the engine and the benchmark."""
    names = list(LIST_ENDPOINTS)
    results = await asyncio.gather(
        *[sim.get(LIST_ENDPOINTS[n]) for n in names],
        sim.get("/v1/metrics"),
        sim.get("/v1/demand-history", params={"limit": history_limit}),
    )
    snap = {n: results[i] for i, n in enumerate(names)}
    snap["metrics"] = results[len(names)]
    snap["demand_history"] = results[len(names) + 1]
    snap.update(tick=inst["tick"], sim_time=inst["sim_time"], tick_minutes=inst["tick_minutes"], status=inst["status"])
    return snap


class Engine:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.sim = SimClient()
        self.snap: dict | None = None
        self.prev: dict | None = None
        self.risks: dict = {}
        self.forecasts: list = []
        self.last_tick: int | None = None
        self.last_sync_at: datetime | None = None
        self.degraded = False
        self.sse_connected = False
        self.started_at = time.time()
        self.mode = {"mode": self.settings.decision_mode,
                     "auto_confidence_threshold": self.settings.auto_confidence_threshold,
                     "auto_max_quantity": self.settings.auto_max_quantity}
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._last_full = 0.0
        self._consecutive_failures = 0

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._poll_loop()), asyncio.create_task(self._sse_loop())]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await self.sim.close()

    # ------------------------------------------------------------ pub/sub for /api/stream
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: str, data: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait((event, data))
            except asyncio.QueueFull:
                self._subscribers.discard(q)

    # ------------------------------------------------------------ loops
    async def _poll_loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.settings.poll_interval_s)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            try:
                await self.sync()
            except Exception:  # never let the loop die
                log.exception("sync loop error")

    async def _sse_loop(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with httpx.AsyncClient(base_url=self.settings.simulator_url, timeout=httpx.Timeout(5, read=40)) as c:
                    async with c.stream("GET", "/v1/stream") as resp:
                        if resp.status_code != 200:
                            raise RuntimeError(f"stream HTTP {resp.status_code}")
                        self._set_sse(True)
                        backoff = 1.0
                        self._wake.set()  # resync via REST after (re)connect
                        event = None
                        async for line in resp.aiter_lines():
                            if line.startswith("event:"):
                                event = line[6:].strip()
                            elif line.startswith("data:") and event in ("simulation.tick", "simulator.notice",
                                                                         "allocation.status_changed", "inventory.updated"):
                                self._wake.set()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self.sse_connected:
                    log_event(log, "simulator stream disconnected", logging.WARNING, error=repr(exc))
                self._set_sse(False)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15)

    def _set_sse(self, up: bool) -> None:
        if up and not self.sse_connected:
            log_event(log, "simulator stream connected", event="sse_connected")
        self.sse_connected = up
        SSE_CONNECTED.set(1 if up else 0)

    # ------------------------------------------------------------ observe
    async def sync(self) -> None:
        async with self._lock:
            try:
                inst = await self.sim.get("/v1/instance")
                tick_changed = inst["tick"] != self.last_tick
                if not tick_changed and self.snap and time.monotonic() - self._last_full < 3:
                    return
                snap = await self._fetch_all(inst)
            except SimulatorUnavailable as exc:
                self._consecutive_failures += 1
                if self._consecutive_failures >= 2:  # hysteresis: one failed sync is not an outage
                    self._enter_degraded(str(exc))
                return
            except InvalidSimulatorResponse as exc:
                self._raise_alert("warning", "integration_failure", {"type": "simulator", "id": exc.endpoint},
                                  "Invalid simulator response rejected", exc.detail[:300])
                log_event(log, "invalid simulator response rejected", logging.WARNING, endpoint=exc.endpoint)
                return
            self._last_full = time.monotonic()
            self._consecutive_failures = 0
            if self.degraded:
                self._recover()
            if self.last_tick is not None and inst["tick"] < self.last_tick:
                self._on_reset()
            self.prev, self.snap = self.snap, snap
            self.last_sync_at = datetime.now(timezone.utc)
            self._update_gauges(snap)
            if self.sim.stale:
                self._raise_alert("warning", "stale_data", {"type": "simulator", "id": "simulator"},
                                  "Simulator reports stale data", "Values may lag; decisions use the latest trusted state.")
            else:
                self._resolve(kind="stale_data")
            if tick_changed:
                self.last_tick = inst["tick"]
                await self._run_tick(snap)

    async def _fetch_all(self, inst: dict) -> dict:
        return await fetch_snapshot(self.sim, inst, self.settings.demand_history_limit)

    def _update_gauges(self, snap: dict) -> None:
        SIM_TICK.set(snap["tick"])
        SERVICE_LEVEL.set(snap["metrics"]["service_level"])
        UNMET_LITERS.set(snap["metrics"]["unmet_demand_liters"])
        for st in snap["stations"]:
            for f, v in st["inventory"].items():
                STATION_INVENTORY.labels(st["id"], f).set(v)
        for d in snap["depots"]:
            for f, v in d["inventory"].items():
                DEPOT_INVENTORY.labels(d["id"], f).set(v)

    # ------------------------------------------------------------ degraded / recover
    def _enter_degraded(self, reason: str) -> None:
        if not self.degraded:
            log_event(log, "entering degraded mode: serving cached state", logging.WARNING, reason=reason)
            self.publish("status", {"degraded": True, "reason": reason})
        self.degraded = True
        DEGRADED.set(1)
        self._raise_alert("critical", "integration_failure", {"type": "simulator", "id": "simulator"},
                          "Simulator unavailable - degraded mode",
                          f"{reason}. Showing last known state; auto-execution paused.")

    def _recover(self) -> None:
        self.degraded = False
        DEGRADED.set(0)
        RECOVERIES.inc()
        self._resolve(kinds={"integration_failure", "recovery"})
        self._raise_alert("info", "recovery", {"type": "simulator", "id": "simulator"},
                          "Simulator connection recovered", "Live state restored; decisions resumed.", dedupe=False)
        log_event(log, "recovered from degraded mode", event="recovery")
        self.publish("status", {"degraded": False})

    def _on_reset(self) -> None:
        log_event(log, "simulator reset detected", event="sim_reset")
        with session() as s:
            for r in s.exec(select(Recommendation).where(Recommendation.status == "pending")).all():
                r.status, r.updated_at = "superseded", utcnow()
                s.add(r)
            s.commit()
        self._resolve(kinds=AUTO_RESOLVE_KINDS)

    # ------------------------------------------------------------ detect / predict / decide
    async def _run_tick(self, snap: dict) -> None:
        t0 = time.perf_counter()
        result = await asyncio.to_thread(intel_bridge.run_pipeline, snap, self.prev)
        PIPELINE_SECONDS.observe(time.perf_counter() - t0)
        self.risks = result["risks"]
        self.forecasts = result.get("forecasts") or []
        if result.get("mape") is not None:
            PREDICTION_MAPE.set(result["mape"])
        if result.get("fallback_used"):
            self._raise_alert("warning", "fallback", {"type": "component", "id": "intelligence"},
                              "Fallback allocation policy active",
                              intel_bridge.STATUS.last_error or "intelligence module unavailable")
        else:
            self._resolve(kind="fallback")

        # alerts: raise current, resolve the ones that disappeared
        current_keys = set()
        for a in result["alerts"]:
            key = self._raise_alert(a["severity"], a["kind"], a.get("entity", {}), a["title"], a.get("detail", ""),
                                    code=a.get("code", ""))
            current_keys.add(key)
        self._resolve(kinds={"shortage_risk", "disruption", "bottleneck", "anomalous_demand", "inventory_anomaly"},
                      keep=current_keys)

        recs = self._store_recommendations(snap, result["recommendations"])
        if recs:
            MODEL_CONFIDENCE.set(sum(r.confidence for r in recs) / len(recs))
        await self._auto_execute(recs)
        self._record_metrics(snap)
        self.publish("tick", {"tick": snap["tick"], "service_level": snap["metrics"]["service_level"]})

    def _store_recommendations(self, snap: dict, drafts: list[dict]) -> list[Recommendation]:
        created = []
        with session() as s:
            for d in drafts:
                alloc = d.get("allocation", {})
                existing = s.exec(select(Recommendation).where(
                    Recommendation.status == "pending", Recommendation.station_id == d["station_id"],
                    Recommendation.fuel_type == d["fuel_type"])).all()
                same = [e for e in existing if e.body.get("allocation", {}).get("route_id") == alloc.get("route_id")
                        and abs(e.body.get("allocation", {}).get("quantity", 0) - alloc.get("quantity", 0))
                        <= 0.1 * max(alloc.get("quantity", 1), 1)]
                if same:
                    continue  # unchanged recommendation still pending
                for e in existing:
                    e.status, e.updated_at = "superseded", utcnow()
                    s.add(e)
                conf = float(d.get("confidence", 0.5))
                rec = Recommendation(tick=snap["tick"], station_id=d["station_id"], fuel_type=d["fuel_type"],
                                     mode=d.get("mode", "heuristic"), confidence=conf,
                                     requires_human_review=bool(d.get("requires_human_review", conf < 0.7)),
                                     body=d)
                s.add(rec)
                RECOMMENDATIONS.labels(rec.mode).inc()
                created.append(rec)
            s.commit()
            for r in created:
                s.refresh(r)
                self.publish("recommendation", self.rec_view(r))
            PENDING_RECS.set(len(s.exec(select(Recommendation.id).where(Recommendation.status == "pending")).all()))
        return created

    async def _auto_execute(self, recs: list[Recommendation]) -> None:
        if self.mode["mode"] != "assisted" or self.degraded:
            return
        for r in recs:
            qty = r.body.get("allocation", {}).get("quantity", 0)
            if (r.confidence >= self.mode["auto_confidence_threshold"] and qty <= self.mode["auto_max_quantity"]
                    and not r.requires_human_review):
                await self.execute(r.id, actor="autopilot")

    def _record_metrics(self, snap: dict) -> None:
        with session() as s:
            open_alerts = len(s.exec(select(Alert.id).where(Alert.status == "open")).all())
            m = snap["metrics"]
            s.add(MetricPoint(tick=snap["tick"], service_level=m["service_level"],
                              unmet_demand_liters=m["unmet_demand_liters"],
                              allocation_liters=m["allocation_liters"], open_alerts=open_alerts))
            s.commit()

    # ------------------------------------------------------------ alerts
    def _raise_alert(self, severity: str, kind: str, entity: dict, title: str, detail: str = "",
                     dedupe: bool = True, code: str = "") -> str:
        # code = sub-type within kind (e.g. bottleneck "dispatch" vs "low_stock") so distinct problems
        # on the same entity stay separate alerts
        key = f"{kind}|{code}|{json.dumps(entity, sort_keys=True)}"
        with session() as s:
            existing = s.exec(select(Alert).where(Alert.dedupe_key == key, Alert.status == "open")).first() if dedupe else None
            if existing:
                if existing.severity != severity or existing.title != title:
                    existing.severity, existing.title, existing.detail = severity, title, detail
                    s.add(existing)
                    s.commit()
                return key
            a = Alert(tick=self.last_tick or 0, severity=severity, kind=kind, entity=entity, dedupe_key=key,
                      title=title, detail=detail)
            s.add(a)
            s.commit()
            s.refresh(a)
            ALERTS_RAISED.labels(kind, severity).inc()
            if kind == "shortage_risk":
                SHORTAGE_ALERTS.inc()
            log_event(log, "alert raised", logging.WARNING if severity != "info" else logging.INFO,
                      alert_id=a.id, kind=kind, severity=severity, title=title)
            self.publish("alert", self.alert_view(a))
            self._update_alert_gauge(s)
        return key

    def _resolve(self, kind: str | None = None, kinds: set[str] | None = None, keep: set[str] | None = None) -> None:
        kinds = kinds or ({kind} if kind else set())
        with session() as s:
            rows = s.exec(select(Alert).where(Alert.status == "open")).all()
            changed = False
            for a in rows:
                if a.kind in kinds and (keep is None or a.dedupe_key not in keep):
                    a.status, a.resolved_at = "resolved", utcnow()
                    s.add(a)
                    changed = True
            if changed:
                s.commit()
                self._update_alert_gauge(s)

    @staticmethod
    def _update_alert_gauge(s) -> None:
        for sev in ("info", "warning", "critical"):
            OPEN_ALERTS.labels(sev).set(len(s.exec(select(Alert.id).where(Alert.status == "open", Alert.severity == sev)).all()))

    # ------------------------------------------------------------ act (executor)
    async def execute(self, rec_id: int, actor: str = "operator", quantity: float | None = None,
                      note: str | None = None) -> Recommendation:
        with session() as s:
            rec = s.get(Recommendation, rec_id)
            if rec is None:
                raise KeyError(rec_id)
            if rec.status not in ("pending", "failed"):
                return rec
            alloc = dict(rec.body.get("allocation", {}))
            if quantity is not None:
                alloc["quantity"] = float(quantity)
            body = {"idempotency_key": f"gta7-rec{rec.id}-q{int(alloc['quantity'])}",
                    "source_depot_id": alloc["source_depot_id"], "destination_station_id": rec.station_id,
                    "route_id": alloc["route_id"], "fuel_type": rec.fuel_type, "quantity": alloc["quantity"]}
            try:
                code, resp = await self.sim.post_allocation(body)
            except SimulatorUnavailable as exc:
                code, resp = 503, {"detail": {"code": "SIMULATOR_UNAVAILABLE", "message": str(exc)}}
            if code in (200, 201):
                rec.status, rec.sim_allocation_id, rec.failure_reason = "executed", resp.get("id"), None
                result = "OK"
            else:
                detail = resp.get("detail") or resp.get("error") or {}
                result = detail.get("code", f"HTTP_{code}") if isinstance(detail, dict) else f"HTTP_{code}"
                rec.status = "pending" if result in ("SIMULATOR_UNAVAILABLE", "FAULT_INJECTED") else "failed"
                rec.failure_reason = f"{result}: {detail.get('message', '') if isinstance(detail, dict) else detail}"
            if quantity is not None:
                rec.body = {**rec.body, "allocation": alloc}
            rec.updated_at = utcnow()
            s.add(rec)
            s.add(Decision(tick=self.last_tick or 0, actor=actor, action="execute" if actor == "autopilot" else "approve",
                           recommendation_id=rec.id, result=result, note=note))
            s.commit()
            s.refresh(rec)
            DECISIONS.labels(actor, "approve", result).inc()
            log_event(log, "allocation decision", actor=actor, recommendation_id=rec.id, result=result,
                      quantity=alloc["quantity"], station=rec.station_id, fuel=rec.fuel_type)
            self.publish("recommendation", self.rec_view(rec))
        self._wake.set()
        return rec

    def reject(self, rec_id: int, note: str | None, actor: str = "operator") -> Recommendation:
        with session() as s:
            rec = s.get(Recommendation, rec_id)
            if rec is None:
                raise KeyError(rec_id)
            if rec.status == "pending":
                rec.status, rec.updated_at = "rejected", utcnow()
                s.add(rec)
                s.add(Decision(tick=self.last_tick or 0, actor=actor, action="reject", recommendation_id=rec.id,
                               result="OK", note=note))
                s.commit()
                s.refresh(rec)
                DECISIONS.labels(actor, "reject", "OK").inc()
                log_event(log, "recommendation rejected", recommendation_id=rec.id, note=note)
            return rec

    # ------------------------------------------------------------ views
    @staticmethod
    def rec_view(r: Recommendation) -> dict:
        b = r.body or {}
        return {"id": r.id, "tick": r.tick, "status": r.status, "mode": r.mode,
                "station_id": r.station_id, "fuel_type": r.fuel_type,
                "allocation": b.get("allocation"), "situation": b.get("situation"),
                "expected_impact": b.get("expected_impact"), "confidence": r.confidence,
                "requires_human_review": r.requires_human_review,
                "signals": b.get("signals", []), "constraints": b.get("constraints", []),
                "alternatives": b.get("alternatives", []), "explanation": b.get("explanation", ""),
                "explanation_source": b.get("explanation_source", "template"),
                "sim_allocation_id": r.sim_allocation_id, "failure_reason": r.failure_reason,
                "created_at": r.created_at, "updated_at": r.updated_at}

    @staticmethod
    def alert_view(a: Alert) -> dict:
        return {"id": a.id, "tick": a.tick, "severity": a.severity, "kind": a.kind, "entity": a.entity,
                "title": a.title, "detail": a.detail, "status": a.status, "created_at": a.created_at,
                "resolved_at": a.resolved_at}

    def state_view(self) -> dict:
        snap = self.snap
        if snap is None:
            return {"instance": None, "data_freshness": {"stale": self.sim.stale, "degraded": self.degraded,
                                                         "last_sync_tick": None, "last_sync_at": None}}
        pending_by_depot: dict[str, float] = {}
        for a in snap["allocations"]:
            if a["status"] == "PENDING":
                pending_by_depot[a["source_depot_id"]] = pending_by_depot.get(a["source_depot_id"], 0) + a["quantity"]
        stations = [{**st, "risk": self.risks.get(st["id"], {})} for st in snap["stations"]]
        depots = [{**d, "dispatch_used_this_tick": pending_by_depot.get(d["id"], 0)} for d in snap["depots"]]
        regions = []
        for r in snap["regions"]:
            ids = {st["id"] for st in snap["stations"] if st["region_id"] == r["id"]}
            recent = [h for h in snap["demand_history"] if h["station_id"] in ids and h["tick"] > snap["tick"] - 16]
            agg: dict[str, float] = {}
            for h in recent:
                agg[h["fuel_type"]] = round(agg.get(h["fuel_type"], 0) + h["demand_liters"], 1)
            regions.append({**r, "demand_last_4h": agg})
        return {
            "instance": {"tick": snap["tick"], "sim_time": snap["sim_time"], "status": snap["status"]},
            "metrics": snap["metrics"], "regions": regions, "depots": depots, "stations": stations,
            "routes": snap["routes"],
            "in_transit": [a for a in snap["allocations"] if a["status"] in ("PENDING", "IN_TRANSIT")],
            "upcoming_supply": [s for s in snap["supply_arrivals"] if s["status"] != "ARRIVED"],
            "active_events": [e for e in snap["events"] if e["status"] in ("ACTIVE", "SCHEDULED")],
            "data_freshness": {"stale": self.sim.stale, "degraded": self.degraded, "last_sync_tick": snap["tick"],
                               "last_sync_at": self.last_sync_at},
        }


engine: Engine | None = None


def get_engine() -> Engine:
    assert engine is not None, "engine not started"
    return engine
