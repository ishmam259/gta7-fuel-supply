"""Named, reproducible crisis and fault presets (scenario configuration, brief §20).

Events are defined relative to the current tick (`offset`), so a preset can be replayed at any point.
The simulator is deterministic: same seed + same actions + same injected events -> same outcome.
"""

SCENARIOS: dict[str, dict] = {
    "demand_spike_dhaka": {
        "title": "Demand spike in Dhaka",
        "description": "Dhaka Division demand x1.8 for 6 hours (Mirpur, Tongi).",
        "events": [{"type": "demand_spike", "offset": 1, "duration_ticks": 24,
                    "parameters": {"region_ids": ["region-dhaka"], "multiplier": 1.8}}],
    },
    "route_disruption_mirpur": {
        "title": "Gazipur -> Mirpur route disrupted",
        "description": "Primary Mirpur route down for 4 hours; backup route Patiya -> Mirpur must be used.",
        "events": [{"type": "route_disruption", "offset": 1, "duration_ticks": 16,
                    "parameters": {"route_ids": ["route-gazipur-mirpur"]}}],
    },
    "depot_constraint_gazipur": {
        "title": "Gazipur depot constrained",
        "description": "Gazipur depot CONSTRAINED for 4 hours.",
        "events": [{"type": "depot_constraint", "offset": 1, "duration_ticks": 16,
                    "parameters": {"depot_ids": ["depot-gazipur"]}}],
    },
    "shipment_delay": {
        "title": "Incoming supply delayed",
        "description": "All scheduled depot supply arrivals delayed by 8 ticks (2 hours).",
        "events": [{"type": "shipment_delay", "offset": 1, "duration_ticks": 1,
                    "parameters": {"delay_ticks": 8}}],
    },
    "supply_shortfall_patiya": {
        "title": "Supply shortfall at Patiya",
        "description": "Patiya's upcoming supply arrivals cut to 40%.",
        "events": [{"type": "supply_shortfall", "offset": 1, "duration_ticks": 1,
                    "parameters": {"factor": 0.4, "depot_ids": ["depot-patiya"]}}],
    },
    "station_outage_tongi": {
        "title": "Tongi station outage",
        "description": "Tongi Industrial Station offline for 3 hours.",
        "events": [{"type": "station_outage", "offset": 1, "duration_ticks": 12,
                    "parameters": {"station_ids": ["station-tongi"]}}],
    },
    "combined_crisis": {
        "title": "Combined crisis",
        "description": "Dhaka demand spike + Gazipur->Mirpur route down + delayed supply + Patiya constrained.",
        "events": [
            {"type": "demand_spike", "offset": 1, "duration_ticks": 32,
             "parameters": {"region_ids": ["region-dhaka"], "multiplier": 1.6}},
            {"type": "route_disruption", "offset": 4, "duration_ticks": 16,
             "parameters": {"route_ids": ["route-gazipur-mirpur"]}},
            {"type": "shipment_delay", "offset": 2, "duration_ticks": 1, "parameters": {"delay_ticks": 6}},
            {"type": "depot_constraint", "offset": 8, "duration_ticks": 16,
             "parameters": {"depot_ids": ["depot-patiya"]}},
        ],
    },
}

FAULTS: dict[str, dict] = {
    "api_errors": {"title": "30% API errors (60 s)", "body": {"type": "error_rate", "duration_seconds": 60,
                                                              "parameters": {"rate": 0.3}}},
    "api_down": {"title": "Simulator API down (30 s)", "body": {"type": "unavailable", "duration_seconds": 30}},
    "slow_api": {"title": "Slow API, 1.5 s latency (60 s)", "body": {"type": "latency", "duration_seconds": 60,
                                                                     "parameters": {"delay_ms": 1500}}},
    "stale_data": {"title": "Stale data (60 s)", "body": {"type": "stale_data", "duration_seconds": 60}},
    "stream_cut": {"title": "Event stream disconnect (60 s)", "body": {"type": "stream_disconnect",
                                                                       "duration_seconds": 60}},
}


def events_for(name: str, current_tick: int) -> list[dict]:
    """Simulator /admin/events bodies for a preset, anchored at the current tick."""
    preset = SCENARIOS[name]
    return [{"type": e["type"], "start_tick": current_tick + e["offset"], "duration_ticks": e["duration_ticks"],
             "parameters": e.get("parameters", {})} for e in preset["events"]]
