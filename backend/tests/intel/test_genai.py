import json
from pathlib import Path

import pytest

from app.intel import genai
from app.intel.forecast import forecast
from app.intel.models import Snapshot
from app.intel.planner import plan
from app.intel.risk import assess_risk

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_tick24.json"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    genai._cache.clear()
    genai._down_until.clear()
    monkeypatch.setattr(genai, "_cfg", lambda: {k: "" for k in genai.FIELDS})  # no keys unless a test adds them


@pytest.fixture
def s() -> Snapshot:
    return Snapshot(**json.loads(FIXTURE.read_text()))


@pytest.fixture
def rec(s) -> dict:
    fc = forecast(s)
    r = plan(s, fc, assess_risk(s, fc))[0]
    return {"id": 21, "status": "pending", **r.model_dump(mode="json")}  # what the backend passes


def use_providers(monkeypatch, *fns):
    monkeypatch.setattr(genai, "_chain", lambda cfg: [(f"p{i}:m", lambda c, m, sy, u, j, fn=fn: fn()) for i, fn in enumerate(fns)])


def boom():
    raise TimeoutError("down")


# ---- dict inputs + templates (no keys) ----
def test_explain_recommendation_accepts_dict(rec, s):
    text, src = genai.explain_recommendation(rec, s)
    assert src == "template" and "Tongi" in text and "99%" in text


def test_explain_recommendation_accepts_model(s):
    fc = forecast(s)
    text, src = genai.explain_recommendation(plan(s, fc, assess_risk(s, fc))[0], s)
    assert src == "template" and text


def test_explain_incident_dict(s):
    alert = {"id": 9, "severity": "critical", "kind": "disruption", "title": "Route X DISRUPTED", "detail": "no alternative",
             "entity": {"type": "route", "id": "route-gazipur-tongi", "fuel_type": None}}
    assert genai.explain_incident(alert, s) == ("Route X DISRUPTED. no alternative", "template")


def test_briefing_with_dict_risks(s):
    risks = [{"station_id": "station-tongi", "fuel_type": "DIESEL", "level": "watch", "stockout_hours": 10.7, "stockout_prob": 0.99}]
    b = genai.briefing(s, risks, [{"id": 1, "severity": "warning", "title": "t"}])
    assert b["source"] == "template" and b["tick"] == s.tick and "Tongi" in b["top_risks"][0]


def test_answer_template_filters_evidence(s):
    alerts = [{"id": 3, "title": "Diesel stockout at Tongi", "detail": ""}, {"id": 4, "title": "Route closed", "detail": ""}]
    out = genai.answer("why is tongi at risk?", s, alerts, [])
    assert out["source"] == "template" and out["evidence"] == ["alert:3"]


# ---- provider chain ----
def test_first_provider_wins(monkeypatch, rec, s):
    calls = []
    use_providers(monkeypatch, lambda: calls.append(1) or "from openai", lambda: calls.append(2) or "from gemini")
    assert genai.explain_recommendation(rec, s) == ("from openai", "llm") and calls == [1]


def test_falls_through_to_next_provider_then_cools_down(monkeypatch, rec, s):
    calls = []
    def flaky():
        calls.append("openai")
        raise TimeoutError
    use_providers(monkeypatch, flaky, boom, lambda: "from groq")
    assert genai.explain_recommendation(rec, s) == ("from groq", "llm")
    genai._cache.clear()
    genai.explain_recommendation(rec, s)
    assert calls == ["openai"]  # skipped during cooldown


def test_all_providers_down_uses_template(monkeypatch, rec, s):
    use_providers(monkeypatch, boom, boom, boom)
    assert genai.explain_recommendation(rec, s)[1] == "template"


def test_cache_avoids_repeat_calls(monkeypatch, rec, s):
    calls = []
    use_providers(monkeypatch, lambda: calls.append(1) or "x")
    genai.explain_recommendation(rec, s)
    genai.explain_recommendation(rec, s)
    assert calls == [1]


def test_briefing_llm_json_and_bad_json(monkeypatch, s):
    use_providers(monkeypatch, lambda: json.dumps({"summary": "All calm.", "top_risks": [], "recommended_actions": ["watch"]}))
    assert genai.briefing(s, [], [])["source"] == "llm"
    genai._cache.clear()
    use_providers(monkeypatch, lambda: "not json")
    assert genai.briefing(s, [], [])["source"] == "template"


def test_answer_drops_invented_evidence(monkeypatch, s):
    use_providers(monkeypatch, lambda: json.dumps({"answer": "Because demand spiked.", "evidence": ["alert:3", "alert:999"]}))
    out = genai.answer("why?", s, [{"id": 3, "title": "spike"}], [])
    assert out == {"answer": "Because demand spiked.", "evidence": ["alert:3"], "source": "llm"}


def test_chain_order_and_models():
    cfg = {k: "" for k in genai.FIELDS} | {"openai_api_key": "a", "openai_model": "gpt-x", "gemini_api_key": "b",
                                          "gemini_model": "g1", "gemini_model_chain": "g2, g1,g3", "groq_api_key": "c",
                                          "groq_model_primary": "q1", "groq_model_fallback": "q2"}
    assert [n for n, _ in genai._chain(cfg)] == ["openai:gpt-x", "gemini:g1", "gemini:g2", "gemini:g3", "groq:q1", "groq:q2"]
    cfg["openai_api_key"] = ""
    assert genai._chain(cfg)[0][0] == "gemini:g1"


def test_json_wrapped_in_fences_and_think(monkeypatch, s):
    reply = '<think>hmm</think>```json\n{"summary": "ok", "top_risks": [], "recommended_actions": []}\n```'
    use_providers(monkeypatch, lambda: reply)
    assert genai.briefing(s, [], [])["source"] == "llm"
