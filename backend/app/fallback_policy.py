"""Rule-based fallback policy (brief §11: "ML model unavailable -> fallback allocation policy").

Used when the intelligence module (app.intel) is missing or raises. Works on the raw snapshot dict.
Deliberately simple and explainable: moving-average demand, reorder at 50% of capacity, refill to 90%.
"""
import math
from collections import defaultdict

FUELS = ("DIESEL", "PETROL", "OCTANE")
# litres per simulated day (guide §8.5), used when there is no demand history yet
PROFILE_DAILY = {
    "urban_high": {"DIESEL": 8500, "PETROL": 10500, "OCTANE": 5600},
    "industrial": {"DIESEL": 14000, "PETROL": 4500, "OCTANE": 2200},
    "highway": {"DIESEL": 10500, "PETROL": 11000, "OCTANE": 6200},
    "regional": {"DIESEL": 7200, "PETROL": 7600, "OCTANE": 3600},
}
ACTIVE = ("PENDING", "IN_TRANSIT")


def demand_rate(snap: dict) -> dict[tuple[str, str], float]:
    """Litres per tick for each (station, fuel): mean of the last 8 observed ticks, else profile."""
    ticks_per_day = 24 * 60 / snap["tick_minutes"]
    by_pair: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    for row in snap.get("demand_history", []):
        by_pair[(row["station_id"], row["fuel_type"])].append((row["tick"], row["demand_liters"]))
    rates = {}
    for st in snap["stations"]:
        for f in FUELS:
            rows = sorted(by_pair.get((st["id"], f), []))[-8:]
            if rows:
                rates[(st["id"], f)] = sum(v for _, v in rows) / len(rows)
            else:
                base = PROFILE_DAILY.get(st["demand_profile"], PROFILE_DAILY["regional"])[f]
                rates[(st["id"], f)] = base / ticks_per_day * st.get("demand_multiplier", 1.0)
    return rates


def in_transit(snap: dict) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = defaultdict(float)
    for a in snap.get("allocations", []):
        if a["status"] in ACTIVE:
            out[(a["destination_station_id"], a["fuel_type"])] += a["quantity"]
    return out


def _prob(hours: float, lead_hours: float) -> float:
    # smooth probability of running out before a shipment can land
    return round(1 / (1 + math.exp((hours - lead_hours * 1.5) / max(lead_hours * 0.5, 0.5))), 3)


def assess(snap: dict) -> dict[str, dict[str, dict]]:
    tph = 60 / snap["tick_minutes"]
    rates, transit = demand_rate(snap), in_transit(snap)
    risks: dict[str, dict[str, dict]] = {}
    for st in snap["stations"]:
        risks[st["id"]] = {}
        for f in FUELS:
            rate = max(rates[(st["id"], f)], 1e-6)
            hours = (st["inventory"][f] + transit[(st["id"], f)]) / rate / tph
            prob = _prob(hours, lead_hours=3.0)
            if st["status"] != "OPEN":
                level = "outage"
            elif hours < 4:
                level = "critical"
            elif hours < 10:
                level = "watch"
            else:
                level = "ok"
            risks[st["id"]][f] = {"level": level, "stockout_hours": round(hours, 1), "stockout_prob": prob}
    return risks


def plan(snap: dict, risks: dict) -> list[dict]:
    tph = 60 / snap["tick_minutes"]
    rates, transit = demand_rate(snap), in_transit(snap)
    depots = {d["id"]: d for d in snap["depots"]}
    depot_left = {d["id"]: dict(d["inventory"]) for d in snap["depots"]}
    dispatch_left = {d["id"]: d["dispatch_capacity_per_tick"] for d in snap["depots"]}
    for a in snap.get("allocations", []):
        if a["status"] == "PENDING" and a["source_depot_id"] in dispatch_left:
            dispatch_left[a["source_depot_id"]] -= a["quantity"]

    pairs = []
    for st in snap["stations"]:
        if st["status"] != "OPEN":
            continue
        for f in FUELS:
            level = st["inventory"][f] + transit[(st["id"], f)]
            if level < 0.5 * st["capacity"][f]:
                pairs.append((risks[st["id"]][f]["stockout_prob"], st, f, level))
    pairs.sort(key=lambda p: -p[0])

    recs = []
    for prob, st, f, level in pairs:
        routes = sorted((r for r in snap["routes"] if r["destination_station_id"] == st["id"]
                         and r["status"] == "AVAILABLE"
                         and depots.get(r["source_depot_id"], {}).get("status") in ("OPEN", "CONSTRAINED")),
                        key=lambda r: r["transit_ticks"])
        need = 0.9 * st["capacity"][f] - level
        options = []
        for r in routes:
            d = r["source_depot_id"]
            qty = min(need, r["max_shipment"], depot_left[d][f] * 0.9, dispatch_left[d],
                      st["capacity"][f] - st["inventory"][f])
            if qty >= 500:
                options.append((r, round(qty, -1)))
        if not options:
            continue
        r, qty = options[0]
        d = r["source_depot_id"]
        depot_left[d][f] -= qty
        dispatch_left[d] -= qty
        rate = rates[(st["id"], f)]
        after_hours = (level + qty) / max(rate, 1e-6) / tph
        recs.append({
            "station_id": st["id"], "fuel_type": f, "mode": "fallback",
            "allocation": {"source_depot_id": d, "route_id": r["id"], "quantity": qty,
                           "eta_tick": snap["tick"] + 1 + r["transit_ticks"]},
            "situation": {"current_inventory": st["inventory"][f],
                          "expected_demand_next_4h": round(rate * tph * 4, 1),
                          "projected_stockout_hours": risks[st["id"]][f]["stockout_hours"]},
            "expected_impact": {"stockout_prob_before": prob,
                                "stockout_prob_after": _prob(after_hours, 3.0),
                                "unmet_liters_avoided": None},
            "confidence": 0.6, "requires_human_review": True,
            "signals": [f"inventory + in-transit {level:.0f} L < 50% of capacity {st['capacity'][f]:.0f} L"],
            "constraints": [f"route max {r['max_shipment']:.0f} L", f"depot {d} dispatch left {dispatch_left[d] + qty:.0f} L"],
            "alternatives": [{"source_depot_id": o[0]["source_depot_id"], "route_id": o[0]["id"], "quantity": o[1],
                              "eta_tick": snap["tick"] + 1 + o[0]["transit_ticks"]} for o in options[1:]],
            "explanation": (f"Fallback rule policy: {st['name']} {f.lower()} is below half capacity. "
                            f"Ship {qty:.0f} L from {depots[d]['name']} via {r['id']} (arrives ~tick "
                            f"{snap['tick'] + 1 + r['transit_ticks']})."),
        })
    return recs


def detect(snap: dict, risks: dict) -> list[dict]:
    alerts = []
    for st in snap["stations"]:
        for f in FUELS:
            rk = risks[st["id"]][f]
            if rk["level"] in ("critical", "watch"):
                alerts.append({"severity": "critical" if rk["level"] == "critical" else "warning",
                               "kind": "shortage_risk",
                               "entity": {"type": "station", "id": st["id"], "fuel_type": f},
                               "title": f"{f.title()} stockout in {rk['stockout_hours']} h at {st['name']}",
                               "detail": f"stockout probability {rk['stockout_prob']:.0%}"})
        if st["status"] != "OPEN":
            alerts.append({"severity": "critical", "kind": "disruption",
                           "entity": {"type": "station", "id": st["id"]},
                           "title": f"{st['name']} is {st['status']}", "detail": "station outage"})
    for r in snap["routes"]:
        if r["status"] != "AVAILABLE":
            alerts.append({"severity": "warning", "kind": "disruption", "entity": {"type": "route", "id": r["id"]},
                           "title": f"Route {r['id']} {r['status']}", "detail": "use alternative routes"})
    for d in snap["depots"]:
        if d["status"] != "OPEN":
            alerts.append({"severity": "warning", "kind": "bottleneck", "entity": {"type": "depot", "id": d["id"]},
                           "title": f"{d['name']} {d['status']}", "detail": "reduced depot capacity"})
    for s in snap.get("supply_arrivals", []):
        if s["status"] == "DELAYED":
            alerts.append({"severity": "warning", "kind": "disruption",
                           "entity": {"type": "supply", "id": s["id"], "fuel_type": s["fuel_type"]},
                           "title": f"Supply {s['id']} to {s['depot_id']} delayed",
                           "detail": f"{s['quantity']:.0f} L {s['fuel_type']} now planned for tick {s['planned_tick']}"})
    return alerts
