import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.intel.forecast import forecast
from app.intel.models import Snapshot

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_tick200.json"


@pytest.fixture
def raw() -> dict:
    return json.loads(FIXTURE.read_text())


def _at(raw: dict, cut: int) -> Snapshot:
    t0 = datetime.fromisoformat(raw["sim_time"]) - timedelta(minutes=15 * (raw["tick"] - cut))
    past = [r for r in raw["demand_history"] if r["tick"] < cut]
    return Snapshot(**{**raw, "tick": cut, "sim_time": t0, "demand_history": past})


def test_backtest_mape_under_10pct(raw):
    errs = []
    for cut in range(80, 185, 8):
        fut = {(r["station_id"], r["fuel_type"], r["tick"]): r["demand_liters"]
               for r in raw["demand_history"] if cut <= r["tick"] < cut + 16}
        for f in forecast(_at(raw, cut)):
            for i, v in enumerate(f.per_tick):
                a = fut.get((f.station_id, f.fuel_type, cut + i))
                if a:
                    errs.append(abs(v - a) / a)
    assert statistics.fmean(errs) < 0.10


def test_band_and_metrics(raw):
    for f in forecast(Snapshot(**raw)):
        assert all(lo <= mu <= hi for lo, mu, hi in zip(f.lower, f.per_tick, f.upper))
        assert f.mape_recent is not None and f.mape_recent < 0.2
        assert f.residual_std > 0


def test_hour_of_day_shape(raw):
    # industrial diesel: busy 06-18 is 1.55/0.45 of the daily average
    s = _at(raw, 196)  # 01:00 -> forecast spans the night into the morning ramp
    f = next(x for x in forecast(s, horizon=40) if x.station_id == "station-tongi" and x.fuel_type == "DIESEL")
    assert max(f.per_tick) / min(f.per_tick) == pytest.approx(1.55 / 0.45, rel=0.01)


def test_fresh_demand_spike_is_reflected(raw):
    base = {(f.station_id, f.fuel_type): f.per_tick[0] for f in forecast(Snapshot(**raw))}
    for st in raw["stations"]:
        if st["region_id"] == "region-dhaka":
            st["demand_multiplier"] = 1.8
    spiked = forecast(Snapshot(**raw))
    f = next(x for x in spiked if x.station_id == "station-mirpur" and x.fuel_type == "PETROL")
    assert f.per_tick[0] == pytest.approx(1.8 * base[("station-mirpur", "PETROL")], rel=0.05)


def test_spike_just_ended_returns_to_normal(raw):
    base = {(f.station_id, f.fuel_type): f.per_tick[0] for f in forecast(Snapshot(**raw))}
    for r in raw["demand_history"]:
        if r["station_id"] == "station-mirpur":
            r["demand_liters"] *= 1.8  # history was recorded during the spike, multiplier now back to 1.0
    f = next(x for x in forecast(Snapshot(**raw)) if x.station_id == "station-mirpur" and x.fuel_type == "PETROL")
    assert f.per_tick[0] == pytest.approx(base[("station-mirpur", "PETROL")], rel=0.05)


def test_unknown_profile_falls_back(raw):
    raw["stations"][0]["demand_profile"] = "mystery"
    fc = forecast(Snapshot(**raw))
    assert len(fc) == 12 and all(min(f.per_tick) >= 0 for f in fc)


def test_no_history(raw):
    raw["demand_history"] = []
    fc = forecast(Snapshot(**raw))
    assert len(fc) == 12 and all(f.per_tick[0] > 0 for f in fc)
