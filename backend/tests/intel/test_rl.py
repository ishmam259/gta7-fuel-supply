import json
from pathlib import Path

import pytest

import app.intel.rl as rl
from app.intel import rl_env as E
from app.intel.forecast import forecast
from app.intel.models import Snapshot
from app.intel.planner import plan, violations
from app.intel.risk import assess_risk

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


def test_trained_policy_is_shipped_and_sensible():
    qt = rl.QTable.load()
    assert qt is not None and len(qt.q) >= 20
    assert all(qt.best(tuple(map(int, k.split(",")))) in E.ACTIONS for k in qt.q)


@pytest.mark.parametrize("name", ["snapshot_live_now", "snapshot_tick24", "snapshot_tick200"])
def test_rl_plan_is_legal_and_explained(name):
    s = Snapshot(**load(name))
    fc = forecast(s)
    recs = rl.rl_plan(s, fc, assess_risk(s, fc))
    assert recs and violations(s, recs) == []
    assert all(r.mode == "rl" and any(sig.startswith("RL ") for sig in r.signals) for r in recs)


def test_rl_plan_falls_back_to_lp_without_policy(monkeypatch):
    monkeypatch.setattr(rl, "policy_table", lambda: None)
    s = Snapshot(**load("snapshot_tick24"))
    fc = forecast(s)
    risks = assess_risk(s, fc)
    assert [r.model_dump() for r in rl.rl_plan(s, fc, risks)] == [r.model_dump() for r in plan(s, fc, risks)]


def test_training_world_is_deterministic():
    s = load("snapshot_tick24")
    a, _ = E.run_episode(s, lambda st, r: 24, seed=7, ticks=96)
    b, _ = E.run_episode(s, lambda st, r: 24, seed=7, ticks=96)
    assert (a.served, a.lost, a.trucks_sent) == (b.served, b.lost, b.trucks_sent)


def test_rl_matches_lp_service_with_fewer_trucks():
    """Held-out seeds: same service level as the fixed-24 h LP rule, fewer trucks. No action collapses."""
    s = load("snapshot_tick24")
    qt = rl.QTable.load()
    res = rl.evaluate(s, {"none": lambda st, r: None, "lp": lambda st, r: 24, "rl": lambda st, r: qt.best(st)},
                      range(90000, 90010), ticks=384)
    assert res["none"]["service_level"] < 0.5
    assert res["rl"]["service_level"] >= res["lp"]["service_level"] - 0.002
    assert res["rl"]["trucks_per_episode"] < res["lp"]["trucks_per_episode"]
