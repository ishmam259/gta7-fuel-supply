"""Bridge between backend core and the intelligence module (app.intel, owned by Farhan).

If app.intel is missing or raises, the rule-based fallback policy is used and the fallback
is counted and reported (brief §11). Outputs are normalized to plain dicts matching the API contract.
"""
import importlib
import logging
from typing import Any

from . import fallback_policy as fb
from .logging_setup import log_event
from .metrics import FALLBACK_ACTIVATIONS, LLM_CALLS

log = logging.getLogger("gta7.intel")


def _d(x: Any) -> Any:
    if hasattr(x, "model_dump"):
        return x.model_dump(mode="json")
    if isinstance(x, list):
        return [_d(i) for i in x]
    if isinstance(x, tuple):
        return tuple(_d(i) for i in x)
    return x


def _intel():
    try:
        return importlib.import_module("app.intel")
    except Exception:
        return None


def _snapshot_obj(intel, snap: dict):
    models = getattr(intel, "models", None) or _try_import("app.intel.models")
    Snap = getattr(models, "Snapshot", None) if models else None
    return Snap(**snap) if Snap else snap


def _try_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception:
        return None


class IntelStatus:
    prediction = "healthy"
    decision = "healthy"
    llm = "unavailable"
    last_error: str | None = None


STATUS = IntelStatus()


def run_pipeline(snap: dict, prev: dict | None) -> dict:
    """Returns {risks, alerts, recommendations, forecasts, mape, fallback_used}."""
    intel = _intel()
    result: dict[str, Any] = {"forecasts": [], "mape": None, "fallback_used": False}
    risks = None
    if intel is not None and hasattr(intel, "forecast") and hasattr(intel, "assess_risk"):
        try:
            s_obj = _snapshot_obj(intel, snap)
            fc = intel.forecast(s_obj)
            risk_list = intel.assess_risk(s_obj, fc)
            risks = _risk_map(_d(risk_list))
            result["forecasts"] = _d(fc)
            mapes = [f.get("mape_recent") for f in result["forecasts"] if isinstance(f, dict) and f.get("mape_recent") is not None]
            result["mape"] = sum(mapes) / len(mapes) if mapes else None
            alerts = _d(intel.detect(s_obj, fc, _snapshot_obj(intel, prev) if prev else None)) if hasattr(intel, "detect") else fb.detect(snap, risks)
            try:
                recs = _d(intel.plan(s_obj, fc, risk_list))
                STATUS.decision = "healthy"
            except Exception as exc:
                log_event(log, "decision engine failed, using fallback policy", logging.WARNING, error=str(exc))
                FALLBACK_ACTIVATIONS.labels("decision_engine").inc()
                STATUS.decision, STATUS.last_error = "fallback", str(exc)
                recs = _d(intel.fallback_plan(s_obj)) if hasattr(intel, "fallback_plan") else fb.plan(snap, risks)
                result["fallback_used"] = True
            STATUS.prediction = "healthy"
            result.update(risks=risks, alerts=alerts, recommendations=recs)
            return result
        except Exception as exc:
            log_event(log, "prediction service failed, using fallback policy", logging.WARNING, error=repr(exc))
            STATUS.last_error = repr(exc)
    # fallback path: intel missing or failed
    FALLBACK_ACTIVATIONS.labels("prediction_service").inc()
    STATUS.prediction = STATUS.decision = "fallback"
    risks = fb.assess(snap)
    result.update(risks=risks, alerts=fb.detect(snap, risks), recommendations=fb.plan(snap, risks), fallback_used=True)
    return result


def _risk_map(risk_list: list[dict]) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for r in risk_list:
        out.setdefault(r["station_id"], {})[r["fuel_type"]] = {
            "level": r.get("level", "ok"),
            "stockout_hours": r.get("stockout_hours"),
            "stockout_prob": r.get("stockout_prob"),
        }
    return out


def simulate(snap: dict, body: dict) -> dict:
    intel = _intel()
    if intel is not None and hasattr(intel, "simulate"):
        try:
            s_obj = _snapshot_obj(intel, snap)
            return _d(intel.simulate(s_obj, intel.forecast(s_obj), body["station_id"], body["fuel_type"],
                                     body["source_depot_id"], body["route_id"], body["quantity"]))
        except Exception as exc:
            log_event(log, "what-if simulate failed, using fallback projection", logging.WARNING, error=repr(exc))
            FALLBACK_ACTIVATIONS.labels("simulate").inc()
    return _fallback_whatif(snap, body)


def _fallback_whatif(snap: dict, body: dict) -> dict:
    rates, transit = fb.demand_rate(snap), fb.in_transit(snap)
    st = next(s for s in snap["stations"] if s["id"] == body["station_id"])
    route = next(r for r in snap["routes"] if r["id"] == body["route_id"])
    f = body["fuel_type"]
    rate = rates[(st["id"], f)]
    arrive = snap["tick"] + 1 + route["transit_ticks"]
    inv_a = inv_b = st["inventory"][f] + transit[(st["id"], f)]
    without, with_ = [], []
    for t in range(snap["tick"] + 1, snap["tick"] + 17):
        inv_a = max(0.0, inv_a - rate)
        inv_b = max(0.0, inv_b - rate) + (body["quantity"] if t == arrive else 0)
        without.append({"tick": t, "inventory": round(inv_a, 1)})
        with_.append({"tick": t, "inventory": round(min(inv_b, st["capacity"][f]), 1)})
    tph = 60 / snap["tick_minutes"]
    before_h = (st["inventory"][f] + transit[(st["id"], f)]) / max(rate, 1e-6) / tph
    after_h = before_h + body["quantity"] / max(rate, 1e-6) / tph
    return {"projection_without": without, "projection_with": with_,
            "stockout_prob_before": fb._prob(before_h, 3.0), "stockout_prob_after": fb._prob(after_h, 3.0),
            "source": "fallback"}


# ---------------- GenAI (explanations, briefing, assistant) ----------------

def _genai():
    return _try_import("app.intel.genai")


def _call_llm(fn_name: str, *args) -> Any | None:
    g = _genai()
    fn = getattr(g, fn_name, None) if g else None
    if fn is None:
        return None
    try:
        out = fn(*args)
        LLM_CALLS.labels("ok").inc()
        STATUS.llm = "healthy"
        return _d(out)
    except Exception as exc:
        LLM_CALLS.labels("error").inc()
        STATUS.llm = "unavailable"
        log_event(log, "LLM call failed, using template", logging.WARNING, fn=fn_name, error=repr(exc))
        return None


def briefing(snap: dict, risks: dict, alerts: list[dict]) -> dict:
    intel = _intel()
    out = _call_llm("briefing", _snapshot_obj(intel, snap) if intel else snap, _flat_risks(risks), alerts)
    if isinstance(out, dict):
        return out
    critical = [a for a in alerts if a.get("severity") == "critical"]
    return {"tick": snap["tick"],
            "summary": (f"Tick {snap['tick']}: {len(alerts)} open alerts ({len(critical)} critical). "
                        f"Service level {snap.get('metrics', {}).get('service_level', 1):.1%}."),
            "top_risks": [a["title"] for a in (critical or alerts)[:5]],
            "recommended_actions": ["Review pending recommendations in the inbox."],
            "source": "template"}


def answer(question: str, snap: dict, alerts: list[dict], recs: list[dict]) -> dict:
    intel = _intel()
    out = _call_llm("answer", question, _snapshot_obj(intel, snap) if intel else snap, alerts, recs)
    if isinstance(out, dict):
        return out
    q = question.lower()
    hits = [a for a in alerts if any(w in (a["title"] + " " + a.get("detail", "")).lower() for w in q.split() if len(w) > 3)]
    lines = [f"- {a['title']} ({a.get('detail', '')})" for a in (hits or alerts)[:5]]
    return {"answer": "LLM unavailable; relevant alerts:\n" + ("\n".join(lines) or "none"),
            "evidence": [f"alert:{a.get('id')}" for a in (hits or alerts)[:5]], "source": "template"}


def explain_incident(alert: dict, snap: dict) -> dict:
    intel = _intel()
    out = _call_llm("explain_incident", alert, _snapshot_obj(intel, snap) if intel else snap)
    if isinstance(out, (list, tuple)) and len(out) == 2:
        return {"explanation": out[0], "source": out[1]}
    return {"explanation": f"{alert['title']}. {alert.get('detail', '')}", "source": "template"}


def explain_recommendation(rec: dict, snap: dict) -> tuple[str, str]:
    intel = _intel()
    out = _call_llm("explain_recommendation", rec, _snapshot_obj(intel, snap) if intel else snap)
    if isinstance(out, (list, tuple)) and len(out) == 2:
        return out[0], out[1]
    return rec.get("explanation") or "", "template"


def _flat_risks(risks: dict) -> list[dict]:
    return [{"station_id": s, "fuel_type": f, **v} for s, fm in risks.items() for f, v in fm.items()]
