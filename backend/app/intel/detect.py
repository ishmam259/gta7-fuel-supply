"""Alert detection: shortage risk, anomalous demand, disruptions."""
from .models import AlertDraft, AlertEntity, Forecast, Snapshot
from .risk import assess_risk

Z_ANOMALY = 3.0


def detect(s: Snapshot, fc: list[Forecast], prev: Snapshot | None) -> list[AlertDraft]:
    alerts: list[AlertDraft] = []
    names = {st["id"]: st.get("name", st["id"]) for st in s.stations}

    for r in assess_risk(s, fc):
        if r.level == "ok":
            continue
        sev = "warning" if r.level == "watch" else "critical"
        alerts.append(AlertDraft(
            tick=s.tick, severity=sev, kind="shortage_risk",
            entity=AlertEntity(type="station", id=r.station_id, fuel_type=r.fuel_type),
            title=f"{r.fuel_type.title()} stockout in {r.stockout_hours} h at {names[r.station_id]}",
            detail=f"risk {r.level}, p={r.stockout_prob:.2f}, inventory {r.current_inventory:.0f} L",
        ))

    last_tick = max((h.get("tick", 0) for h in s.demand_history), default=None)
    by_key = {(f.station_id, f.fuel_type): f for f in fc}
    for h in s.demand_history:
        if h.get("tick") != last_tick:
            continue
        f = by_key.get((h.get("station_id"), h.get("fuel_type")))
        if not f or f.residual_std <= 0:
            continue
        z = (float(h.get("demand_liters", 0)) - f.per_tick[0]) / f.residual_std
        if z >= Z_ANOMALY:
            alerts.append(AlertDraft(
                tick=s.tick, severity="warning", kind="anomalous_demand",
                entity=AlertEntity(type="station", id=f.station_id, fuel_type=f.fuel_type),
                title=f"Abnormal {f.fuel_type.lower()} demand at {names.get(f.station_id, f.station_id)}",
                detail=f"z={z:.1f}",
            ))

    for ev in s.events:
        if ev.get("status") == "ACTIVE":
            alerts.append(AlertDraft(
                tick=s.tick, severity="warning", kind="disruption",
                entity=AlertEntity(type="system", id=str(ev.get("id"))),
                title=f"Active event: {ev.get('type')}", detail=str(ev.get("parameters", {})),
            ))
    for r in s.routes:
        if r.get("status") != "AVAILABLE":
            alerts.append(AlertDraft(
                tick=s.tick, severity="warning", kind="disruption",
                entity=AlertEntity(type="route", id=r["id"]), title=f"Route {r['id']} {r.get('status')}",
            ))
    for kind, items in (("depot", s.depots), ("station", s.stations)):
        for e in items:
            if e.get("status") != "OPEN":
                alerts.append(AlertDraft(
                    tick=s.tick, severity="critical", kind="disruption",
                    entity=AlertEntity(type=kind, id=e["id"]), title=f"{e.get('name', e['id'])} {e.get('status')}",
                ))
    for a in s.supply_arrivals:
        if a.get("status") == "DELAYED":
            alerts.append(AlertDraft(
                tick=s.tick, severity="warning", kind="disruption",
                entity=AlertEntity(type="supply", id=a["id"], fuel_type=a.get("fuel_type")),
                title=f"Supply {a['id']} to {a.get('depot_id')} delayed",
            ))
    return alerts
