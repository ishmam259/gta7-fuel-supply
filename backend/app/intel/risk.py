"""Stockout risk per (station, fuel) from forecast + inventory + incoming shipments."""
import math

from .models import Forecast, Risk, Snapshot


def _norm_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def incoming(s: Snapshot, station_id: str, fuel: str) -> dict[int, float]:
    """Liters arriving at the station per tick from in-transit allocations."""
    route_dest = {r["id"]: r.get("destination_station_id") for r in s.routes}
    out: dict[int, float] = {}
    for a in s.allocations:
        if a.get("status") != "IN_TRANSIT" or a.get("fuel_type") != fuel:
            continue
        if route_dest.get(a.get("route_id")) != station_id:
            continue
        t = int(a.get("expected_arrival_tick") or s.tick + 1)
        out[t] = out.get(t, 0.0) + float(a.get("quantity", 0.0))
    return out


def project(s: Snapshot, fc: Forecast, inventory: float, extra: dict[int, float] | None = None) -> list[tuple[int, float]]:
    """Inventory path over the forecast horizon (floored at 0)."""
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
    """P(cumulative demand over horizon > inventory + arrivals), normal approximation."""
    supply = inventory + sum(incoming(s, fc.station_id, fc.fuel_type).values()) + sum((extra or {}).values())
    demand = sum(fc.per_tick)
    sd = max(fc.residual_std * math.sqrt(len(fc.per_tick)), 1e-6)
    return round(1 - _norm_cdf((supply - demand) / sd), 4)


def stockout_hours(s: Snapshot, fc: Forecast, inventory: float, extra: dict[int, float] | None = None) -> float:
    for t, inv in project(s, fc, inventory, extra):
        if inv <= 0:
            return round((t - s.tick) * s.tick_minutes / 60, 2)
    rate = (sum(fc.per_tick) / len(fc.per_tick)) or 1e-6
    last = project(s, fc, inventory, extra)[-1][1]
    return round((len(fc.per_tick) + last / rate) * s.tick_minutes / 60, 2)


def _level(inv: float, open_: bool, hours: float, prob: float) -> str:
    if inv <= 0 or not open_:
        return "outage"
    if hours < 4 or prob > 0.5:
        return "critical"
    if hours < 12 or prob > 0.2:
        return "watch"
    return "ok"


def assess_risk(s: Snapshot, fc: list[Forecast]) -> list[Risk]:
    stations = {st["id"]: st for st in s.stations}
    out = []
    for f in fc:
        st = stations.get(f.station_id)
        if not st:
            continue
        inv = float(st.get("inventory", {}).get(f.fuel_type, 0.0))
        hours, prob = stockout_hours(s, f, inv), stockout_prob(s, f, inv)
        arrivals = incoming(s, f.station_id, f.fuel_type)
        out.append(Risk(
            station_id=f.station_id, fuel_type=f.fuel_type,
            level=_level(inv, st.get("status") == "OPEN", hours, prob),
            stockout_hours=hours, stockout_prob=prob, current_inventory=inv,
            next_supply_eta_tick=min(arrivals) if arrivals else None,
        ))
    return out
