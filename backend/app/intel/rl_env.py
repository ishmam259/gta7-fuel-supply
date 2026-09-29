"""Fast offline training world for the RL cover-level policy (no simulator calls).

Built from a real snapshot (stations, depots, routes, supply schedule) and the documented demand model that the
forecast already uses (guide §8.5/§8.6). One step = one 15-minute tick, same mechanics as the simulator:
trucks depart on the tick they are ordered and arrive `transit_ticks` later; dispatch capacity per depot per tick;
route max; station capacity; depot stock; supply arrivals (with delays); demand spikes and route disruptions.

Each tick, every station/fuel under WATCH_HOURS of cover with nothing inbound asks a policy for a target cover
(hours). The dispatch rule is the planner's: fastest available route, quantity = SAFETY x demand for
transit + cover, minus stock and inbound, capped by every simulator limit.
"""
import math
import random
from functools import lru_cache
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .forecast import DAILY, prior

FUELS = ("DIESEL", "PETROL", "OCTANE")
TICKS_PER_HOUR = 4
WATCH_HOURS = 16.0
SAFETY = 1.2
MIN_QTY, ROUND_TO = 500.0, 50.0
ACTIONS = (12, 18, 24, 30)          # target cover in hours
REWARD_WINDOW = 32                  # ticks after a decision that count towards its reward (8 h)
TRUCK_COST = 40.0                   # "liters-equivalent" cost of sending one truck
NOISE = 0.10


@dataclass
class Decision:
    tick: int
    station: str
    fuel: str
    depot: str
    state: tuple
    action: int
    qty: float


@dataclass
class World:
    s: dict                                    # raw snapshot dict (used for static data)
    tick: int
    sim_time: datetime
    st_inv: dict                               # (station, fuel) -> L
    dp_inv: dict                               # (depot, fuel) -> L
    mult: dict                                 # station -> demand multiplier
    route_ok: dict                             # route id -> bool
    supply: list                               # [{depot, fuel, qty, tick}]
    trucks: list = field(default_factory=list)  # [{station, fuel, qty, arrive}]
    unmet: dict = field(default_factory=dict)  # (tick, station, fuel) -> L
    served: float = 0.0
    lost: float = 0.0
    trucks_sent: int = 0


def _region_factor(s: dict) -> dict:
    return {r["id"]: float(r.get("demand_factor", 1.0)) for r in s.get("regions", [])}


@lru_cache(maxsize=None)
def _per_tick(prof: str, fuel: str, hour: int) -> float:
    return prior(prof, fuel, datetime(2026, 1, 1, hour), 15)


def expected_demand(w: World, station: dict, fuel: str, ticks: int) -> float:
    """Liters expected over the next `ticks` (documented model x multiplier x region)."""
    prof, h0 = station["demand_profile"], w.sim_time.hour * 4 + w.sim_time.minute // 15
    rf = w.rf.get(station["region_id"], 1.0)
    return sum(_per_tick(prof, fuel, ((h0 + i) // 4) % 24) for i in range(ticks)) * rf * w.mult[station["id"]]


def cover_hours(w: World, station: dict, fuel: str) -> float:
    have = w.st_inv[(station["id"], fuel)] + sum(t["qty"] for t in w.trucks if (t["station"], t["fuel"]) == (station["id"], fuel))
    rate = DAILY[station["demand_profile"]][fuel] / 96 * w.rf.get(station["region_id"], 1.0) * w.mult[station["id"]]
    return have / rate / TICKS_PER_HOUR


def state_of(w: World, station: dict, fuel: str, routes: list) -> tuple:
    """Small discrete state: cover bucket, depot stock bucket, spike active, primary route open."""
    cov = cover_hours(w, station, fuel)
    cov_b = min(3, int(cov // 4))                                   # 0-4, 4-8, 8-12, 12-16 h
    dep = routes[0]["source_depot_id"] if routes else None
    dcap = next((d["capacity"][fuel] for d in w.s["depots"] if d["id"] == dep), 1)
    ratio = w.dp_inv.get((dep, fuel), 0) / dcap
    dep_b = 0 if ratio < 0.2 else (1 if ratio < 0.5 else 2)
    spike = int(w.mult[station["id"]] > 1.05)
    fastest = min((r for r in w.s["routes"] if r["destination_station_id"] == station["id"]), key=lambda r: r["transit_ticks"])
    primary_ok = int(w.route_ok[fastest["id"]])                     # is the station's normal (fastest) route open?
    return cov_b, dep_b, spike, primary_ok


def new_world(s: dict, rng: random.Random, events: bool = True) -> World:
    t0 = rng.randrange(24, 480)
    sim0 = datetime.fromisoformat(str(s["sim_time"])) - timedelta(minutes=15 * s["tick"]) + timedelta(minutes=15 * t0)
    st_inv = {(st["id"], f): st["capacity"][f] * rng.uniform(0.35, 0.8) for st in s["stations"] for f in FUELS}
    dp_inv = {(d["id"], f): d["capacity"][f] * rng.uniform(0.15, 0.6) for d in s["depots"] for f in FUELS}
    # supply every 64 ticks per depot/fuel, sized to about a day of downstream demand (guide §8.7)
    supply = []
    for d in s["depots"]:
        for i, f in enumerate(FUELS):
            daily = sum(DAILY[st["demand_profile"]][f] for st in s["stations"] if st["region_id"] == d["region_id"])
            first = t0 + rng.randrange(0, 64)
            supply += [{"depot": d["id"], "fuel": f, "qty": 0.8 * daily, "tick": first + 64 * k + 4 * i} for k in range(4)]
    w = World(s=s, tick=t0, sim_time=sim0, st_inv=st_inv, dp_inv=dp_inv,
              mult={st["id"]: 1.0 for st in s["stations"]}, route_ok={r["id"]: True for r in s["routes"]}, supply=supply)
    w.events = _random_events(s, rng, t0) if events else []
    w.rf = _region_factor(s)
    return w


def _random_events(s: dict, rng: random.Random, t0: int) -> list:
    ev = []
    if rng.random() < 0.6:
        region = rng.choice([r["id"] for r in s.get("regions", [])] or ["region-dhaka"])
        start = t0 + rng.randrange(0, 96)
        ev.append({"type": "demand_spike", "start": start, "end": start + rng.randrange(24, 64), "region": region,
                   "m": rng.choice([1.5, 1.8, 2.0])})
    if rng.random() < 0.4:
        start = t0 + rng.randrange(0, 96)
        ev.append({"type": "route_disruption", "start": start, "end": start + rng.randrange(16, 48),
                   "route": rng.choice([r["id"] for r in s["routes"] if r["transit_ticks"] <= 3])})
    if rng.random() < 0.4:
        ev.append({"type": "shipment_delay", "start": t0 + rng.randrange(0, 96), "delay": rng.randrange(8, 24),
                   "depot": rng.choice([d["id"] for d in s["depots"]])})
    return ev


def _apply_events(w: World):
    for e in w.events:
        if e["type"] == "demand_spike":
            active = e["start"] <= w.tick < e["end"]
            for st in w.s["stations"]:
                if st["region_id"] == e["region"]:
                    w.mult[st["id"]] = e["m"] if active else 1.0
        elif e["type"] == "route_disruption":
            w.route_ok[e["route"]] = not (e["start"] <= w.tick < e["end"])
        elif e["type"] == "shipment_delay" and w.tick == e["start"]:
            for sup in w.supply:
                if sup["depot"] == e["depot"] and sup["tick"] >= w.tick:
                    sup["tick"] += e["delay"]


def usable_routes(w: World, station_id: str) -> list:
    return sorted((r for r in w.s["routes"] if r["destination_station_id"] == station_id and w.route_ok[r["id"]]),
                  key=lambda r: r["transit_ticks"])


def dispatch(w: World, policy, rng: random.Random) -> list[Decision]:
    """Ask the policy for a cover target for every pair that needs fuel; send legal trucks. Returns decisions."""
    decisions = []
    left = {d["id"]: float(d["dispatch_capacity_per_tick"]) for d in w.s["depots"]}
    pairs = [(st, f) for st in w.s["stations"] for f in FUELS]
    pairs.sort(key=lambda p: cover_hours(w, *p))                     # most urgent first
    for st, f in pairs:
        if cover_hours(w, st, f) >= WATCH_HOURS or any((t["station"], t["fuel"]) == (st["id"], f) for t in w.trucks):
            continue
        routes = usable_routes(w, st["id"])
        if not routes:
            continue
        state = state_of(w, st, f, routes)
        action = policy(state, rng)
        if action is None:                                           # "no action" baseline
            continue
        r = routes[0]
        dep = r["source_depot_id"]
        have = w.st_inv[(st["id"], f)]
        want = SAFETY * expected_demand(w, st, f, r["transit_ticks"] + action * TICKS_PER_HOUR) - have
        qty = min(want, r["max_shipment"], st["capacity"][f] - have, w.dp_inv[(dep, f)], left[dep])
        qty = math.floor(max(0.0, qty) / ROUND_TO) * ROUND_TO
        if qty < MIN_QTY:
            continue
        w.dp_inv[(dep, f)] -= qty
        left[dep] -= qty
        w.trucks.append({"station": st["id"], "fuel": f, "qty": qty, "arrive": w.tick + r["transit_ticks"]})
        w.trucks_sent += 1
        decisions.append(Decision(w.tick, st["id"], f, dep, state, action, qty))
    return decisions


def step(w: World, rng: random.Random):
    """Advance one tick: events, arrivals, demand."""
    _apply_events(w)
    for t in [t for t in w.trucks if t["arrive"] <= w.tick]:
        st = next(x for x in w.s["stations"] if x["id"] == t["station"])
        w.st_inv[(t["station"], t["fuel"])] = min(st["capacity"][t["fuel"]], w.st_inv[(t["station"], t["fuel"])] + t["qty"])
        w.trucks.remove(t)
    for sup in [x for x in w.supply if x["tick"] <= w.tick]:
        d = next(x for x in w.s["depots"] if x["id"] == sup["depot"])
        w.dp_inv[(sup["depot"], sup["fuel"])] = min(d["capacity"][sup["fuel"]], w.dp_inv[(sup["depot"], sup["fuel"])] + sup["qty"])
        w.supply.remove(sup)
    rf = w.rf
    for st in w.s["stations"]:
        for f in FUELS:
            d = _per_tick(st["demand_profile"], f, w.sim_time.hour) * rf.get(st["region_id"], 1.0) * w.mult[st["id"]]
            d *= max(0.0, rng.gauss(1.0, NOISE))
            k = (st["id"], f)
            sold = min(w.st_inv[k], d)
            w.st_inv[k] -= sold
            w.served += sold
            w.lost += d - sold
            w.unmet[(w.tick, st["id"], f)] = d - sold
    w.tick += 1
    w.sim_time += timedelta(minutes=15)


def run_episode(s: dict, policy, seed: int, ticks: int = 192, events: bool = True):
    """Returns (world, decisions). Same seed => same starting stock, events and demand noise for every policy."""
    rng_world, rng_noise, rng_pol = random.Random(seed), random.Random(seed + 1), random.Random(seed + 2)
    w = new_world(s, rng_world, events)
    decisions = []
    for _ in range(ticks):
        decisions += dispatch(w, policy, rng_pol)
        step(w, rng_noise)
    return w, decisions


def service_level(w: World) -> float:
    return w.served / max(w.served + w.lost, 1e-9)
