"""Intelligence layer (owner: Farhan). Pure functions called by backend core once per tick.

Agreed signatures (see docs/INTEL_INTERFACE.md):
    forecast(s, horizon=16) -> list[Forecast]
    assess_risk(s, fc) -> list[Risk]
    detect(s, fc, prev) -> list[AlertDraft]
    plan(s, fc, risks) -> list[RecommendationDraft]
    fallback_plan(s) -> list[RecommendationDraft]
    simulate(s, fc, station_id, fuel_type, source_depot_id, route_id, quantity) -> WhatIf
    explain_recommendation(rec, s) -> (text, source)
    explain_incident(alert, s) -> (text, source)
    briefing(s, risks, alerts) -> dict
    answer(question, s, alerts, recs) -> dict
"""
from .detect import detect
from .forecast import forecast
from .genai import answer, briefing, explain_incident, explain_recommendation
from .models import (
    AlertDraft, Forecast, RecommendationDraft, Risk, Snapshot, WhatIf,
)
from .planner import fallback_plan, plan, simulate
from .risk import assess_risk

__all__ = [
    "Snapshot", "Forecast", "Risk", "AlertDraft", "RecommendationDraft", "WhatIf",
    "forecast", "assess_risk", "detect", "plan", "fallback_plan", "simulate",
    "explain_recommendation", "explain_incident", "briefing", "answer",
]
