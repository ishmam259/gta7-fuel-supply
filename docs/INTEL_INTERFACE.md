# Interface: backend core (Ishmam) ↔ intelligence (Farhan)
`backend/app/intel/` exposes plain functions. Backend core calls them once per tick with a validated snapshot.
Models live in `backend/app/intel/models.py` (Farhan) and are plain Pydantic v2 models. Until Farhan pushes, Ishmam uses stubs with the same signatures.

## Input
```python
class Snapshot(BaseModel):
    tick: int; sim_time: datetime; tick_minutes: int = 15
    depots: list[dict]; stations: list[dict]; routes: list[dict]           # raw simulator JSON (already validated)
    allocations: list[dict]; supply_arrivals: list[dict]; events: list[dict]
    demand_history: list[dict]                                             # last ~2000 rows from /v1/demand-history
```

## Functions
```python
def forecast(s: Snapshot, horizon: int = 16) -> list[Forecast]          # one per (station_id, fuel_type)
def assess_risk(s: Snapshot, fc: list[Forecast]) -> list[Risk]          # stockout_hours, stockout_prob, level
def detect(s: Snapshot, fc: list[Forecast], prev: Snapshot | None) -> list[AlertDraft]
def plan(s: Snapshot, fc: list[Forecast], risks: list[Risk]) -> list[RecommendationDraft]   # obeys ALL simulator limits
def fallback_plan(s: Snapshot) -> list[RecommendationDraft]              # rule-based; used if forecast/plan raises
def simulate(s: Snapshot, fc: list[Forecast], station_id: str, fuel_type: str,
             source_depot_id: str, route_id: str, quantity: float) -> WhatIf
# genai.py (each returns (text, source) where source in {"llm","template"})
def explain_recommendation(rec: RecommendationDraft, s: Snapshot) -> tuple[str, str]
def explain_incident(alert: AlertDraft, s: Snapshot) -> tuple[str, str]
def briefing(s: Snapshot, risks: list[Risk], alerts: list[AlertDraft]) -> dict      # summary, top_risks, recommended_actions, source
def answer(question: str, s: Snapshot, alerts: list[dict], recs: list[dict]) -> dict  # answer, evidence, source
```
Field names of `Risk`, `AlertDraft`, `RecommendationDraft`, `WhatIf` must match the JSON in `docs/API_CONTRACT.md`
(`risk`, alerts, recommendations, simulate response) so the backend can store and return them unchanged.

## Metrics the backend records from intel results
prediction MAPE (from Forecast.mape_recent), avg confidence, shortage alerts per tick, recommendations per tick,
fallback activations, LLM calls/failures.
