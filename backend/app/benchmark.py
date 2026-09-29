"""A/B benchmark: the same deterministic world with and without the platform.

Both runs: reset the simulator (same seed), inject the same scenario, advance N ticks with /admin/step.
- baseline: no allocations at all (what happens if nobody acts)
- platform: every tick, observe -> run the intelligence pipeline -> execute its recommendations

Because the simulator is deterministic, the difference in service level / unmet demand is attributable
to our decisions. CLI: `python -m app.benchmark --scenario combined_crisis --ticks 96`
"""
import argparse
import asyncio
import json
import logging
import time

import httpx
from datetime import datetime, timezone
from pathlib import Path

from . import intel_bridge, scenarios
from .engine import fetch_snapshot
from .logging_setup import log_event
from .sim_client import SimClient, SimulatorUnavailable

log = logging.getLogger("gta7.benchmark")
RESULT_PATH = Path("data/benchmark_latest.json")

STATE: dict = {"status": "idle", "progress": 0.0, "result": None, "error": None}


async def _snapshot(sim: SimClient) -> dict:
    inst = await sim.get("/v1/instance")
    return await fetch_snapshot(sim, inst)


async def _with_retry(fn, attempts: int = 5):
    for i in range(attempts):
        try:
            return await fn()
        except SimulatorUnavailable:
            if i == attempts - 1:
                raise
            await asyncio.sleep(1 + i)


async def _run_policy(sim: SimClient, policy: str, scenario: str | None, ticks: int, run_id: str,
                      progress_base: float) -> dict:
    # reset wipes and reloads the whole world; it can take a while under load
    await sim.http.post("/admin/reset", timeout=300)
    for _ in range(60):
        if await sim.health():
            break
        await asyncio.sleep(1)
    await sim.admin("POST", "/admin/pause")
    if scenario:
        for ev in scenarios.events_for(scenario, 0):
            await sim.admin("POST", "/admin/events", json=ev)
    series, allocations, rejected = [], 0, {}
    for t in range(ticks):
        if policy == "platform":
            snap = await _with_retry(lambda: _snapshot(sim))
            result = await asyncio.to_thread(intel_bridge.run_pipeline, snap, None)
            for i, rec in enumerate(result["recommendations"]):
                a = rec["allocation"]
                code, body = await sim.post_allocation({
                    "idempotency_key": f"bench-{run_id}-t{t}-{i}", "source_depot_id": a["source_depot_id"],
                    "destination_station_id": rec["station_id"], "route_id": a["route_id"],
                    "fuel_type": rec["fuel_type"], "quantity": a["quantity"]})
                if code in (200, 201):
                    allocations += 1
                else:
                    err = (body.get("detail") or body.get("error") or {})
                    k = err.get("code", str(code)) if isinstance(err, dict) else str(code)
                    rejected[k] = rejected.get(k, 0) + 1
        await sim.admin("POST", "/admin/step")
        if t % 4 == 3 or t == ticks - 1:
            m = await _with_retry(lambda: sim.get("/v1/metrics"))
            series.append({"tick": t + 1, "service_level": m["service_level"],
                           "unmet_demand_liters": m["unmet_demand_liters"]})
        STATE["progress"] = round(progress_base + 0.5 * (t + 1) / ticks, 3)
    m = await _with_retry(lambda: sim.get("/v1/metrics"))
    return {"policy": policy, "final": m, "allocations_submitted": allocations,
            "allocations_rejected": rejected, "series": series}


async def run_benchmark(scenario: str | None = "combined_crisis", ticks: int = 96) -> dict:
    if scenario and scenario not in scenarios.SCENARIOS:
        raise ValueError(f"unknown scenario {scenario}")
    sim = SimClient()
    sim.http.timeout = httpx.Timeout(20.0)
    sim.breaker.threshold = 1000  # benchmark handles retries itself
    run_id = datetime.now(timezone.utc).strftime("%H%M%S")
    t0 = time.perf_counter()
    try:
        baseline = await _run_policy(sim, "baseline", scenario, ticks, run_id, 0.0)
        platform = await _run_policy(sim, "platform", scenario, ticks, run_id, 0.5)
    finally:
        await sim.close()
    b, p = baseline["final"], platform["final"]
    result = {
        "scenario": scenario, "ticks": ticks, "sim_hours": ticks * 15 / 60,
        "baseline": baseline, "platform": platform,
        "summary": {
            "service_level_baseline": round(b["service_level"], 4),
            "service_level_platform": round(p["service_level"], 4),
            "service_level_gain_pts": round((p["service_level"] - b["service_level"]) * 100, 2),
            "unmet_liters_baseline": round(b["unmet_demand_liters"], 1),
            "unmet_liters_platform": round(p["unmet_demand_liters"], 1),
            "unmet_liters_avoided": round(b["unmet_demand_liters"] - p["unmet_demand_liters"], 1),
            "unmet_reduction_pct": round(100 * (1 - p["unmet_demand_liters"] / b["unmet_demand_liters"]), 1)
            if b["unmet_demand_liters"] > 0 else None,
        },
        "duration_s": round(time.perf_counter() - t0, 1),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, indent=1, default=str))
    log_event(log, "benchmark finished", **result["summary"], scenario=scenario, ticks=ticks)
    return result


async def run_in_background(scenario: str | None, ticks: int) -> None:
    from .engine import engine as live
    STATE.update(status="running", progress=0.0, error=None, started_at=time.time())
    if live is not None:
        live.paused_for_benchmark = True  # the benchmark owns the simulator while it runs
    try:
        STATE["result"] = await run_benchmark(scenario, ticks)
        STATE["status"] = "done"
    except Exception as exc:  # report, don't crash the API
        log.exception("benchmark failed")
        STATE.update(status="failed", error=repr(exc))
    finally:
        if live is not None:
            live.paused_for_benchmark = False


def latest() -> dict:
    out = {k: v for k, v in STATE.items()}
    if out["result"] is None and RESULT_PATH.exists():
        out["result"] = json.loads(RESULT_PATH.read_text())
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="With vs without platform benchmark")
    ap.add_argument("--scenario", default="combined_crisis", help="preset name or 'none'")
    ap.add_argument("--ticks", type=int, default=96)
    args = ap.parse_args()
    res = asyncio.run(run_benchmark(None if args.scenario == "none" else args.scenario, args.ticks))
    print(json.dumps(res["summary"], indent=2))
