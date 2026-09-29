"""A/B/C on the REAL simulator: no action vs deterministic LP (plan) vs RL-tuned LP (rl_plan).

Same reset + same seed + same crisis script for every policy (the simulator is deterministic), every recommendation
auto-approved and POSTed with an idempotency key, so any difference comes from the policy.
Local simulator only (it resets it). Run from backend/:  python -m app.intel.compare_policies [ticks]
Writes policy_comparison.json and policy_comparison.png next to this file.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .forecast import forecast
from .models import Snapshot
from .planner import plan
from .risk import assess_risk
from .rl import rl_plan

SIM = "http://localhost:8000"
OUT = Path(__file__).with_name("policy_comparison.json")

# same shape as the team's combined crisis: Dhaka demand spike, Gazipur->Mirpur route down, delayed Gazipur supply,
# Patiya constrained (offsets from the start tick)
CRISIS = [
    {"type": "demand_spike", "offset": 8, "duration_ticks": 48, "parameters": {"region_ids": ["region-dhaka"], "multiplier": 1.6}},
    {"type": "route_disruption", "offset": 16, "duration_ticks": 32, "parameters": {"route_ids": ["route-gazipur-mirpur"]}},
    {"type": "shipment_delay", "offset": 4, "duration_ticks": 1, "parameters": {"depot_ids": ["depot-gazipur"], "delay_ticks": 12}},
    {"type": "depot_constraint", "offset": 20, "duration_ticks": 24, "parameters": {"depot_ids": ["depot-patiya"]}},
]


def _get(path):
    return json.load(urllib.request.urlopen(SIM + path, timeout=15))


def _post(path, body=None):
    req = urllib.request.Request(SIM + path, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def snapshot() -> Snapshot:
    inst = _get("/v1/instance")
    return Snapshot(tick=inst["tick"], sim_time=inst["sim_time"], tick_minutes=inst["tick_minutes"],
                    depots=_get("/v1/depots"), stations=_get("/v1/stations"), routes=_get("/v1/routes"),
                    allocations=_get("/v1/allocations"), supply_arrivals=_get("/v1/supply-arrivals"),
                    events=_get("/v1/events"), regions=_get("/v1/regions"),
                    demand_history=_get("/v1/demand-history?limit=2000"), metrics=_get("/v1/metrics"))


def run(policy_name: str, planner, ticks: int) -> dict:
    _post("/admin/pause")
    _post("/admin/reset")
    t0 = _get("/v1/instance")["tick"]
    for e in CRISIS:
        code, err = _post("/admin/events", {"type": e["type"], "start_tick": t0 + e["offset"],
                                            "duration_ticks": e["duration_ticks"], "parameters": e["parameters"]})
        assert code in (200, 201), (e["type"], code, err)
    sent = rejected = liters = 0
    reasons: dict[str, int] = {}
    curve = []
    started = time.time()
    for _ in range(ticks):
        s = snapshot()
        curve.append({"tick": s.tick, "service_level": s.metrics.get("service_level", 1.0),
                      "unmet": s.metrics.get("unmet_demand_liters", 0.0)})
        if planner is not None:
            fc = forecast(s)
            for i, r in enumerate(planner(s, fc, assess_risk(s, fc))):
                code, err = _post("/v1/allocations", {
                    "idempotency_key": f"cmp-{policy_name}-{s.tick}-{i}", "source_depot_id": r.allocation.source_depot_id,
                    "destination_station_id": r.station_id, "route_id": r.allocation.route_id,
                    "fuel_type": r.fuel_type, "quantity": r.allocation.quantity})
                if code in (200, 201):
                    sent += 1
                    liters += r.allocation.quantity
                else:
                    rejected += 1
                    key = (err or str(code)).split('"code":"')[-1].split('"')[0]
                    reasons[key] = reasons.get(key, 0) + 1
        _post("/admin/step")
    m = _get("/v1/metrics")
    return {"policy": policy_name, "ticks": ticks, "service_level": round(m["service_level"], 4),
            "unmet_liters": round(m["unmet_demand_liters"], 1), "served_liters": round(m["served_demand_liters"], 1),
            "trucks_sent": sent, "liters_shipped": liters, "rejected": rejected, "reject_reasons": reasons,
            "seconds": round(time.time() - started, 1), "curve": curve}


def chart(results: list[dict], path: Path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4), gridspec_kw={"width_ratios": [2, 1]})
    colors = {"no_action": "#9ca3af", "deterministic_lp": "#2563eb", "rl": "#16a34a"}
    for r in results:
        a.plot([p["tick"] for p in r["curve"]], [100 * p["service_level"] for p in r["curve"]],
               label=f"{r['policy']} ({100 * r['service_level']:.1f}%)", color=colors.get(r["policy"]), lw=2)
    a.set_title("Service level over time (same crisis, same seed)"); a.set_xlabel("tick (15 min)"); a.set_ylabel("%")
    a.legend(); a.grid(alpha=.3)
    acting = [r for r in results if r["policy"] != "no_action"]
    b.bar([r["policy"] for r in acting], [r["trucks_sent"] for r in acting], color=[colors[r["policy"]] for r in acting])
    for i, r in enumerate(acting):
        b.text(i, r["trucks_sent"], str(r["trucks_sent"]), ha="center", va="bottom")
    b.set_title("Trucks sent"); b.grid(alpha=.3, axis="y")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    return path


if __name__ == "__main__":
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 192
    results = []
    for name, fn in (("no_action", None), ("deterministic_lp", plan), ("rl", rl_plan)):
        res = run(name, fn, ticks)
        results.append(res)
        print({k: v for k, v in res.items() if k != "curve"}, flush=True)
    OUT.write_text(json.dumps({"crisis": CRISIS, "results": results}, indent=1))
    print("chart:", chart(results, OUT.with_suffix(".png")))
