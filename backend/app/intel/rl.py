"""RL-tuned hybrid planner: tabular Q-learning picks the TARGET COVER (12/18/24/30 h) per station x fuel;
the normal LP planner then decides the trucks and still enforces every simulator rule.

State  (48 values): cover bucket (0-4/4-8/8-12/12-16 h), primary depot stock bucket (<20% / <50% / more),
                    demand spike active, primary route open.
Action (4):         target cover 12 / 18 / 24 / 30 h.
Reward:             -(liters lost at that station/fuel + TRUCK_COST) / hours until it needs its next truck,
                    i.e. cost per hour (average-cost view, so bigger deliveries only win if they really save trucks
                    without losing sales).
Training:           offline in `rl_env` (documented demand model, same mechanics as the simulator), random crises.
Policy file:        rl_policy.json next to this module; if missing, rl_plan() falls back to the LP (24 h).
"""
import json
import random
from pathlib import Path

from . import rl_env as E
from .models import Forecast, RecommendationDraft, Risk, Snapshot

POLICY_FILE = Path(__file__).with_name("rl_policy.json")
DEFAULT_COVER = 24


class QTable:
    def __init__(self, q: dict | None = None, n: dict | None = None):
        self.q = q or {}
        self.n = n or {}

    def key(self, state) -> str:
        return ",".join(map(str, state))

    def best(self, state) -> int:
        row = self.q.get(self.key(state))
        return E.ACTIONS[max(range(len(E.ACTIONS)), key=lambda i: row[i])] if row else DEFAULT_COVER

    def update(self, state, action: int, reward: float, alpha: float):
        k, i = self.key(state), E.ACTIONS.index(action)
        row = self.q.setdefault(k, [0.0] * len(E.ACTIONS))
        cnt = self.n.setdefault(k, [0] * len(E.ACTIONS))
        cnt[i] += 1
        row[i] += max(alpha, 1.0 / cnt[i]) * (reward - row[i])

    def save(self, path: Path = POLICY_FILE, meta: dict | None = None):
        path.write_text(json.dumps({"actions": E.ACTIONS, "q": self.q, "n": self.n, "meta": meta or {}}, indent=1))

    @classmethod
    def load(cls, path: Path = POLICY_FILE) -> "QTable | None":
        try:
            d = json.loads(path.read_text())
            return cls(d["q"], d.get("n"))
        except Exception:
            return None


def _rewards(w: E.World, decisions: list[E.Decision], end_tick: int):
    """Cost-per-hour reward for each decision: until the same station/fuel's next decision (or episode end)."""
    by_pair: dict[tuple, list[E.Decision]] = {}
    for d in decisions:
        by_pair.setdefault((d.station, d.fuel), []).append(d)
    for (st, f), ds in by_pair.items():
        for j, d in enumerate(ds):
            nxt = ds[j + 1].tick if j + 1 < len(ds) else end_tick
            lost = sum(w.unmet.get((t, st, f), 0.0) for t in range(d.tick, nxt))
            hours = max(nxt - d.tick, 1) / E.TICKS_PER_HOUR
            yield d, -(lost + E.TRUCK_COST) / hours


def train(s: dict, episodes: int = 1500, ticks: int = 384, seed: int = 1000, eps0: float = 0.3) -> QTable:
    qt = QTable()
    for ep in range(episodes):
        eps = eps0 * (1 - ep / episodes) + 0.02
        policy = lambda state, rng: rng.choice(E.ACTIONS) if rng.random() < eps else qt.best(state)
        w, decisions = E.run_episode(s, policy, seed + ep, ticks=ticks)
        for d, r in _rewards(w, decisions, w.tick):
            qt.update(d.state, d.action, r, alpha=0.05)
    return qt


def evaluate(s: dict, policies: dict, seeds: range, ticks: int = 384) -> dict:
    """Same seeds (same stock, crises, demand noise) for every policy."""
    out = {}
    for name, pol in policies.items():
        sl, lost, trucks = [], [], []
        for sd in seeds:
            w, _ = E.run_episode(s, pol, sd, ticks=ticks)
            sl.append(E.service_level(w)); lost.append(w.lost); trucks.append(w.trucks_sent)
        out[name] = {"service_level": round(sum(sl) / len(sl), 4), "min_service_level": round(min(sl), 4),
                     "unmet_l_per_episode": round(sum(lost) / len(lost), 1), "trucks_per_episode": round(sum(trucks) / len(trucks), 1)}
    return out


# ---------------- runtime: plug the learned cover into the real planner ----------------
_TABLE: QTable | None = None


def policy_table() -> QTable | None:
    global _TABLE
    if _TABLE is None:
        _TABLE = QTable.load()
    return _TABLE


def live_state(s: Snapshot, r: Risk, station: dict, routes: list) -> tuple:
    """Same state buckets as training, computed from a live snapshot."""
    cov_b = min(3, max(0, int(r.stockout_hours // 4)))
    dep = routes[0]["source_depot_id"] if routes else None
    d = next((x for x in s.depots if x["id"] == dep), None)
    ratio = float(d["inventory"].get(r.fuel_type, 0)) / float(d["capacity"].get(r.fuel_type, 1) or 1) if d else 0.0
    dep_b = 0 if ratio < 0.2 else (1 if ratio < 0.5 else 2)
    spike = int(float(station.get("demand_multiplier", 1.0)) > 1.05)
    all_routes = [x for x in s.routes if x.get("destination_station_id") == station["id"]]
    fastest = min(all_routes, key=lambda x: x.get("transit_ticks", 99)) if all_routes else None
    primary_ok = int(bool(fastest) and fastest.get("status") == "AVAILABLE")
    return cov_b, dep_b, spike, primary_ok


def rl_plan(s: Snapshot, fc: list[Forecast], risks: list[Risk]) -> list[RecommendationDraft]:
    """LP planner with the RL-chosen target cover per station/fuel. mode="rl"; falls back to plain LP if no policy."""
    from . import planner
    qt = policy_table()
    if qt is None:
        return planner.plan(s, fc, risks)
    stations = {st["id"]: st for st in s.stations}
    chosen: dict[tuple, tuple[int, tuple]] = {}
    for r in risks:
        st = stations.get(r.station_id)
        if st:
            state = live_state(s, r, st, planner.usable_routes(s, r.station_id))
            chosen[(r.station_id, r.fuel_type)] = (qt.best(state), state)
    recs = planner._plan(s, fc, risks, planner.long_forecasts(s), use_lp=True,
                         cover_for=lambda sid, f: chosen.get((sid, f), (DEFAULT_COVER, None))[0] * E.TICKS_PER_HOUR)
    for rec in recs:
        cover, state = chosen.get((rec.station_id, rec.fuel_type), (DEFAULT_COVER, None))
        rec.mode = "rl"
        rec.signals.append(f"RL chose {cover} h target cover (state: cover bucket {state[0]}, depot bucket {state[1]}, "
                           f"spike {'yes' if state[2] else 'no'}, primary route {'open' if state[3] else 'down'})"
                           if state else f"RL default {cover} h cover")
    return recs


if __name__ == "__main__":  # python -m app.intel.rl  (from backend/): train, evaluate, save the policy
    import sys, time
    fixture = Path(__file__).resolve().parents[2] / "tests/intel/fixtures/snapshot_tick24.json"
    snap = json.loads(fixture.read_text())
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    t = time.time()
    qt = train(snap, episodes=n)
    res = evaluate(snap, {"no_action": lambda st, r: None, "lp_24h": lambda st, r: DEFAULT_COVER,
                          "rl": lambda st, r: qt.best(st)}, range(50000, 50100))
    qt.save(meta={"episodes": n, "train_seconds": round(time.time() - t, 1), "evaluation_100_eps_4_days": res})
    print(json.dumps(res, indent=1))
