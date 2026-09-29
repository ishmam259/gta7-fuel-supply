"""Operator-facing text: explanations, briefing, investigation assistant.

The LLM only explains facts computed by deterministic code; it never decides quantities.
Provider chain: OpenAI -> Gemini -> Groq -> template. Every function returns source "llm" or "template".
Inputs may be Pydantic models or plain dicts (the backend passes dicts).
"""
import hashlib
import json
import logging
import os
import re
import time
from typing import Any

log = logging.getLogger("gta7.intel.genai")

TIMEOUT_S = 8.0
GEMINI_TIMEOUT_MS = 12_000  # Gemini rejects deadlines under 10 s
COOLDOWN_S = 60.0          # skip a provider for this long after it fails
CACHE_MAX = 256
SYSTEM = (
    "You are the operations assistant of a fuel supply control room (simulated network in Bangladesh). "
    "Use ONLY the facts in the JSON you are given. Never invent numbers, stations, routes or events. "
    "Quantities and decisions come from the optimizer; you explain them. Be concise and concrete, "
    "plain text, no markdown headings."
)

_cache: dict[str, str] = {}
_down_until: dict[str, float] = {}
last_provider: dict[str, str] = {"name": ""}  # for status/metrics


def _json_block(text: str) -> str:
    """Some models wrap JSON in ```json fences or add reasoning before it."""
    if "{" in text and "}" in text:
        return text[text.index("{"): text.rindex("}") + 1]
    return text


# ---------------- config / helpers ----------------
FIELDS = ("openai_api_key", "openai_model", "gemini_api_key", "gemini_model", "gemini_model_chain",
          "groq_api_key", "groq_model_primary", "groq_model_fallback", "groq_tls_insecure")


def _cfg() -> dict[str, str]:
    """.env (repo root or backend/) overridden by real environment variables; later duplicate lines win."""
    vals: dict[str, str] = {}
    try:
        from dotenv import dotenv_values
        for path in ("../.env", ".env", os.path.join(os.path.dirname(__file__), "../../../.env")):
            if os.path.exists(path):
                vals.update({k.lower(): v or "" for k, v in dotenv_values(path).items()})
    except Exception:
        pass
    vals.update({k.lower(): v for k, v in os.environ.items() if k.lower() in FIELDS})
    return {k: vals.get(k, "") for k in FIELDS}


def _models(*names: str) -> list[str]:
    out: list[str] = []
    for n in names:
        out += [m.strip() for m in (n or "").split(",") if m.strip() and m.strip() not in out]
    return out


def _d(x: Any) -> Any:
    if hasattr(x, "model_dump"):
        return x.model_dump(mode="json")
    if isinstance(x, list):
        return [_d(i) for i in x]
    return x


def _g(obj: Any, *path: str, default: Any = None) -> Any:
    cur = _d(obj)
    for p in path:
        if not isinstance(cur, dict) or p not in cur or cur[p] is None:
            return default
        cur = cur[p]
    return cur


def _names(s: Any) -> dict[str, str]:
    items = (_g(s, "stations", default=[]) or []) + (_g(s, "depots", default=[]) or [])
    return {e["id"]: e.get("name", e["id"]) for e in items if isinstance(e, dict) and "id" in e}


def _pct(x: Any) -> str:
    try:
        return f"{float(x):.0%}"
    except (TypeError, ValueError):
        return "n/a"


# ---------------- providers ----------------
def _openai(cfg, model, system, user, want_json):
    from openai import OpenAI
    client = OpenAI(api_key=cfg["openai_api_key"], timeout=TIMEOUT_S, max_retries=0)
    kw = {"response_format": {"type": "json_object"}} if want_json else {}
    r = client.chat.completions.create(model=model, temperature=0.2, max_tokens=500,
                                       messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kw)
    return r.choices[0].message.content


def _gemini(cfg, model, system, user, want_json):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=cfg["gemini_api_key"], http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS))
    conf = types.GenerateContentConfig(system_instruction=system, temperature=0.2, max_output_tokens=500,
                                       response_mime_type="application/json" if want_json else None)
    return client.models.generate_content(model=model, contents=user, config=conf).text


def _groq(cfg, model, system, user, want_json):
    from groq import Groq
    kw_client = {}
    if cfg.get("groq_tls_insecure", "").lower() in ("1", "true", "yes"):
        import httpx
        log.warning("GROQ_TLS_INSECURE set: TLS certificate verification disabled for Groq")
        kw_client["http_client"] = httpx.Client(verify=False, timeout=TIMEOUT_S)
    client = Groq(api_key=cfg["groq_api_key"], timeout=TIMEOUT_S, max_retries=0, **kw_client)
    kw = {"response_format": {"type": "json_object"}} if want_json else {}
    r = client.chat.completions.create(model=model, temperature=0.2, max_tokens=500,
                                       messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kw)
    return r.choices[0].message.content


def _chain(cfg: dict) -> list[tuple[str, callable]]:
    """(provider:model, call) in priority order; providers without a key are left out."""
    steps = []
    if cfg.get("openai_api_key"):
        steps += [(f"openai:{m}", _openai) for m in _models(cfg.get("openai_model") or "gpt-4o-mini")]
    if cfg.get("gemini_api_key"):
        steps += [(f"gemini:{m}", _gemini) for m in _models(cfg.get("gemini_model"), cfg.get("gemini_model_chain")) or ["gemini-2.5-flash-lite"]]
    if cfg.get("groq_api_key"):
        steps += [(f"groq:{m}", _groq) for m in _models(cfg.get("groq_model_primary"), cfg.get("groq_model_fallback")) or ["llama-3.1-8b-instant"]]
    return steps


def _llm(user: str, want_json: bool = False) -> str | None:
    """First provider that answers wins; None means use the template."""
    key = hashlib.sha256(f"{want_json}|{user}".encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    cfg = _cfg()
    for name, fn in _chain(cfg):
        if _down_until.get(name, 0) > time.monotonic():
            continue
        try:
            text = (fn(cfg, name.split(":", 1)[1], SYSTEM, user, want_json) or "").strip()
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # reasoning models
            if want_json:
                text = _json_block(text)
                json.loads(text)
            if text:
                if len(_cache) >= CACHE_MAX:
                    _cache.pop(next(iter(_cache)))
                _cache[key] = text
                last_provider["name"] = name
                return text
        except Exception as exc:
            log.warning("llm %s failed: %s", name, str(exc)[:200])
            _down_until[name] = time.monotonic() + COOLDOWN_S
    return None


# ---------------- templates ----------------
def _tpl_recommendation(rec: dict, names: dict) -> str:
    a, sit, imp = rec.get("allocation", {}), rec.get("situation", {}), rec.get("expected_impact", {})
    st = names.get(rec.get("station_id"), rec.get("station_id"))
    text = (f"Send {a.get('quantity', 0):.0f} L of {str(rec.get('fuel_type', '')).lower()} from "
            f"{names.get(a.get('source_depot_id'), a.get('source_depot_id'))} to {st} via {a.get('route_id')} "
            f"(arrives tick {a.get('eta_tick')}). {st} holds {sit.get('current_inventory', 0):.0f} L and is projected to "
            f"run out in {sit.get('projected_stockout_hours', '?')} h. This lowers the 12 h stockout risk from "
            f"{_pct(imp.get('stockout_prob_before'))} to {_pct(imp.get('stockout_prob_after'))}. "
            f"Confidence {_pct(rec.get('confidence'))}.")
    if rec.get("constraints"):
        text += " Limited by: " + "; ".join(rec["constraints"][:3]) + "."
    return text


# ---------------- public API ----------------
def explain_recommendation(rec: Any, s: Any) -> tuple[str, str]:
    rec, names = _d(rec), _names(s)
    template = _tpl_recommendation(rec, names)
    facts = {k: rec.get(k) for k in ("station_id", "fuel_type", "mode", "allocation", "situation", "expected_impact",
                                      "confidence", "signals", "constraints", "alternatives")}
    facts["names"] = {k: v for k, v in names.items() if k in json.dumps(facts)}
    text = _llm("Explain this fuel allocation recommendation to the operator in 2-3 sentences: why it is needed, "
                "why this source/route, and the expected effect on stockout risk. Mention the key constraint if any.\n"
                + json.dumps(facts, default=str))
    return (text, "llm") if text else (template, "template")


def explain_incident(alert: Any, s: Any) -> tuple[str, str]:
    alert = _d(alert)
    template = f"{alert.get('title', 'Incident')}. {alert.get('detail', '')}".strip()
    ent = alert.get("entity") or {}
    context = {"alert": alert, "entity_state": next((e for e in (_g(s, "stations", default=[]) + _g(s, "depots", default=[])
                                                                   + _g(s, "routes", default=[])) if e.get("id") == ent.get("id")), None),
               "active_events": [e for e in _g(s, "events", default=[]) if e.get("status") == "ACTIVE"]}
    text = _llm("Explain this incident to the operator in 2-3 sentences: what is happening, the likely cause "
                "(from the events/state given), and what it affects.\n" + json.dumps(context, default=str))
    return (text, "llm") if text else (template, "template")


def briefing(s: Any, risks: list, alerts: list) -> dict:
    risks, alerts, names = _d(risks) or [], _d(alerts) or [], _names(s)
    tick = _g(s, "tick", default=0)
    top = sorted((r for r in risks if r.get("level") not in (None, "ok")), key=lambda r: -(r.get("stockout_prob") or 0))[:5]
    crit = [a for a in alerts if a.get("severity") == "critical"]
    template = {
        "tick": tick,
        "summary": f"Tick {tick}: {len(top)} station-fuel pairs at risk, {len(alerts)} open alerts ({len(crit)} critical).",
        "top_risks": [f"{names.get(r['station_id'], r['station_id'])} {r['fuel_type']}: {r['level']}, "
                      f"stockout in {r.get('stockout_hours')} h (p={_pct(r.get('stockout_prob'))})" for r in top],
        "recommended_actions": [f"Review resupply for {names.get(r['station_id'], r['station_id'])} {r['fuel_type']}" for r in top[:3]]
                               or ["No action needed; keep monitoring."],
        "source": "template",
    }
    facts = {"tick": tick, "top_risks": top, "alerts": [{k: a.get(k) for k in ("severity", "kind", "title", "detail")} for a in alerts[:15]],
             "names": names}
    text = _llm('Write a control-room situation briefing. Return JSON {"summary": str (2-4 sentences), '
                '"top_risks": [str] (max 5), "recommended_actions": [str] (max 4)}.\n' + json.dumps(facts, default=str), want_json=True)
    if text:
        try:
            out = json.loads(text)
            return {"tick": tick, "summary": str(out["summary"]), "top_risks": [str(x) for x in out.get("top_risks", [])][:5],
                    "recommended_actions": [str(x) for x in out.get("recommended_actions", [])][:4], "source": "llm"}
        except Exception:
            pass
    return template


def answer(question: str, s: Any, alerts: list, recs: list) -> dict:
    alerts, recs = _d(alerts) or [], _d(recs) or []
    ids = {f"alert:{a['id']}" for a in alerts if "id" in a} | {f"recommendation:{r['id']}" for r in recs if "id" in r}
    words = [w for w in question.lower().split() if len(w) > 3]
    hits = [a for a in alerts if any(w in f"{a.get('title', '')} {a.get('detail', '')}".lower() for w in words)] or alerts
    template = {
        "answer": ("AI assistant unavailable. Relevant alerts:\n" + "\n".join(f"- {a.get('title')} ({a.get('detail', '')})" for a in hits[:5]))
                  if hits else "AI assistant unavailable and there are no open alerts.",
        "evidence": [f"alert:{a['id']}" for a in hits[:5] if "id" in a], "source": "template",
    }
    context = {
        "tick": _g(s, "tick"),
        "stations": [{k: st.get(k) for k in ("id", "name", "status", "inventory", "capacity", "demand_multiplier")} for st in _g(s, "stations", default=[])],
        "depots": [{k: d.get(k) for k in ("id", "name", "status", "inventory")} for d in _g(s, "depots", default=[])],
        "routes": [{k: r.get(k) for k in ("id", "status", "transit_ticks", "max_shipment")} for r in _g(s, "routes", default=[])],
        "active_events": [e for e in _g(s, "events", default=[]) if e.get("status") == "ACTIVE"],
        "alerts": [{k: a.get(k) for k in ("id", "severity", "kind", "entity", "title", "detail")} for a in alerts[:20]],
        "recommendations": [{k: r.get(k) for k in ("id", "status", "station_id", "fuel_type", "allocation", "expected_impact", "confidence")} for r in recs[:10]],
    }
    text = _llm("Answer the operator's question using only this network state. If the question is not about this fuel "
                "network, say you can only answer questions about the current operations. Return JSON "
                '{"answer": str, "evidence": [ids like "alert:9" or "recommendation:21" that support it]}.\n'
                f"Question: {question}\nState: {json.dumps(context, default=str)}", want_json=True)
    if text:
        try:
            out = json.loads(text)
            return {"answer": str(out["answer"]), "evidence": [e for e in out.get("evidence", []) if e in ids], "source": "llm"}
        except Exception:
            pass
    return template
