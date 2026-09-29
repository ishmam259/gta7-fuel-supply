"""Allocation planning: which depot sends how much fuel over which route to which station.

1. Candidates: every OPEN station/fuel at watch/critical/outage risk.
2. Need: liters to cover demand until arrival + COVER_TICKS, minus stock and inbound, capped by free tank space.
3. Optimizer (scipy linprog / HiGHS): split scarce depot stock and dispatch capacity across stations, weighted by
   risk and by whether the route arrives before the stockout. The first FIRST_TICKS of cover is worth
   FIRST_BONUS x more, so when fuel is short every station gets a share before anyone is topped up.
   Falls back to a greedy heuristic if scipy fails.
4. Every quantity obeys the simulator's validation rules (guide §5.2), re-checked by `violations()`.
"""
import logging
import math
import statistics

from .models import (
    AllocationPlan, Alternative, ExpectedImpact, Forecast, ProjectionPoint, RecommendationDraft,
    Risk, Situation, Snapshot, WhatIf,
)
from .risk import (
    SHIPPABLE_DEPOT, assess_risk, dispatch_used, expected_unmet, incoming, long_forecasts, project, stockout_prob,
)

log = logging.getLogger("gta7.intel.planner")

MIN_QTY = 500.0        # smaller shipments are not worth a truck
ROUND_TO = 50.0        # liters
COVER_TICKS = 96       # stock to cover after arrival (24 h)
FIRST_TICKS = 24       # "keep it running" cover after arrival (6 h), valued FIRST_BONUS x more
FIRST_BONUS = 3.0
AT_RISK = ("watch", "critical", "outage")
REVIEW_BELOW = 0.6     # confidence under this needs a human


# ---------------- network limits ----------------
class Limits:
    """Remaining capacity this tick, shared by all recommendations in one plan."""

    def __init__(self, s: Snapshot):
        self.dispatch = {d["id"]: float(d.get("dispatch_capacity_per_tick") or 0) - dispatch_used(s, d) for d in s.depots}
        self.stock = {(d["id"], f): float(q) for d in s.depots for f, q in (d.get("inventory") or {}).items()}

    def copy(self) -> "Limits":
        c = Limits.__new__(Limits)
        c.dispatch, c.stock = dict(self.dispatch), dict(self.stock)
        return c

    def take(self, depot: str, fuel: str, qty: float):
        self.dispatch[depot] -= qty
        self.stock[(depot, fuel)] -= qty


def _room(s: Snapshot, st: dict, fuel: str) -> float:
    """Free tank space counting fuel already on the way (the simulator checks inventory + qty <= capacity)."""
    return float(st["capacity"].get(fuel, 0)) - float(st["inventory"].get(fuel, 0)) - sum(incoming(s, st["id"], fuel).values())


def usable_routes(s: Snapshot, station_id: str) -> list[dict]:
    depots = {d["id"]: d for d in s.depots}
    return sorted((r for r in s.routes
                   if r.get("destination_station_id") == station_id and r.get("status") == "AVAILABLE"
                   and depots.get(r.get("source_depot_id"), {}).get("status") in SHIPPABLE_DEPOT),
                  key=lambda r: r.get("transit_ticks", 99))


def route_cap(s: Snapshot, st: dict, fuel: str, route: dict, lim: Limits) -> tuple[float, list[str]]:
    """Largest legal quantity on this route right now, and the limits that apply."""
    d = route["source_depot_id"]
    limits = {
        f"route max {float(route['max_shipment']):.0f} L": float(route["max_shipment"]),
        f"station free capacity {_room(s, st, fuel):.0f} L": _room(s, st, fuel),
        f"depot {fuel.lower()} stock {lim.stock.get((d, fuel), 0):.0f} L": lim.stock.get((d, fuel), 0.0),
        f"depot dispatch left this tick {lim.dispatch.get(d, 0):.0f} L": lim.dispatch.get(d, 0.0),
    }
    return max(0.0, min(limits.values())), list(limits)


def violations(s: Snapshot, recs: list[RecommendationDraft]) -> list[str]:
    """Replays guide §5.2 validation for a batch of allocations submitted this tick. Empty list = all legal."""
    errs = []
    st = {x["id"]: x for x in s.stations}
    dp = {x["id"]: x for x in s.depots}
    rt = {x["id"]: x for x in s.routes}
    used = {d: dispatch_used(s, dp[d]) for d in dp}
    stock = {(d, f): float(q) for d in dp for f, q in dp[d]["inventory"].items()}
    added: dict[tuple, float] = {}
    for rec in recs:
        a, f = rec.allocation, rec.fuel_type
        r = rt.get(a.route_id)
        if not r or a.source_depot_id not in dp or rec.station_id not in st:
            errs.append(f"{a.route_id}: NOT_FOUND")
            continue
        if (r["source_depot_id"], r["destination_station_id"]) != (a.source_depot_id, rec.station_id):
            errs.append(f"{a.route_id}: ROUTE_MISMATCH")
        if dp[a.source_depot_id]["status"] not in SHIPPABLE_DEPOT:
            errs.append(f"{a.route_id}: DEPOT_CLOSED")
        if st[rec.station_id]["status"] != "OPEN":
            errs.append(f"{a.route_id}: STATION_CLOSED")
        if r["status"] != "AVAILABLE":
            errs.append(f"{a.route_id}: ROUTE_DISRUPTED")
        if a.quantity <= 0 or a.quantity > float(r["max_shipment"]):
            errs.append(f"{a.route_id}: ROUTE_CAPACITY_EXCEEDED")
        if stock[(a.source_depot_id, f)] < a.quantity:
            errs.append(f"{a.route_id}: INSUFFICIENT_INVENTORY")
        if used[a.source_depot_id] + a.quantity > float(dp[a.source_depot_id]["dispatch_capacity_per_tick"]):
            errs.append(f"{a.route_id}: DISPATCH_CAPACITY_EXCEEDED")
        key = (rec.station_id, f)
        added[key] = added.get(key, 0.0) + a.quantity
        if float(st[rec.station_id]["inventory"][f]) + added[key] > float(st[rec.station_id]["capacity"][f]):
            errs.append(f"{a.route_id}: DESTINATION_CAPACITY_EXCEEDED")
        stock[(a.source_depot_id, f)] -= a.quantity
        used[a.source_depot_id] += a.quantity
    return errs


# ---------------- candidates ----------------
class Candidate:
    def __init__(self, s: Snapshot, risk: Risk, fc: Forecast, st: dict):
        self.risk, self.fc, self.st = risk, fc, st
        self.station_id, self.fuel = risk.station_id, risk.fuel_type
        self.routes = usable_routes(s, self.station_id)
        self.stockout_tick = s.tick + max(0, int(risk.stockout_hours * 60 / s.tick_minutes))
        # weight: likelihood + urgency, outages/critical first
        self.weight = (0.2 + risk.stockout_prob + 1.0 / (1.0 + risk.stockout_hours)
                       + (1.0 if risk.level in ("critical", "outage") else 0.0))

    def need(self, s: Snapshot, route: dict | None = None, cover: int = COVER_TICKS) -> float:
        route = route or (self.routes[0] if self.routes else {"transit_ticks": 2})
        horizon = min(len(self.fc.per_tick), int(route["transit_ticks"]) + cover)
        have = self.risk.current_inventory + sum(incoming(s, self.station_id, self.fuel).values())
        return max(0.0, min(sum(self.fc.per_tick[:horizon]) - have, _room(s, self.st, self.fuel)))

    def timeliness(self, s: Snapshot, route: dict) -> float:
        """1.0 if the truck arrives before the station runs dry, less the later it is."""
        late = s.tick + int(route["transit_ticks"]) - self.stockout_tick
        return 1.0 if late <= 0 else max(0.3, 1.0 - late / 16)


def _candidates(s: Snapshot, fc: list[Forecast], risks: list[Risk], long_fc: dict) -> list[Candidate]:
    by_key = {(f.station_id, f.fuel_type): f for f in fc}
    stations = {st["id"]: st for st in s.stations}
    out = []
    for r in risks:
        st = stations.get(r.station_id)
        if r.level not in AT_RISK or not st or st.get("status") != "OPEN":
            continue
        f = long_fc.get((r.station_id, r.fuel_type)) or by_key.get((r.station_id, r.fuel_type))
        if f is None:
            continue
        c = Candidate(s, r, f, st)
        if c.routes and c.need(s) >= MIN_QTY:
            out.append(c)
    return sorted(out, key=lambda c: -c.weight)


# ---------------- solvers ----------------
def _floor(q: float) -> float:
    return math.floor(q / ROUND_TO) * ROUND_TO


def _solve_lp(s: Snapshot, cands: list[Candidate], lim: Limits) -> dict[tuple[int, str], float]:
    """Variables: x[c,r] liters per (candidate, route), then y1[c] (first cover) and y2[c] (rest) per candidate."""
    from scipy.optimize import linprog

    pairs = [(i, r) for i, c in enumerate(cands) for r in c.routes]
    if not pairs:
        return {}
    n, m = len(pairs), len(cands)
    need = [c.need(s) for c in cands]
    first = [min(need[i], c.need(s, cover=FIRST_TICKS)) for i, c in enumerate(cands)]
    # minimise: late/slow routes cost a little, covered demand earns weight (first cover earns FIRST_BONUS x)
    cost = ([cands[i].weight * (1 - cands[i].timeliness(s, r)) + 1e-4 * r["transit_ticks"] for i, r in pairs]
            + [-FIRST_BONUS * c.weight for c in cands] + [-c.weight for c in cands])
    bounds = ([(0.0, route_cap(s, cands[i].st, cands[i].fuel, r, lim)[0]) for i, r in pairs]
              + [(0.0, first[i]) for i in range(m)] + [(0.0, need[i] - first[i]) for i in range(m)])
    a_eq, b_eq = [], []
    for i in range(m):                                   # sum_r x[i,r] == y1[i] + y2[i]
        row = [1.0 if p[0] == i else 0.0 for p in pairs] + [0.0] * (2 * m)
        row[n + i] = row[n + m + i] = -1.0
        a_eq.append(row)
        b_eq.append(0.0)
    a_ub, b_ub = [], []
    for d, left in lim.dispatch.items():                 # depot dispatch capacity this tick (all fuels)
        a_ub.append([1.0 if p[1]["source_depot_id"] == d else 0.0 for p in pairs] + [0.0] * (2 * m))
        b_ub.append(max(0.0, left))
    for (d, f), left in lim.stock.items():               # depot stock per fuel
        a_ub.append([1.0 if p[1]["source_depot_id"] == d and cands[p[0]].fuel == f else 0.0 for p in pairs] + [0.0] * (2 * m))
        b_ub.append(max(0.0, left))
    res = linprog(cost, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if res.status != 0:
        raise RuntimeError(f"linprog: {res.message}")
    return {(i, r["id"]): float(x) for (i, r), x in zip(pairs, res.x[:n]) if x > 1e-6}


def _solve_greedy(s: Snapshot, cands: list[Candidate], lim: Limits) -> dict[tuple[int, str], float]:
    out, scratch = {}, lim.copy()
    for i, c in enumerate(cands):                        # most at-risk first
        need = c.need(s)
        for r in sorted(c.routes, key=lambda r: (-c.timeliness(s, r), r["transit_ticks"])):
            if need < MIN_QTY:
                break
            q = min(need, route_cap(s, c.st, c.fuel, r, scratch)[0])
            if q >= MIN_QTY:
                out[(i, r["id"])] = q
                scratch.take(r["source_depot_id"], c.fuel, q)
                need -= q
    return out


# ---------------- recommendation building ----------------
def _signals(s: Snapshot, c: Candidate, route: dict) -> list[str]:
    r = c.risk
    sig = [f"risk {r.level}: stockout in {r.stockout_hours} h, p(12h)={r.stockout_prob:.0%}"]
    m = float(c.st.get("demand_multiplier", 1.0))
    if m >= 1.2:
        sig.append(f"demand {m:.1f}x normal (demand spike)")
    if r.incoming_liters:
        sig.append(f"{r.incoming_liters:.0f} L already inbound (tick {r.next_supply_eta_tick})")
    if r.depot_supply_delayed:
        sig.append("upstream depot supply DELAYED")
    blocked = [x["id"] for x in s.routes if x.get("destination_station_id") == c.station_id and x.get("status") != "AVAILABLE"]
    if blocked:
        sig.append(f"route {', '.join(blocked)} unavailable, using {route['id']}")
    dep = next((d for d in s.depots if d["id"] == route["source_depot_id"]), {})
    if dep.get("status") == "CONSTRAINED":
        sig.append(f"{dep.get('name', dep.get('id'))} constrained")
    for ev in s.events:
        if ev.get("status") != "ACTIVE":
            continue
        p = ev.get("parameters") or {}
        scope = {x for k in ("station_ids", "region_ids", "route_ids", "depot_ids") for x in p.get(k, [])}
        if not scope or scope & {c.station_id, c.st.get("region_id"), route["id"], route["source_depot_id"]}:
            sig.append(f"active {ev.get('type')} event")
    return sig


def _confidence(s: Snapshot, c: Candidate, route: dict, qty: float, need: float, mode: str) -> float:
    mape = c.fc.mape_recent if c.fc.mape_recent is not None else 0.25
    conf = max(0.3, 1.0 - 2 * mape)                                  # forecast quality
    if c.timeliness(s, route) < 1.0:
        conf *= 0.85                                                  # arrives after the stockout
    if need > 0 and qty < 0.7 * need:
        conf *= 0.85                                                  # partial fill
    if c.risk.depot_supply_delayed or any(e.get("status") == "ACTIVE" for e in s.events):
        conf *= 0.9                                                   # disrupted network, more uncertainty
    if mode == "fallback":
        conf *= 0.75
    return round(min(conf, 0.99), 2)


def _build(s: Snapshot, cands: list[Candidate], alloc: dict[tuple[int, str], float], lim: Limits, mode: str) -> list[RecommendationDraft]:
    recs = []
    routes = {r["id"]: r for r in s.routes}
    base = lim.copy()                                # limits before this plan, used to show alternatives
    for (i, rid), q in sorted(alloc.items(), key=lambda kv: -cands[kv[0][0]].weight):
        c, route = cands[i], routes[rid]
        cap, cons = route_cap(s, c.st, c.fuel, route, lim)
        qty = _floor(min(q, cap))
        if qty < MIN_QTY:
            continue
        lim.take(route["source_depot_id"], c.fuel, qty)
        eta = s.tick + int(route["transit_ticks"])
        inv = c.risk.current_inventory
        need = c.need(s, route)
        alts = []
        for other in c.routes:
            if other["id"] == rid:
                continue
            aq = _floor(min(route_cap(s, c.st, c.fuel, other, base)[0], need or qty))
            if aq >= MIN_QTY:
                aeta = s.tick + int(other["transit_ticks"])
                alts.append(Alternative(source_depot_id=other["source_depot_id"], route_id=other["id"], quantity=aq,
                                        eta_tick=aeta, stockout_prob_after=stockout_prob(s, c.fc, inv, {aeta: aq}, from_tick=aeta)))
        conf = _confidence(s, c, route, qty, need, mode)
        recs.append(RecommendationDraft(
            tick=s.tick, mode=mode, station_id=c.station_id, fuel_type=c.fuel,
            allocation=AllocationPlan(source_depot_id=route["source_depot_id"], route_id=rid, quantity=qty, eta_tick=eta),
            situation=Situation(current_inventory=inv,
                                expected_demand_next_4h=round(sum(c.fc.per_tick[:240 // s.tick_minutes]), 1),
                                projected_stockout_hours=c.risk.stockout_hours),
            expected_impact=ExpectedImpact(
                stockout_prob_before=c.risk.stockout_prob,
                stockout_prob_after=stockout_prob(s, c.fc, inv, {eta: qty}, from_tick=eta),
                unmet_liters_avoided=round(max(0.0, expected_unmet(s, c.fc, inv) - expected_unmet(s, c.fc, inv, {eta: qty})), 1)),
            confidence=conf,
            requires_human_review=conf < REVIEW_BELOW or mode == "fallback" or c.timeliness(s, route) < 1.0,
            signals=_signals(s, c, route) + ([f"runs dry before the truck arrives (tick {eta}); gap cannot be avoided"]
                                             if c.stockout_tick < eta else []),
            constraints=cons + ([f"need {need:.0f} L, only {qty:.0f} L possible this tick"] if qty < need - ROUND_TO else []),
            alternatives=alts,
        ))
    return recs


def _plan(s: Snapshot, fc: list[Forecast], risks: list[Risk], long_fc: dict, use_lp: bool) -> list[RecommendationDraft]:
    cands = _candidates(s, fc, risks, long_fc)
    if not cands:
        return []
    lim = Limits(s)
    mode = "fallback"
    if use_lp:
        try:
            alloc, mode = _solve_lp(s, cands, lim), "optimizer"
        except Exception as exc:
            log.warning("optimizer failed, using heuristic: %r", exc)
            alloc, mode = _solve_greedy(s, cands, lim), "heuristic"
    else:
        alloc = _solve_greedy(s, cands, lim)
    recs = _build(s, cands, alloc, lim, mode)
    bad = violations(s, recs)
    if bad:  # never hand out an allocation the simulator would reject
        log.error("planner produced invalid allocations, dropping them: %s", bad)
        bad_routes = {b.split(":")[0] for b in bad}
        recs = [r for r in recs if r.allocation.route_id not in bad_routes]
    return recs


# ---------------- public API ----------------
def plan(s: Snapshot, fc: list[Forecast], risks: list[Risk]) -> list[RecommendationDraft]:
    return _plan(s, fc, risks, long_forecasts(s), use_lp=True)


def _simple_forecasts(s: Snapshot, horizon: int = 192) -> list[Forecast]:
    """Recent-average demand, no model: used when the forecaster itself is broken."""
    out = []
    for st in s.stations:
        for fuel in ("DIESEL", "PETROL", "OCTANE"):
            hist = [float(h.get("demand_liters", 0)) for h in s.demand_history
                    if h.get("station_id") == st["id"] and h.get("fuel_type") == fuel][-96:]
            mean = statistics.fmean(hist) if hist else 80.0
            std = statistics.pstdev(hist) if len(hist) > 1 else mean * 0.3
            out.append(Forecast(station_id=st["id"], fuel_type=fuel, horizon_ticks=horizon, per_tick=[mean] * horizon,
                                lower=[max(0.0, mean - 1.28 * std)] * horizon, upper=[mean + 1.28 * std] * horizon,
                                mape_recent=0.3, residual_std=std))
    return out


def fallback_plan(s: Snapshot) -> list[RecommendationDraft]:
    """Rule-based: recent-average demand + greedy allocation. Uses neither the forecaster nor the optimizer."""
    fc = _simple_forecasts(s)
    by_key = {(f.station_id, f.fuel_type): f for f in fc}
    return _plan(s, fc, assess_risk(s, fc, long_fc=by_key), by_key, use_lp=False)


def simulate(s: Snapshot, fc: list[Forecast], station_id: str, fuel_type: str,
             source_depot_id: str, route_id: str, quantity: float) -> WhatIf:
    f = next(x for x in fc if x.station_id == station_id and x.fuel_type == fuel_type)
    st = next(x for x in s.stations if x["id"] == station_id)
    route = next(r for r in s.routes if r["id"] == route_id)
    if (route["source_depot_id"], route["destination_station_id"]) != (source_depot_id, station_id):
        raise ValueError("ROUTE_MISMATCH")
    inv, cap = float(st["inventory"][fuel_type]), float(st["capacity"][fuel_type])
    extra = {s.tick + int(route["transit_ticks"]): float(quantity)}
    lf = long_forecasts(s).get((station_id, fuel_type), f)
    pts = lambda path: [ProjectionPoint(tick=t, inventory=round(min(i, cap), 1)) for t, i in path]
    return WhatIf(
        projection_without=pts(project(s, f, inv)), projection_with=pts(project(s, f, inv, extra)),
        stockout_prob_before=stockout_prob(s, lf, inv), stockout_prob_after=stockout_prob(s, lf, inv, extra),
    )
