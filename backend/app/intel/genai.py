"""Operator-facing text: explanations, briefing, investigation assistant.

The LLM only explains facts computed by deterministic code; it never decides quantities.
Provider chain: OpenAI -> Gemini -> Groq -> template. Every function returns source "llm" or "template".
Inputs may be Pydantic models or plain dicts (the backend passes dicts).
Prompts get pre-formatted, human-readable facts (names, percentages, clock times) so the text is operator-ready.
"""
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any

log = logging.getLogger("gta7.intel.genai")

TIMEOUT_S = 8.0
GEMINI_TIMEOUT_MS = 12_000  # Gemini rejects deadlines under 10 s
COOLDOWN_S = 60.0          # skip a provider for this long after it fails
CACHE_MAX = 256
MAX_CHARS = 900
# used when GROQ_MODEL_PRIMARY/FALLBACK are not set; all verified available on Groq (Llama left the free tier: 404)
GROQ_DEFAULT_MODELS = ("qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b")  # 20b: free-tier safety net            # explanation length shown in the dashboard
SYSTEM = (
    "You are the operations assistant of a fuel supply control room (simulated network in Bangladesh). "
    "Use ONLY the facts in the JSON you are given. Never invent numbers, stations, routes or events. "
    "Quantities and decisions come from the optimizer; you explain them. Be concise and concrete, "
    "plain text, no markdown."
)

_cache: dict[str, str] = {}
_down_until: dict[str, float] = {}
last_provider: dict[str, str] = {"name": ""}
stats: dict[str, Any] = {"calls": 0, "llm_ok": 0, "template": 0, "failures": 0, "cache_hits": 0, "last_error": None}


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


def _json_block(text: str) -> str:
    """Some models wrap JSON in ```json fences or add reasoning before it."""
    if "{" in text and "}" in text:
        return text[text.index("{"): text.rindex("}") + 1]
    return text


def _d(x: Any) -> Any:
    if hasattr(x, "model_dump"):
        return x.model_dump(mode="json")
    if isinstance(x, list):
        return [_d(i) for i in x]
    return x


def _g(obj: Any, *path: str, default: Any = None) -> Any:
    """Field access on a model or dict without dumping the whole snapshot."""
    cur = obj
    for p in path:
        cur = cur.get(p) if isinstance(cur, dict) else getattr(cur, p, None)
        if cur is None:
            return default
    return _d(cur)


def _names(s: Any) -> dict[str, str]:
    items = (_g(s, "stations", default=[]) or []) + (_g(s, "depots", default=[]) or [])
    return {e["id"]: e.get("name", e["id"]) for e in items if isinstance(e, dict) and "id" in e}


def _pct(x: Any) -> str:
    try:
        return f"{float(x):.0%}"
    except (TypeError, ValueError):
        return "n/a"


def _clean(text: str, limit: int = MAX_CHARS) -> str:
    """Plain text for the dashboard: no markdown, one paragraph, cut at a sentence end."""
    text = re.sub(r"[*_`#]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cut = text[:limit]
        text = cut[: cut.rfind(". ") + 1] if ". " in cut else cut.rstrip() + "..."
    return text


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
        steps += [(f"groq:{m}", _groq) for m in _models(cfg.get("groq_model_primary"), cfg.get("groq_model_fallback")) or list(GROQ_DEFAULT_MODELS)]
    return steps


def _llm(user: str, want_json: bool = False) -> str | None:
    """First provider that answers wins; None means use the template."""
    stats["calls"] += 1
    key = hashlib.sha256(f"{want_json}|{user}".encode()).hexdigest()
    if key in _cache:
        stats["cache_hits"] += 1
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
                stats["llm_ok"] += 1
                return text
        except Exception as exc:
            log.warning("llm %s failed: %s", name, str(exc)[:200])
            stats["failures"] += 1
            stats["last_error"] = f"{name}: {str(exc)[:120]}"
            _down_until[name] = time.monotonic() + COOLDOWN_S
    stats["template"] += 1
    return None


def llm_status() -> dict:
    """For the backend's system-status page: which provider answers and how often we fell back to templates."""
    chain = [n for n, _ in _chain(_cfg())]
    now = time.monotonic()
    ready = [n for n in chain if _down_until.get(n, 0) <= now]
    return {"status": "healthy" if ready else "unavailable", "chain": chain,
            "cooling_down": [n for n in chain if n not in ready], "last_provider": last_provider["name"] or None, **stats}


# ---------------- readable facts (shared by prompts and templates) ----------------
def _clock(s: Any, tick: Any) -> str:
    """'14:30 (in 30 min)' for a tick relative to the snapshot."""
    try:
        now = _g(s, "sim_time")
        now = now if isinstance(now, datetime) else datetime.fromisoformat(str(now))
        mins = (int(tick) - int(_g(s, "tick", default=0))) * int(_g(s, "tick_minutes", default=15))
        when = (now + timedelta(minutes=mins)).strftime("%H:%M")
        if mins <= 0:
            return f"{when} (now)"
        return f"{when} (in {mins} min)" if mins < 120 else f"{when} (in {mins / 60:.1f} h)"
    except Exception:
        return f"tick {tick}"


def _rec_facts(rec: dict, s: Any, names: dict) -> dict:
    a, sit, imp = rec.get("allocation") or {}, rec.get("situation") or {}, rec.get("expected_impact") or {}
    n = lambda x: names.get(x, x)
    return {
        "action": f"send {a.get('quantity', 0):.0f} L of {str(rec.get('fuel_type', '')).lower()} from {n(a.get('source_depot_id'))} "
                  f"to {n(rec.get('station_id'))} via {a.get('route_id')}",
        "arrives": _clock(s, a.get("eta_tick")),
        "station_stock_now": f"{sit.get('current_inventory', 0):.0f} L",
        "runs_dry_in": f"{sit.get('projected_stockout_hours', '?')} h",
        "demand_next_4h": f"{sit.get('expected_demand_next_4h', 0):.0f} L",
        "stockout_risk_24h": f"{_pct(imp.get('stockout_prob_before'))} now, {_pct(imp.get('stockout_prob_after'))} after this delivery",
        "lost_sales_avoided": f"{imp.get('unmet_liters_avoided', 0):.0f} L",
        "confidence": _pct(rec.get("confidence")),
        "needs_human_review": bool(rec.get("requires_human_review")),
        "planner_mode": rec.get("mode"),
        "reasons": rec.get("signals") or [],
        "limits": rec.get("constraints") or [],
        "alternatives": [f"{alt.get('quantity', 0):.0f} L from {n(alt.get('source_depot_id'))} via {alt.get('route_id')}, "
                         f"arrives {_clock(s, alt.get('eta_tick'))}, risk after {_pct(alt.get('stockout_prob_after'))}"
                         for alt in (rec.get("alternatives") or [])[:3]],
    }


def _risk_table(s: Any, limit: int = 8) -> list[dict]:
    """At-risk station/fuels computed on the fly; empty if anything fails."""
    try:
        from .forecast import forecast
        from .models import Snapshot
        from .risk import assess_risk
        snap = s if isinstance(s, Snapshot) else Snapshot(**s)
        names = _names(snap)
        risks = sorted((r for r in assess_risk(snap, forecast(snap)) if r.level != "ok"), key=lambda r: -r.stockout_prob)
        return [{"station": names.get(r.station_id, r.station_id), "fuel": r.fuel_type, "level": r.level,
                 "runs_dry_in": f"{r.stockout_hours} h", "stockout_risk_24h": _pct(r.stockout_prob),
                 "stock": f"{r.current_inventory:.0f} L"} for r in risks[:limit]]
    except Exception:
        return []


def _entity_state(s: Any, ent: dict, names: dict) -> dict | None:
    eid = ent.get("id")
    for kind in ("stations", "depots"):
        for e in _g(s, kind, default=[]):
            if e.get("id") == eid:
                inv, cap = e.get("inventory") or {}, e.get("capacity") or {}
                out = {"name": e.get("name", eid), "status": e.get("status"),
                       "stock": {f: f"{inv.get(f, 0):.0f} of {cap.get(f, 0):.0f} L" for f in inv}}
                if "demand_multiplier" in e:
                    out["demand_multiplier"] = e["demand_multiplier"]
                return out
    routes = _g(s, "routes", default=[])
    for r in routes:
        if r.get("id") == eid:
            dest = r.get("destination_station_id")
            alts = [x["id"] for x in routes if x.get("destination_station_id") == dest and x.get("status") == "AVAILABLE" and x["id"] != eid]
            return {"route": eid, "status": r.get("status"), "from": names.get(r.get("source_depot_id")),
                    "to": names.get(dest), "other_routes_to_station": alts or "none"}
    return None


def _events(s: Any) -> list[str]:
    return [f"{e.get('type')} (ticks {e.get('start_tick')}-{e.get('end_tick')}, {e.get('parameters') or {}})"
            for e in _g(s, "events", default=[]) if e.get("status") == "ACTIVE"]


def _known_cause(s: Any, alert: dict) -> list[str]:
    """Active events whose parameters name the alert's entity (or its station's region / supply's depot).
    Deterministic, so the LLM never has to guess the cause."""
    ent = alert.get("entity") or {}
    eid, etype = ent.get("id"), ent.get("type")
    related = {eid}
    for st in _g(s, "stations", default=[]):
        if st.get("id") == eid:
            related.add(st.get("region_id"))
    for a in _g(s, "supply_arrivals", default=[]):
        if a.get("id") == eid:
            related.add(a.get("depot_id"))
    if etype == "system" and str(eid).startswith("event-"):
        return [e for e in _events(s) if f"event-{e}" == eid] or [alert.get("title", "")]
    out = []
    for e in _g(s, "events", default=[]):
        if e.get("status") != "ACTIVE":
            continue
        p = e.get("parameters") or {}
        named = {x for k in ("station_ids", "region_ids", "route_ids", "depot_ids") for x in p.get(k, [])}
        type_fits = {"route": ("route_disruption",), "supply": ("shipment_delay", "supply_shortfall"),
                     "depot": ("depot_constraint", "shipment_delay", "supply_shortfall")}.get(etype)
        if named & related and (type_fits is None or e.get("type") in type_fits):
            out.append(f"{e.get('type')} event (ticks {e.get('start_tick')}-{e.get('end_tick')})")
    return out


def _service(s: Any) -> str | None:
    m = _g(s, "metrics", default={}) or {}
    if "service_level" not in m:
        return None
    return f"service level {_pct(m['service_level'])}, {float(m.get('unmet_demand_liters', 0)):.0f} L unmet so far"


# ---------------- templates ----------------
def _tpl_recommendation(f: dict) -> str:
    text = (f"Recommend: {f['action']}, arriving {f['arrives']}. The station holds {f['station_stock_now']} and runs dry in "
            f"{f['runs_dry_in']}. Stockout risk (24 h): {f['stockout_risk_24h']}; about {f['lost_sales_avoided']} of lost sales "
            f"avoided. Confidence {f['confidence']}.")
    if f["limits"]:
        text += " Limited by: " + "; ".join(f["limits"][:2]) + "."
    if f["needs_human_review"]:
        text += " Needs operator review."
    return text


# ---------------- public API ----------------
def explain_recommendation(rec: Any, s: Any) -> tuple[str, str]:
    rec, names = _d(rec), _names(s)
    facts = _rec_facts(rec, s, names)
    text = _llm("Explain this fuel delivery recommendation to the control-room operator in 2-3 short sentences: why the "
                "station needs it, why this depot/route (mention an alternative only if it matters), and what it does to the "
                "stockout risk. Use the numbers exactly as given.\n" + json.dumps(facts, default=str))
    return (_clean(text), "llm") if text else (_tpl_recommendation(facts), "template")


def explain_incident(alert: Any, s: Any) -> tuple[str, str]:
    alert, names = _d(alert), _names(s)
    template = f"{alert.get('title', 'Incident')}. {alert.get('detail', '')}".strip()
    ent = alert.get("entity") or {}
    context = {"alert": {k: alert.get(k) for k in ("severity", "kind", "title", "detail")},
               "affected": _entity_state(s, ent, names),
               "known_cause": _known_cause(s, alert) or "not known from current data",
               "stations_at_risk": _risk_table(s, 5)}
    text = _llm("Explain this incident to the operator in 2-3 short sentences: what is happening, its cause, and what it "
                "affects next. State the cause exactly as given in known_cause; do not suggest any other cause.\n"
                + json.dumps(context, default=str))
    return (_clean(text), "llm") if text else (template, "template")


def briefing(s: Any, risks: list, alerts: list) -> dict:
    risks, alerts, names = _d(risks) or [], _d(alerts) or [], _names(s)
    tick = _g(s, "tick", default=0)
    top = sorted((r for r in risks if r.get("level") not in (None, "ok")), key=lambda r: -(r.get("stockout_prob") or 0))[:5]
    crit = [a for a in alerts if a.get("severity") == "critical"]
    service = _service(s)
    template = {
        "tick": tick,
        "summary": f"Tick {tick}: {len(top)} station-fuel pairs at risk, {len(alerts)} open alerts ({len(crit)} critical)."
                   + (f" Network {service}." if service else ""),
        "top_risks": [f"{names.get(r['station_id'], r['station_id'])} {r['fuel_type']}: {r['level']}, "
                      f"runs dry in {r.get('stockout_hours')} h (24 h risk {_pct(r.get('stockout_prob'))})" for r in top],
        "recommended_actions": [f"Review resupply for {names.get(r['station_id'], r['station_id'])} {r['fuel_type']}" for r in top[:3]]
                               or ["No action needed; keep monitoring."],
        "source": "template",
    }
    facts = {"time": _clock(s, tick), "network": service,
             "top_risks": [{"station": names.get(r["station_id"], r["station_id"]), "fuel": r["fuel_type"], "level": r["level"],
                            "runs_dry_in": f"{r.get('stockout_hours')} h", "risk_24h": _pct(r.get("stockout_prob"))} for r in top],
             "alerts": [{k: a.get(k) for k in ("severity", "kind", "title", "detail")} for a in alerts[:15]],
             "active_events": _events(s)}
    text = _llm('Write a control-room situation briefing. Return JSON {"summary": str (2-4 sentences, lead with the most '
                'urgent issue), "top_risks": [str] (max 5, one line each), "recommended_actions": [str] (max 4, concrete)}.\n'
                + json.dumps(facts, default=str), want_json=True)
    if text:
        try:
            out = json.loads(text)
            return {"tick": tick, "summary": _clean(str(out["summary"])),
                    "top_risks": [_clean(str(x), 200) for x in out.get("top_risks", [])][:5],
                    "recommended_actions": [_clean(str(x), 200) for x in out.get("recommended_actions", [])][:4], "source": "llm"}
        except Exception:
            pass
    return template


def answer(question: str, s: Any, alerts: list, recs: list) -> dict:
    alerts, recs, names = _d(alerts) or [], _d(recs) or [], _names(s)
    ids = {f"alert:{a['id']}" for a in alerts if "id" in a} | {f"recommendation:{r['id']}" for r in recs if "id" in r}
    words = [w for w in question.lower().split() if len(w) > 3]
    hits = [a for a in alerts if any(w in f"{a.get('title', '')} {a.get('detail', '')}".lower() for w in words)] or alerts
    template = {
        "answer": ("AI assistant unavailable. Relevant alerts:\n" + "\n".join(f"- {a.get('title')} ({a.get('detail', '')})" for a in hits[:5]))
                  if hits else "AI assistant unavailable and there are no open alerts.",
        "evidence": [f"alert:{a['id']}" for a in hits[:5] if "id" in a], "source": "template",
    }
    context = {
        "time": _clock(s, _g(s, "tick", default=0)), "network": _service(s),
        "stations_at_risk": _risk_table(s),
        "stations": [{k: st.get(k) for k in ("id", "name", "status", "inventory", "capacity", "demand_multiplier")}
                     for st in _g(s, "stations", default=[])],
        "depots": [{k: d.get(k) for k in ("id", "name", "status", "inventory", "dispatch_capacity_per_tick")} for d in _g(s, "depots", default=[])],
        "routes": [{k: r.get(k) for k in ("id", "status", "transit_ticks", "max_shipment")} for r in _g(s, "routes", default=[])],
        "active_events": _events(s),
        "alerts": [{k: a.get(k) for k in ("id", "severity", "kind", "title", "detail")} for a in alerts[:20]],
        "recommendations": [{"id": r.get("id"), "status": r.get("status"), **_rec_facts(r, s, names)} for r in recs[:10]],
    }
    text = _llm("Answer the operator's question using only this network state. Be direct and specific (2-5 sentences). "
                "If the question is not about this fuel network, say you can only answer questions about the current operations. "
                'Return JSON {"answer": str, "evidence": [ids like "alert:9" or "recommendation:21" that support it]}.\n'
                f"Question: {question}\nState: {json.dumps(context, default=str)}", want_json=True)
    if text:
        try:
            out = json.loads(text)
            return {"answer": _clean(str(out["answer"]), 1200), "evidence": [e for e in out.get("evidence", []) if e in ids],
                    "source": "llm"}
        except Exception:
            pass
    return template
