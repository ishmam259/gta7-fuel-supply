"""The LLM chain must never keep the operator waiting longer than LLM_BUDGET_S (4 s), whatever the providers do.

Offline (fake providers, no network): hangs, slow failures, slow bad JSON, slow chains, parallel load,
all four genai functions, the real 4.0 s budget. Live stress (real APIs) runs only with LIVE_LLM=1.
"""
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.intel import genai
from app.intel.forecast import forecast
from app.intel.models import Snapshot
from app.intel.planner import plan
from app.intel.risk import assess_risk

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_live_now.json"
BUDGET = genai.LLM_BUDGET_S          # the real value (4.0)
SLACK = 0.35                         # thread hand-off + template rendering + slow CI machines
# the briefing refreshes in the background, so it has a longer budget than the interactive calls
LIMIT = {"explain_recommendation": BUDGET, "explain_incident": BUDGET, "answer": BUDGET,
         "briefing": genai.BRIEFING_BUDGET_S}


@pytest.fixture
def s() -> Snapshot:
    return Snapshot(**json.loads(FIXTURE.read_text()))


@pytest.fixture
def rec(s) -> dict:
    fc = forecast(s)
    return {"id": 1, "status": "pending", **plan(s, fc, assess_risk(s, fc))[0].model_dump(mode="json")}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    genai._cache.clear()
    genai._down_until.clear()
    yield
    genai._cache.clear()
    genai._down_until.clear()


def chain(monkeypatch, *fns):
    monkeypatch.setattr(genai, "_chain", lambda cfg: [(f"p{i}:m", lambda c, m, sy, u, j, fn=fn: fn()) for i, fn in enumerate(fns)])


def hang(seconds):
    return lambda: time.sleep(seconds) or '{"summary": "late", "answer": "late", "evidence": []}'


def slow_fail(seconds):
    def f():
        time.sleep(seconds)
        raise ConnectionError("upstream reset")
    return f


def calls(s, rec):
    alert = {"id": 3, "title": "Route down", "detail": "", "entity": {"type": "route", "id": "route-gazipur-mirpur"}}
    return {
        "explain_recommendation": lambda q="": genai.explain_recommendation({**rec, "note": q}, s),
        "explain_incident": lambda q="": genai.explain_incident({**alert, "detail": q}, s),
        "briefing": lambda q="": genai.briefing(s, [], [{"id": 1, "title": q}]),
        "answer": lambda q="": genai.answer(f"why? {q}", s, [alert], [rec]),
    }


def timed(fn):
    t = time.monotonic()
    out = fn()
    return time.monotonic() - t, out


# ---------------- every failure shape, every function, real 4.0 s budget ----------------
SCENARIOS = {
    "hangs forever":                  [hang(30)],
    "hangs, then a fast one":         [hang(30), lambda: '{"summary": "ok", "answer": "ok", "evidence": []}'],
    "three slow providers (2 s each)": [hang(2), hang(2), hang(2)],
    "slow failure then hang":         [slow_fail(2.5), hang(30)],
    "slow invalid JSON then hang":    [lambda: time.sleep(2.5) or "not json {", hang(30)],
}


@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("fn_name", ["explain_recommendation", "explain_incident", "briefing", "answer"])
def test_every_function_respects_budget(monkeypatch, s, rec, scenario, fn_name):
    chain(monkeypatch, *SCENARIOS[scenario])
    dt, out = timed(calls(s, rec)[fn_name])
    assert dt <= LIMIT[fn_name] + SLACK, f"{fn_name} / {scenario}: {dt:.2f} s"
    src = out[1] if isinstance(out, tuple) else out["source"]
    assert src in ("llm", "template")


def test_fast_provider_after_a_hang_is_used_if_time_remains(monkeypatch, s, rec):
    """First provider fails fast, second answers: the LLM answer wins, well under budget."""
    chain(monkeypatch, slow_fail(0.2), lambda: "Fast answer.")
    dt, (text, src) = timed(calls(s, rec)["explain_recommendation"])
    assert (text, src) == ("Fast answer.", "llm") and dt < 1.0


def test_budget_is_total_not_per_provider(monkeypatch, s, rec):
    """Three providers that each fail after 1.5 s would take 4.5 s if the budget were per provider."""
    chain(monkeypatch, slow_fail(1.5), slow_fail(1.5), slow_fail(1.5))
    dt, (_, src) = timed(calls(s, rec)["explain_recommendation"])
    assert src == "template" and dt <= BUDGET + SLACK


# ---------------- parallel load ----------------
def test_parallel_calls_each_within_budget(monkeypatch, s, rec):
    """20 simultaneous calls against a hanging provider (more than the worker pool): nobody waits > budget."""
    chain(monkeypatch, hang(30))
    fns = calls(s, rec)
    jobs = [(name, f"q{i}") for i in range(5) for name in fns]      # distinct prompts: no cache help
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        durations = list(ex.map(lambda j: (j[0], timed(lambda: fns[j[0]](j[1]))[0]), jobs))
    over = [(n, round(d, 2)) for n, d in durations if d > LIMIT[n] + SLACK]
    assert not over, f"over budget: {over}"


def test_abandoned_slow_calls_do_not_starve_later_calls(monkeypatch, s, rec):
    """After a burst of hung calls, a healthy provider must still answer quickly (workers not exhausted)."""
    chain(monkeypatch, hang(5))
    fns = calls(s, rec)
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda i: fns["answer"](f"burst {i}"), range(8)))
    genai._down_until.clear()
    chain(monkeypatch, lambda: '{"answer": "fresh", "evidence": []}')
    dt, out = timed(lambda: fns["answer"]("after burst"))
    assert out["source"] == "llm" and dt < 1.0, f"{dt:.2f} s, {out['source']}"


def test_cooldown_skips_slow_provider_next_time(monkeypatch, s, rec):
    """A provider that blew the budget is skipped for a while, so the next call goes straight to the next one."""
    chain(monkeypatch, hang(30), lambda: "second provider")
    timed(calls(s, rec)["explain_recommendation"])                  # p0 times out -> cooldown
    dt, (text, src) = timed(lambda: calls(s, rec)["explain_recommendation"]("again"))
    assert (text, src) == ("second provider", "llm") and dt < 0.5


# ---------------- live stress (real APIs) ----------------
live = pytest.mark.skipif(os.getenv("LIVE_LLM") != "1", reason="set LIVE_LLM=1 to hit the real providers")


@live
@pytest.mark.parametrize("only", [None, "openai", "gemini", "groq"])
def test_live_latency_stays_under_budget(monkeypatch, s, rec, only):
    cfg = genai._cfg()
    if only:
        keep = {"openai": "openai_api_key", "gemini": "gemini_api_key", "groq": "groq_api_key"}[only]
        if not cfg.get(keep):
            pytest.skip(f"no {only} key")
        cfg = {k: (v if not k.endswith("_api_key") or k == keep else "") for k, v in cfg.items()}
        monkeypatch.setattr(genai, "_cfg", lambda: cfg)
    fns = calls(s, rec)
    durations, sources = [], []
    for i in range(6):
        for name, fn in fns.items():
            dt, out = timed(lambda: fn(f"live {only} {i}"))
            durations.append(dt)
            assert dt <= LIMIT[name] + SLACK, f"{name}: {dt:.2f} s"
            sources.append(out[1] if isinstance(out, tuple) else out["source"])
    print(f"\n[{only or 'full chain'}] n={len(durations)} p50={statistics.median(durations):.2f}s "
          f"p95={sorted(durations)[int(0.95 * len(durations)) - 1]:.2f}s max={max(durations):.2f}s "
          f"llm={sources.count('llm')} template={sources.count('template')}")


@live
def test_live_parallel_burst(s, rec):
    fns = calls(s, rec)
    jobs = [(name, f"par {i}") for i in range(4) for name in fns]
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        res = list(ex.map(lambda j: timed(lambda: fns[j[0]](j[1])), jobs))
    durations = [d for d, _ in res]
    assert all(d <= LIMIT[j[0]] + SLACK for j, (d, _) in zip(jobs, res))
    srcs = [o[1] if isinstance(o, tuple) else o["source"] for _, o in res]
    print(f"\n[parallel x{len(jobs)}] max={max(durations):.2f}s llm={srcs.count('llm')} template={srcs.count('template')}")
