"""Allocation planning. v1: greedy heuristic that respects route, depot and station limits."""
from .forecast import forecast as _forecast
from .models import (
    AllocationPlan, Alternative, ExpectedImpact, Forecast, ProjectionPoint, RecommendationDraft,
    Risk, Situation, Snapshot, WhatIf,
)
from .risk import assess_risk, incoming, project, stockout_hours, stockout_prob

MIN_QTY = 500.0


def _candidates(s: Snapshot, station_id: str, fuel: str, depot_left: dict, depot_inv: dict) -> list[tuple[dict, float, list[str]]]:
    depots = {d["id"]: d for d in s.depots}
    st = next(x for x in s.stations if x["id"] == station_id)
    room = float(st["capacity"][fuel]) - float(st["inventory"][fuel]) - sum(incoming(s, station_id, fuel).values())
    out = []
    for r in s.routes:
        d = depots.get(r.get("source_depot_id"))
        if r.get("destination_station_id") != station_id or r.get("status") != "AVAILABLE" or not d or d.get("status") != "OPEN":
            continue
        limits = {
            f"route max {r['max_shipment']:.0f} L": float(r["max_shipment"]),
            f"station free capacity {room:.0f} L": room,
            f"depot {fuel.lower()} stock {depot_inv[(d['id'], fuel)]:.0f} L": depot_inv[(d["id"], fuel)],
            f"depot dispatch left this tick {depot_left[d['id']]:.0f} L": depot_left[d["id"]],
        }
        qty = min(limits.values())
        if qty >= MIN_QTY:
            out.append((r, qty, list(limits)))
    out.sort(key=lambda c: c[0]["transit_ticks"])
    return out


def _plan(s: Snapshot, fc: list[Forecast], risks: list[Risk], mode: str) -> list[RecommendationDraft]:
    by_key = {(f.station_id, f.fuel_type): f for f in fc}
    depot_left = {d["id"]: float(d.get("dispatch_capacity_per_tick", 0)) - float(d.get("dispatch_used_this_tick", 0)) for d in s.depots}
    depot_inv = {(d["id"], f): float(q) for d in s.depots for f, q in d.get("inventory", {}).items()}
    recs = []
    for r in sorted((x for x in risks if x.level in ("watch", "critical")), key=lambda x: -x.stockout_prob):
        f = by_key[(r.station_id, r.fuel_type)]
        cands = _candidates(s, r.station_id, r.fuel_type, depot_left, depot_inv)
        if not cands:
            continue
        options = []
        for route, qty, cons in cands:
            eta = s.tick + int(route["transit_ticks"])
            p_after = stockout_prob(s, f, r.current_inventory, {eta: qty})
            options.append((route, qty, cons, eta, p_after))
        route, qty, cons, eta, p_after = options[0]
        depot_left[route["source_depot_id"]] -= qty
        depot_inv[(route["source_depot_id"], r.fuel_type)] -= qty
        demand_4h = sum(f.per_tick[: 240 // s.tick_minutes])
        confidence = round(max(0.3, 1 - (f.mape_recent or 0.3)) * (0.8 if mode == "fallback" else 1.0), 2)
        recs.append(RecommendationDraft(
            tick=s.tick, mode=mode, station_id=r.station_id, fuel_type=r.fuel_type,
            allocation=AllocationPlan(source_depot_id=route["source_depot_id"], route_id=route["id"], quantity=qty, eta_tick=eta),
            situation=Situation(current_inventory=r.current_inventory, expected_demand_next_4h=round(demand_4h, 1),
                                projected_stockout_hours=r.stockout_hours),
            expected_impact=ExpectedImpact(stockout_prob_before=r.stockout_prob, stockout_prob_after=p_after,
                                           unmet_liters_avoided=round(max(0.0, sum(f.per_tick) - r.current_inventory), 1)),
            confidence=confidence, requires_human_review=confidence < 0.6,
            signals=[f"risk {r.level}, stockout in {r.stockout_hours} h"],
            constraints=cons,
            alternatives=[Alternative(source_depot_id=o[0]["source_depot_id"], route_id=o[0]["id"], quantity=o[1],
                                      eta_tick=o[3], stockout_prob_after=o[4]) for o in options[1:]],
        ))
    return recs


def plan(s: Snapshot, fc: list[Forecast], risks: list[Risk]) -> list[RecommendationDraft]:
    return _plan(s, fc, risks, "heuristic")


def fallback_plan(s: Snapshot) -> list[RecommendationDraft]:
    fc = _forecast(s)
    return _plan(s, fc, assess_risk(s, fc), "fallback")


def simulate(s: Snapshot, fc: list[Forecast], station_id: str, fuel_type: str,
             source_depot_id: str, route_id: str, quantity: float) -> WhatIf:
    f = next(x for x in fc if x.station_id == station_id and x.fuel_type == fuel_type)
    st = next(x for x in s.stations if x["id"] == station_id)
    route = next(r for r in s.routes if r["id"] == route_id)
    inv = float(st["inventory"][fuel_type])
    extra = {s.tick + int(route["transit_ticks"]): quantity}
    pts = lambda path: [ProjectionPoint(tick=t, inventory=round(i, 1)) for t, i in path]
    return WhatIf(
        projection_without=pts(project(s, f, inv)), projection_with=pts(project(s, f, inv, extra)),
        stockout_prob_before=stockout_prob(s, f, inv), stockout_prob_after=stockout_prob(s, f, inv, extra),
    )
