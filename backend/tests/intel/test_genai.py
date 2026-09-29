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


# ---- readable output + status ----
def test_clean_strips_markdown_and_limits_length():
    assert genai._clean("**Send** 500 L\n\n# now") == "Send 500 L now"
    out = genai._clean("First sentence. " * 100, 60)
    assert len(out) <= 60 and out.endswith(".")


def test_clock_shows_arrival_time(s):
    assert genai._clock(s, s.tick + 2) == "06:30 (in 30 min)"   # fixture sim_time is 06:00
    assert genai._clock(s, s.tick) == "06:00 (now)"


def test_recommendation_template_is_readable(rec, s):
    text, _ = genai.explain_recommendation(rec, s)
    assert "Tongi Industrial Station" in text and "06:30" in text and "lost sales" in text


def test_briefing_template_mentions_service_level(s):
    s.metrics = {"service_level": 0.943, "unmet_demand_liters": 1200}
    assert "service level 94%" in genai.briefing(s, [], [])["summary"]


def test_prompts_carry_risk_table_and_route_alternatives(monkeypatch, s):
    seen = []
    monkeypatch.setattr(genai, "_chain", lambda cfg: [("p:m", lambda c, m, sy, u, j: seen.append(u) or '{"answer": "x", "evidence": []}')])
    genai.answer("which station is most at risk?", s, [], [])
    assert "stations_at_risk" in seen[-1] and "Tongi Industrial Station" in seen[-1]
    genai.explain_incident({"title": "Route down", "entity": {"type": "route", "id": "route-gazipur-mirpur"}}, s)
    assert "route-patiya-mirpur" in seen[-1]          # the other route to Mirpur is offered


def test_known_cause_is_matched_in_code(s):
    s.events = [{"id": 3, "type": "demand_spike", "start_tick": 20, "end_tick": 40, "status": "ACTIVE",
                 "parameters": {"region_ids": ["region-dhaka"]}},
                {"id": 4, "type": "route_disruption", "start_tick": 22, "end_tick": 34, "status": "ACTIVE",
                 "parameters": {"route_ids": ["route-gazipur-mirpur"]}}]
    route = genai._known_cause(s, {"entity": {"type": "route", "id": "route-gazipur-mirpur"}})
    assert len(route) == 1 and route[0].startswith("route_disruption")          # not the demand spike
    station = genai._known_cause(s, {"entity": {"type": "station", "id": "station-mirpur"}})
    assert any(c.startswith("demand_spike") for c in station)                   # via its region
    assert genai._known_cause(s, {"entity": {"type": "station", "id": "station-coxsbazar"}}) == []


def test_llm_output_is_cleaned(monkeypatch, rec, s):
    use_providers(monkeypatch, lambda: "**Send it.**\n\nNow.")
    assert genai.explain_recommendation(rec, s) == ("Send it. Now.", "llm")


def test_llm_status_counts(monkeypatch, rec, s):
    for k in ("calls", "llm_ok", "template", "failures", "cache_hits"):
        genai.stats[k] = 0
    genai.explain_recommendation(rec, s)                      # no keys -> template
    st = genai.llm_status()
    assert st["status"] == "unavailable" and st["template"] == 1 and st["calls"] == 1
    use_providers(monkeypatch, boom, lambda: "ok")
    genai.explain_incident({"title": "t"}, s)
    assert genai.stats["llm_ok"] == 1 and genai.stats["failures"] == 1 and "p0" in genai.stats["last_error"]
