"""Demand forecast per (station, fuel). v1: recent mean ± std (hour-of-day profile comes next)."""
import statistics

from .models import Forecast, Snapshot

FUELS = ("DIESEL", "PETROL", "OCTANE")
DEFAULT_DEMAND = 50.0  # L/tick when there is no history yet
WINDOW = 16


def _series(s: Snapshot, station_id: str, fuel: str) -> list[float]:
    rows = [r for r in s.demand_history if r.get("station_id") == station_id and r.get("fuel_type") == fuel]
    rows.sort(key=lambda r: r.get("tick", 0))
    return [float(r.get("demand_liters", 0.0)) for r in rows]


def forecast(s: Snapshot, horizon: int = 16) -> list[Forecast]:
    out = []
    for st in s.stations:
        for fuel in FUELS:
            hist = _series(s, st["id"], fuel)[-WINDOW:]
            mean = statistics.fmean(hist) if hist else DEFAULT_DEMAND
            std = statistics.pstdev(hist) if len(hist) > 1 else mean * 0.2
            mape = statistics.fmean(abs(x - mean) / x for x in hist if x > 0) if hist else None
            out.append(Forecast(
                station_id=st["id"], fuel_type=fuel, horizon_ticks=horizon,
                per_tick=[mean] * horizon,
                lower=[max(0.0, mean - 1.28 * std)] * horizon,
                upper=[mean + 1.28 * std] * horizon,
                mape_recent=mape, residual_std=std,
            ))
    return out
