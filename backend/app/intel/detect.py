"""Alert detection: shortage risk, anomalous demand, inventory anomalies, bottlenecks, disruptions.

Each AlertDraft has a stable `.key` (kind:entity:id:fuel) so the backend can de-duplicate and resolve.
"""
import statistics
from datetime import datetime

from .forecast import BUSY, hour_factor
from .models import AlertDraft, AlertEntity, Forecast, Snapshot
from .risk import assess_risk, depot_supply, dispatch_used

Z_WARN, Z_CRIT = 3.0, 5.0
MULTIPLIER_ALERT = 1.2
INV_TOLERANCE_L, INV_TOLERANCE_FRAC = 250.0, 0.03
DISPATCH_SATURATION = 0.9
DEPOT_COVER_HOURS_CRIT = 6.0
LOW_CONFIDENCE_MAPE = 0.2
ACTIVE_ALLOC = ("PENDING", "IN_TRANSIT", "ARRIVED")


def _alert(s, severity, kind, etype, eid, title, detail="", fuel=None, code="") -> AlertDraft:
    return AlertDraft(tick=s.tick, severity=severity, kind=kind, title=title, detail=detail, code=code,
                      entity=AlertEntity(type=etype, id=eid, fuel_type=fuel))


def _parse(t) -> datetime:
    return t if isinstance(t, datetime) else datetime.fromisoformat(str(t))


# ---------- shortage ----------
def _shortage(s: Snapshot, fc: list[Forecast], names: dict) -> list[AlertDraft]:
    out = []
    for r in assess_risk(s, fc):
        if r.level == "ok":
            continue
        sev = "warning" if r.level == "watch" else "critical"
        what = "out of stock" if r.level == "outage" else f"stockout in {r.stockout_hours} h"
        detail = f"p(stockout, 24h)={r.stockout_prob:.2f}, inventory {r.current_inventory:.0f} L"
        if r.next_supply_eta_tick is not None:
            detail += f", {r.incoming_liters:.0f} L arriving tick {r.next_supply_eta_tick}"
        if r.depot_supply_delayed:
            detail += ", upstream depot supply DELAYED"
        out.append(_alert(s, sev, "shortage_risk", "station", r.station_id,
                          f"{r.fuel_type.title()} {what} at {names[r.station_id]}", detail, r.fuel_type))
    return out


# ---------- demand ----------
def _demand(s: Snapshot, fc: list[Forecast], names: dict) -> list[AlertDraft]:
    out = []
    profiles = {st["id"]: st.get("demand_profile") for st in s.stations}
    last_tick = max((h.get("tick", -1) for h in s.demand_history), default=None)
    by_key = {(f.station_id, f.fuel_type): f for f in fc}
    now = _parse(s.sim_time)
    for h in s.demand_history:
        if h.get("tick") != last_tick:
            continue
        f = by_key.get((h.get("station_id"), h.get("fuel_type")))
        if not f or f.residual_std <= 0 or not f.per_tick[0]:
            continue
        # forecast per_tick[0] is for "now"; shift it to the observed row's hour
        prof, expected = profiles.get(f.station_id), f.per_tick[0]
        if prof in BUSY and h.get("sim_time"):
            expected *= hour_factor(prof, _parse(h["sim_time"]).hour) / hour_factor(prof, now.hour)
        rel_std = f.residual_std / statistics.fmean(f.per_tick)
        z = (float(h.get("demand_liters", 0)) - expected) / max(expected * rel_std, 1e-6)
        if z >= Z_WARN:
            out.append(_alert(s, "critical" if z >= Z_CRIT else "warning", "anomalous_demand", "station", f.station_id,
                              f"Abnormal {f.fuel_type.lower()} demand at {names[f.station_id]}",
                              f"{h['demand_liters']:.0f} L vs expected {expected:.0f} L (z={z:.1f})", f.fuel_type))
    for st in s.stations:
        m = float(st.get("demand_multiplier", 1.0))
        if m >= MULTIPLIER_ALERT:
            out.append(_alert(s, "critical" if m >= 1.5 else "warning", "anomalous_demand", "station", st["id"],
                              f"Demand {m:.1f}x normal at {names[st['id']]}", "demand_multiplier raised (demand spike)", code="multiplier"))
    return out


# ---------- inventory accounting ----------
# The backend reads the tick number first and the lists in parallel, so while the simulator runs a snapshot's
# contents can be one tick newer than its tick label. Every event at a window edge (tick p or n) may therefore
# belong on either side: we try each boundary shift and keep the explanation with the smallest residual.
SHIFTS = ((0, 0), (1, 0), (0, 1), (1, 1))   # (drop events at tick p, add events at tick n)


def _in_window(tick, p: int, n: int, shift: tuple[int, int]) -> bool:
    return tick is not None and (p + shift[0]) <= tick < (n + shift[1])


def _inventory(s: Snapshot, prev: Snapshot | None, names: dict) -> list[AlertDraft]:
    if not prev or s.tick <= prev.tick:
        return []
    out, p, n = [], prev.tick, s.tick
    hist_ticks = {h.get("tick") for h in s.demand_history}
    if not all(t in hist_ticks for t in range(p, n)):  # history window does not cover the gap
        return []

    prev_st = {st["id"]: st for st in prev.stations}
    for st in s.stations:
        old = prev_st.get(st["id"])
        if not old:
            continue
        for fuel, inv in st.get("inventory", {}).items():
            cap = float(st["capacity"].get(fuel, float("inf")))
            def resid(shift):
                sold = sum(float(h.get("served_liters", 0.0)) for h in s.demand_history
                           if h.get("station_id") == st["id"] and h.get("fuel_type") == fuel and _in_window(h.get("tick"), p, n, shift))
                got = sum(float(a.get("quantity", 0.0)) for a in s.allocations
                          if a.get("status") == "ARRIVED" and a.get("destination_station_id") == st["id"]
                          and a.get("fuel_type") == fuel and _in_window(a.get("actual_arrival_tick"), p, n, shift))
                return float(inv) - min(float(old["inventory"].get(fuel, 0)) + got - sold, cap)  # overflow is discarded
            r = min((resid(sh) for sh in SHIFTS), key=abs)
            tol = max(INV_TOLERANCE_L, INV_TOLERANCE_FRAC * cap)
            if abs(r) > tol:
                out.append(_alert(s, "warning", "inventory_anomaly", "station", st["id"],
                                  f"Unexplained {fuel.lower()} inventory {'drop' if r < 0 else 'gain'} at {names[st['id']]}",
                                  f"{r:+.0f} L vs deliveries/sales (ticks {p}-{n})", fuel))

    prev_dp = {d["id"]: d for d in prev.depots}
    for d in s.depots:
        old = prev_dp.get(d["id"])
        if not old:
            continue
        for fuel, inv in d.get("inventory", {}).items():
            cap = float(d["capacity"].get(fuel, float("inf")))
            def resid(shift):
                supplied = sum(float(a.get("quantity", 0)) for a in s.supply_arrivals
                               if a.get("depot_id") == d["id"] and a.get("fuel_type") == fuel and a.get("status") == "ARRIVED"
                               and _in_window(a.get("actual_tick"), p, n, shift))
                # depot stock drops when an allocation is POSTed, so it counts at its created tick
                shipped = sum(float(a.get("quantity", 0)) for a in s.allocations
                              if a.get("source_depot_id") == d["id"] and a.get("fuel_type") == fuel
                              and a.get("status") in ACTIVE_ALLOC and _in_window(a.get("created_tick"), p, n + 1, shift))
                return float(inv) - min(float(old["inventory"].get(fuel, 0)) + supplied - shipped, cap)  # overflow discarded
            r = min((resid(sh) for sh in SHIFTS), key=abs)
            tol = max(INV_TOLERANCE_L, INV_TOLERANCE_FRAC * cap)
            if abs(r) > tol:
                out.append(_alert(s, "warning", "inventory_anomaly", "depot", d["id"],
                                  f"Unexplained {fuel.lower()} inventory {'drop' if r < 0 else 'gain'} at {d.get('name', d['id'])}",
                                  f"{r:+.0f} L vs supply/dispatch (ticks {p}-{n})", fuel))
    return out


# ---------- bottlenecks ----------
def _bottlenecks(s: Snapshot, fc: list[Forecast]) -> list[AlertDraft]:
    out = []
    # each station's primary depot = source of its fastest route
    primary: dict[str, str] = {}
    for r in sorted(s.routes, key=lambda r: r.get("transit_ticks", 99)):
        primary.setdefault(r["destination_station_id"], r["source_depot_id"])
    rate = {(f.station_id, f.fuel_type): statistics.fmean(f.per_tick) for f in fc}  # L/tick
    ticks_per_hour = 60 / s.tick_minutes

    for d in s.depots:
        name = d.get("name", d["id"])
        cap = float(d.get("dispatch_capacity_per_tick") or 0)
        used = dispatch_used(s, d)
        if cap and used >= DISPATCH_SATURATION * cap:
            out.append(_alert(s, "warning", "bottleneck", "depot", d["id"], f"{name} dispatch saturated",
                              f"{used:.0f} / {cap:.0f} L committed this tick", code="dispatch"))
        if d.get("status") == "CONSTRAINED":
            out.append(_alert(s, "warning", "bottleneck", "depot", d["id"], f"{name} constrained",
                              "depot_constraint active: reduced capacity, prefer alternative depots", code="constrained"))
        served = [st for st, dep in primary.items() if dep == d["id"]]
        for fuel, inv in d.get("inventory", {}).items():
            burn = sum(rate.get((st, fuel), 0.0) for st in served) * ticks_per_hour  # L/h
            if burn <= 0:
                continue
            cover_h = float(inv) / burn
            nxt = depot_supply(s, d["id"], fuel)
            gap_h = ((nxt[0]["eta_tick"] - s.tick) / ticks_per_hour) if nxt else float("inf")
            if cover_h < min(gap_h, 24.0) or cover_h < DEPOT_COVER_HOURS_CRIT:
                when = f"next supply tick {nxt[0]['eta_tick']}" + (" (DELAYED)" if nxt[0].get("status") == "DELAYED" else "") if nxt else "no supply scheduled"
                out.append(_alert(s, "critical" if cover_h < DEPOT_COVER_HOURS_CRIT else "warning", "bottleneck", "depot", d["id"],
                                  f"Low {fuel.lower()} stock at {name}",
                                  f"{inv:.0f} L covers ~{cover_h:.1f} h of downstream demand; {when}", fuel, code="low_stock"))
    return out


# ---------- disruptions ----------
def _disruptions(s: Snapshot, names: dict) -> list[AlertDraft]:
    out = []
    for ev in s.events:
        if ev.get("status") == "ACTIVE":
            params = ev.get("parameters") or {}
            scope = ", ".join(str(x) for k in ("station_ids", "region_ids", "route_ids", "depot_ids") for x in params.get(k, [])) or "all"
            out.append(_alert(s, "warning", "disruption", "system", f"event-{ev.get('id')}",
                              f"Active {ev.get('type')} ({scope})",
                              f"ticks {ev.get('start_tick')}-{ev.get('end_tick')}, params {params}"))
    avail = {}
    for r in s.routes:
        if r.get("status") == "AVAILABLE":
            avail.setdefault(r["destination_station_id"], []).append(r["id"])
    for r in s.routes:
        if r.get("status") != "AVAILABLE":
            dest = r.get("destination_station_id")
            alts = avail.get(dest, [])
            out.append(_alert(s, "warning" if alts else "critical", "disruption", "route", r["id"],
                              f"Route {r['id']} {r.get('status')}",
                              f"{names.get(dest, dest)}: " + (f"alternative {', '.join(alts)}" if alts else "no alternative route")))
    for st in s.stations:
        if st.get("status") != "OPEN":
            out.append(_alert(s, "critical", "disruption", "station", st["id"], f"{names[st['id']]} {st.get('status')}",
                              "station cannot serve demand or receive shipments"))
    for d in s.depots:
        if d.get("status") not in ("OPEN", "CONSTRAINED"):
            out.append(_alert(s, "critical", "disruption", "depot", d["id"], f"{d.get('name', d['id'])} {d.get('status')}",
                              "depot cannot dispatch"))
    for a in s.supply_arrivals:
        if a.get("status") == "DELAYED":
            out.append(_alert(s, "warning", "disruption", "supply", a["id"],
                              f"Supply {a['id']} to {a.get('depot_id')} delayed",
                              f"{a.get('quantity', 0):.0f} L {a.get('fuel_type', '').lower()} now due tick {a.get('planned_tick')}",
                              a.get("fuel_type")))
    return out


def _confidence(s: Snapshot, fc: list[Forecast], names: dict) -> list[AlertDraft]:
    return [_alert(s, "info", "low_confidence", "station", f.station_id,
                   f"Low forecast confidence for {f.fuel_type.lower()} at {names[f.station_id]}",
                   f"recent MAPE {f.mape_recent:.0%}", f.fuel_type)
            for f in fc if f.mape_recent is not None and f.mape_recent > LOW_CONFIDENCE_MAPE]


def detect(s: Snapshot, fc: list[Forecast], prev: Snapshot | None) -> list[AlertDraft]:
    names = {st["id"]: st.get("name", st["id"]) for st in s.stations}
    alerts: list[AlertDraft] = []
    for part in (lambda: _shortage(s, fc, names), lambda: _demand(s, fc, names), lambda: _inventory(s, prev, names),
                 lambda: _bottlenecks(s, fc), lambda: _disruptions(s, names), lambda: _confidence(s, fc, names)):
        try:  # one broken detector must not hide the others
            alerts.extend(part())
        except Exception:
            continue
    seen, out = set(), []
    for a in alerts:
        if a.key not in seen:
            seen.add(a.key)
            out.append(a)
    return out
