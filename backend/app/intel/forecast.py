"""Demand forecast per (station, fuel) per tick.

Model (guide §8.5/§8.6): daily_liters/ticks_per_day × hour_factor(hour) × demand_multiplier × region demand_factor.
A per-series scale learned from recent history corrects the prior; residuals give the band and rolling MAPE.
Unknown profiles fall back to the recent mean.
"""
import statistics
from datetime import datetime, timedelta

from .models import Forecast, Snapshot

FUELS = ("DIESEL", "PETROL", "OCTANE")
DEFAULT_DEMAND = 50.0  # L/tick when there is nothing to go on
CALIB_WINDOW = 32      # ticks used for scale + error metrics
SCALE_BOUNDS = (0.5, 2.0)
Z80 = 1.28             # 80% band

DAILY = {  # liters per simulated day
    "urban_high": {"DIESEL": 8500, "PETROL": 10500, "OCTANE": 5600},
    "industrial": {"DIESEL": 14000, "PETROL": 4500, "OCTANE": 2200},
    "highway": {"DIESEL": 10500, "PETROL": 11000, "OCTANE": 6200},
    "regional": {"DIESEL": 7200, "PETROL": 7600, "OCTANE": 3600},
}
BUSY = {  # profile -> (busy hours, busy factor, off-peak factor)
    "industrial": (set(range(6, 18)), 1.55, 0.45),
    "highway": (set(range(6, 10)) | set(range(16, 21)), 1.35, 0.75),
    "urban_high": (set(range(7, 10)) | set(range(16, 21)), 1.45, 0.70),
    "regional": (set(range(7, 21)), 1.25, 0.65),
}


def hour_factor(profile: str, hour: int) -> float:
    busy, hi, lo = BUSY[profile]
    return hi if hour in busy else lo


def prior(profile: str, fuel: str, when: datetime, tick_minutes: int) -> float:
    """Expected liters in one tick at `when` with multiplier and region factor = 1."""
    return DAILY[profile][fuel] * tick_minutes / 1440 * hour_factor(profile, when.hour)


def _parse(t) -> datetime:
    return t if isinstance(t, datetime) else datetime.fromisoformat(str(t))


def _history(s: Snapshot, station_id: str, fuel: str) -> list[dict]:
    rows = [r for r in s.demand_history if r.get("station_id") == station_id and r.get("fuel_type") == fuel]
    rows.sort(key=lambda r: r.get("tick", 0))
    return rows[-CALIB_WINDOW:]


def _model_forecast(s: Snapshot, st: dict, fuel: str, horizon: int, region_factor: float) -> Forecast:
    profile, mult = st["demand_profile"], float(st.get("demand_multiplier", 1.0))
    rows = _history(s, st["id"], fuel)
    base = lambda when: prior(profile, fuel, when, s.tick_minutes) * region_factor

    # scale = observed / prior over recent ticks (absorbs noise bias, events that already ended, scenario drift)
    ratios = [float(r["demand_liters"]) / base(_parse(r["sim_time"])) for r in rows if r.get("sim_time")]
    scale = statistics.median(ratios) if ratios else mult
    scale = min(max(scale, SCALE_BOUNDS[0] * mult), SCALE_BOUNDS[1] * mult)
    # a multiplier change the history window has not caught up with yet (spike started or just ended)
    if ratios and abs(scale - mult) / mult > 0.25:
        scale = mult

    rel_err = [abs(r / scale - 1) for r in ratios]
    rel_std = statistics.pstdev([r / scale for r in ratios]) if len(ratios) > 1 else 0.12
    rel_std = max(rel_std, 0.05)
    mape = statistics.fmean(rel_err) if rel_err else None

    per_tick, lower, upper = [], [], []
    for i in range(horizon):
        mu = base(_parse(s.sim_time) + timedelta(minutes=i * s.tick_minutes)) * scale
        per_tick.append(round(mu, 3))
        lower.append(round(max(0.0, mu * (1 - Z80 * rel_std)), 3))
        upper.append(round(mu * (1 + Z80 * rel_std), 3))
    mean = statistics.fmean(per_tick)
    return Forecast(station_id=st["id"], fuel_type=fuel, horizon_ticks=horizon, per_tick=per_tick,
                    lower=lower, upper=upper, mape_recent=mape, residual_std=round(mean * rel_std, 3))


def _mean_forecast(s: Snapshot, st: dict, fuel: str, horizon: int) -> Forecast:
    hist = [float(r.get("demand_liters", 0.0)) for r in _history(s, st["id"], fuel)]
    mean = statistics.fmean(hist) if hist else DEFAULT_DEMAND
    std = statistics.pstdev(hist) if len(hist) > 1 else mean * 0.2
    mape = statistics.fmean(abs(x - mean) / x for x in hist if x > 0) if any(hist) else None
    return Forecast(station_id=st["id"], fuel_type=fuel, horizon_ticks=horizon, per_tick=[mean] * horizon,
                    lower=[max(0.0, mean - Z80 * std)] * horizon, upper=[mean + Z80 * std] * horizon,
                    mape_recent=mape, residual_std=std)


def forecast(s: Snapshot, horizon: int = 16) -> list[Forecast]:
    regions = {r["id"]: float(r.get("demand_factor", 1.0)) for r in s.regions}
    out = []
    for st in s.stations:
        for fuel in FUELS:
            if st.get("demand_profile") in DAILY:
                out.append(_model_forecast(s, st, fuel, horizon, regions.get(st.get("region_id"), 1.0)))
            else:
                out.append(_mean_forecast(s, st, fuel, horizon))
    return out
