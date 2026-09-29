"""Operator-facing text. v1: templates only (source="template"); Gemini/Groq added later with this as fallback."""
from .models import AlertDraft, RecommendationDraft, Risk, Snapshot


def explain_recommendation(rec: RecommendationDraft, s: Snapshot) -> tuple[str, str]:
    a, imp = rec.allocation, rec.expected_impact
    text = (f"Send {a.quantity:.0f} L {rec.fuel_type.lower()} from {a.source_depot_id} via {a.route_id} "
            f"to {rec.station_id} (arrives tick {a.eta_tick}). Stockout expected in "
            f"{rec.situation.projected_stockout_hours} h; risk drops from {imp.stockout_prob_before:.0%} "
            f"to {imp.stockout_prob_after:.0%}. Confidence {rec.confidence:.0%}.")
    return text, "template"


def explain_incident(alert: AlertDraft, s: Snapshot) -> tuple[str, str]:
    return f"{alert.title}. {alert.detail}".strip(), "template"


def briefing(s: Snapshot, risks: list[Risk], alerts: list[AlertDraft]) -> dict:
    top = sorted((r for r in risks if r.level != "ok"), key=lambda r: -r.stockout_prob)[:3]
    return {
        "summary": f"Tick {s.tick}: {len(top)} station-fuel pairs at risk, {len(alerts)} alerts.",
        "top_risks": [f"{r.station_id} {r.fuel_type}: {r.level}, {r.stockout_hours} h" for r in top],
        "recommended_actions": [f"Review resupply for {r.station_id} {r.fuel_type}" for r in top],
        "source": "template",
    }


def answer(question: str, s: Snapshot, alerts: list[dict], recs: list[dict]) -> dict:
    ev = [f"alert:{a['id']}" for a in alerts if "id" in a][:5] + [f"recommendation:{r['id']}" for r in recs if "id" in r][:5]
    return {
        "answer": f"{len(alerts)} open alerts and {len(recs)} recommendations at tick {s.tick}. "
                  "Detailed AI answers are unavailable; see the listed evidence.",
        "evidence": ev, "source": "template",
    }
