"""Stockout risk per (station, fuel) from forecast + inventory + incoming shipments.

stockout_prob = max over the horizon of P(cumulative demand by tick k > inventory + arrivals by k), normal approx.
Per-tick sd comes from the forecast band; a systematic term (MAPE) covers model error that does not average out.
"""
import math

from .models import Forecast, Risk, Snapshot

Z80 = 1.28
SHIPPABLE_DEPOT = {"OPEN", "CONSTRAINED"}
MAX_HOURS = 168.0  # cap for "no stockout in sight"
LONG_HORIZON_TICKS = 192  # 48 h at 15 min/tick


def _norm_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _arrival_tick(s: Snapshot, a: dict, transit: dict[str, int]) -> int:
    if a.get("expected_arrival_tick") is not None:
        return int(a["expected_arrival_tick"])
    # PENDING: departs next tick, then transit_ticks on the road
    return int(a.get("created_tick", s.tick)) + 1 + transit.get(a.get("route_id"), 2)


def incoming(s: Snapshot, station_id: str, fuel: str) -> dict[int, float]:
    """Liters arriving at the station per tick from PENDING/IN_TRANSIT allocations."""
    routes = {r["id"]: r for r in s.routes}
    transit = {rid: int(r.get("transit_ticks", 2)) for rid, r in routes.items()}
    out: dict[int, float] = {}
    for a in s.allocations:
        if a.get("status") not in ("PENDING", "IN_TRANSIT") or a.get("fuel_type") != fuel:
            continue
        dest = a.get("destination_station_id") or routes.get(a.get("route_id"), {}).get("destination_station_id")
        if dest != station_id:
            continue
        t = max(_arrival_tick(s, a, transit), s.tick + 1)
        out[t] = out.get(t, 0.0) + float(a.get("quantity", 0.0))
    return out


def depot_supply(s: Snapshot, depot_id: str, fuel: str) -> list[dict]:
    """Upcoming (not yet arrived) supply for a depot/fuel, soonest first. DELAYED planned_tick already includes the delay."""
    out = []
    for a in s.supply_arrivals:
        if a.get("depot_id") != depot_id or a.get("fuel_type") != fuel or a.get("status") == "ARRIVED":
            continue
        eta = max(int(a.get("planned_tick", s.tick)), s.tick + 1)
        out.append({**a, "eta_tick": eta})
    return sorted(out, key=lambda a: a["eta_tick"])


def serving_depots(s: Snapshot, station_id: str) -> list[str]:
    return [r["source_depot_id"] for r in s.routes if r.get("destination_station_id") == station_id]


def project(s: Snapshot, fc: Forecast, inventory: float, extra: dict[int, float] | None = None) -> list[tuple[int, float]]:
    """Expected inventory path over the forecast horizon (floored at 0)."""
    arrivals = incoming(s, fc.station_id, fc.fuel_type)
    for t, q in (extra or {}).items():
        arrivals[t] = arrivals.get(t, 0.0) + q
    inv, path = inventory, []
    for i, d in enumerate(fc.per_tick, start=1):
        t = s.tick + i
        inv = max(0.0, inv + arrivals.get(t, 0.0) - d)
        path.append((t, inv))
    return path


def stockout_prob(s: Snapshot, fc: Forecast, inventory: float, extra: dict[int, float] | None = None) -> float:
    arrivals = incoming(s, fc.station_id, fc.fuel_type)
    for t, q in (extra or {}).items():
        arrivals[t] = arrivals.get(t, 0.0) + q
    sys_err = min(fc.mape_recent if fc.mape_recent is not None else 0.1, 0.5)
    cum_d = var = worst = 0.0
    for i, (mu, lo, hi) in enumerate(zip(fc.per_tick, fc.lower, fc.upper), start=1):
        supply_k = inventory + sum(q for t, q in arrivals.items() if t <= s.tick + i)
        cum_d += mu
        var += ((hi - lo) / (2 * Z80)) ** 2
        sd = max(math.sqrt(var) + sys_err * cum_d, 1e-6)
        worst = max(worst, 1 - _norm_cdf((supply_k - cum_d) / sd))
    return round(worst, 4)


def stockout_hours(s: Snapshot, fc: Forecast, inventory: float, extra: dict[int, float] | None = None) -> float:
    if inventory <= 0 and not incoming(s, fc.station_id, fc.fuel_type) and not extra:
        return 0.0
    path = project(s, fc, inventory, extra)
    for t, inv in path:
        if inv <= 0:
            return round((t - s.tick) * s.tick_minutes / 60, 2)
    rate = (sum(fc.per_tick) / len(fc.per_tick)) or 1e-6
    hours = (len(fc.per_tick) + path[-1][1] / rate) * s.tick_minutes / 60
    return round(min(hours, MAX_HOURS), 2)


def level(inventory: float, station_open: bool, hours: float, prob: float) -> str:
    if inventory <= 0 or not station_open:
        return "outage"
    if hours < 4 or prob > 0.5:
        return "critical"
    if hours < 12 or prob > 0.2:
        return "watch"
    return "ok"


def _long_forecasts(s: Snapshot) -> dict[tuple[str, str], Forecast]:
    """48 h forecast so stockout_hours follows the daily profile instead of extrapolating the current rate."""
    from .forecast import forecast
    try:
        return {(f.station_id, f.fuel_type): f for f in forecast(s, horizon=LONG_HORIZON_TICKS)}
    except Exception:
        return {}


def assess_risk(s: Snapshot, fc: list[Forecast]) -> list[Risk]:
    stations = {st["id"]: st for st in s.stations}
    long_fc = _long_forecasts(s)
    out = []
    for f in fc:
        st = stations.get(f.station_id)
        if not st:
            continue
        inv = float(st.get("inventory", {}).get(f.fuel_type, 0.0))
        hours = stockout_hours(s, long_fc.get((f.station_id, f.fuel_type), f), inv)
        prob = stockout_prob(s, f, inv)
        arrivals = incoming(s, f.station_id, f.fuel_type)
        upstream = sorted((a for d in serving_depots(s, f.station_id) for a in depot_supply(s, d, f.fuel_type)),
                          key=lambda a: a["eta_tick"])
        nxt = upstream[0] if upstream else None
        out.append(Risk(
            station_id=f.station_id, fuel_type=f.fuel_type,
            level=level(inv, st.get("status") == "OPEN", hours, prob),
            stockout_hours=hours, stockout_prob=prob, current_inventory=inv,
            next_supply_eta_tick=min(arrivals) if arrivals else None,
            incoming_liters=round(sum(arrivals.values()), 1),
            depot_supply_eta_tick=nxt["eta_tick"] if nxt else None,
            depot_supply_delayed=any(a.get("status") == "DELAYED" for a in upstream),
        ))
    return out
