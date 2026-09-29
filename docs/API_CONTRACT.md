# API Contract v2 (backend port 8090) — backend http://localhost:8090
Source of truth between dashboard ↔ backend. **Only Ishmam edits this file**; changes are announced as "contract vN" in the team chat.
JSON everywhere. Errors: `{"detail": {"code": "UPPER_SNAKE", "message": "..."}}`.
Sensitive routes (marked 🔒) need header `X-Operator-Key: <OPERATOR_KEY from .env>`.

## Network state
`GET /api/state`
```json
{
  "instance": {"tick": 42, "sim_time": "2026-01-01T10:30:00", "status": "RUNNING"},
  "metrics": {"service_level": 0.981, "served_demand_liters": 12345.6, "unmet_demand_liters": 234.5, "allocation_liters": 9800, "allocation_failures": 2},
  "regions": [{"id": "region-dhaka", "name": "Dhaka Division", "demand_factor": 1.0, "demand_last_4h": {"DIESEL": 4200, "PETROL": 5100, "OCTANE": 2300}}],
  "depots": [{"id": "depot-gazipur", "name": "Gazipur Depot", "region_id": "region-dhaka", "status": "OPEN", "dispatch_capacity_per_tick": 12000,
              "dispatch_used_this_tick": 3000,
              "capacity": {"DIESEL": 90000, "PETROL": 70000, "OCTANE": 45000}, "inventory": {"DIESEL": 60000, "PETROL": 45000, "OCTANE": 26000}}],
  "stations": [{"id": "station-mirpur", "name": "Mirpur Fuel Station", "region_id": "region-dhaka", "status": "OPEN",
                "demand_profile": "urban_high", "demand_multiplier": 1.0,
                "capacity": {"DIESEL": 15000, "PETROL": 14000, "OCTANE": 9000}, "inventory": {"DIESEL": 9000, "PETROL": 9000, "OCTANE": 5000},
                "risk": {"DIESEL": {"level": "ok", "stockout_hours": 30.5, "stockout_prob": 0.02},
                         "PETROL": {"level": "watch", "stockout_hours": 9.1, "stockout_prob": 0.21},
                         "OCTANE": {"level": "critical", "stockout_hours": 3.2, "stockout_prob": 0.74}}}],
  "routes": [{"id": "route-gazipur-mirpur", "source_depot_id": "depot-gazipur", "destination_station_id": "station-mirpur", "transit_ticks": 2, "max_shipment": 7000, "status": "AVAILABLE"}],
  "in_transit": [{"id": 17, "route_id": "route-gazipur-tongi", "fuel_type": "DIESEL", "quantity": 6000, "status": "IN_TRANSIT", "expected_arrival_tick": 44}],
  "upcoming_supply": [{"id": "supply-005", "depot_id": "depot-patiya", "fuel_type": "PETROL", "quantity": 18000, "planned_tick": 60, "status": "DELAYED"}],
  "active_events": [{"id": 3, "type": "route_disruption", "start_tick": 40, "end_tick": 52, "status": "ACTIVE", "parameters": {"route_ids": ["route-gazipur-mirpur"]}}],
  "data_freshness": {"stale": false, "degraded": false, "last_sync_tick": 42, "last_sync_at": "2026-09-29T10:12:00Z"}
}
```
`risk.level` ∈ `ok | watch | critical | outage`. Simulated data only (UI must label it "SIMULATED").

`GET /api/forecast?station_id=&fuel_type=` → `[{"station_id","fuel_type","horizon_ticks":16,"per_tick":[55.2,...],"lower":[...],"upper":[...],"mape_recent":0.08}]`
`GET /api/metrics/history?limit=500` → `[{"tick":41,"service_level":0.98,"unmet_demand_liters":230.1,"allocation_liters":9000,"open_alerts":3}]`

## Alerts
`GET /api/alerts?status=open|all&limit=100`
```json
[{"id": 9, "tick": 42, "severity": "info|warning|critical", "kind": "shortage_risk|anomalous_demand|inventory_anomaly|bottleneck|disruption|integration_failure|low_confidence|fallback|recovery",
  "entity": {"type": "station", "id": "station-mirpur", "fuel_type": "OCTANE"},
  "title": "Octane stockout in 3.2 h at Mirpur", "detail": "Demand 1.8x normal (demand_spike, Dhaka)", "status": "open|resolved", "created_at": "..."}]
```

## Recommendations (inspectable, human-in-the-loop)
`GET /api/recommendations?status=pending|approved|executed|rejected|failed|all`
```json
[{"id": 21, "tick": 42, "status": "pending", "mode": "optimizer|heuristic|fallback",
  "station_id": "station-mirpur", "fuel_type": "OCTANE",
  "allocation": {"source_depot_id": "depot-gazipur", "route_id": "route-gazipur-mirpur", "quantity": 5000, "eta_tick": 44},
  "situation": {"current_inventory": 5000, "expected_demand_next_4h": 7400, "projected_stockout_hours": 3.2},
  "expected_impact": {"stockout_prob_before": 0.74, "stockout_prob_after": 0.12, "unmet_liters_avoided": 2400},
  "confidence": 0.86, "requires_human_review": false,
  "signals": ["demand 1.8x forecast (anomaly z=3.1)", "active demand_spike region-dhaka"],
  "constraints": ["route max 7000 L", "depot dispatch left this tick 9000 L"],
  "alternatives": [{"source_depot_id": "depot-patiya", "route_id": "route-patiya-mirpur", "quantity": 5000, "eta_tick": 46, "stockout_prob_after": 0.31}],
  "explanation": "LLM or template text for the operator",
  "sim_allocation_id": null, "failure_reason": null}]
```
`GET /api/recommendations/{id}` → one object
🔒 `POST /api/recommendations/{id}/approve` body `{"quantity": 5000, "note": "optional override"}` → updated object (status `executed` or `failed` + `failure_reason`)
🔒 `POST /api/recommendations/{id}/reject` body `{"note": "..."}` → updated object
`POST /api/recommendations/simulate` body `{"station_id","fuel_type","source_depot_id","route_id","quantity"}` → `{"projection_without":[{"tick","inventory"}],"projection_with":[...],"stockout_prob_before":0.74,"stockout_prob_after":0.12}` (what-if, no writes)
`GET /api/decisions?limit=100` → audit history: `[{"id","tick","actor":"operator|autopilot|system","action":"approve|reject|execute|fallback|cancel","recommendation_id","result":"OK|<ERROR_CODE>","note","created_at"}]`

## Decision mode
`GET /api/mode` → `{"mode": "manual|assisted", "auto_confidence_threshold": 0.8, "auto_max_quantity": 5000}`
🔒 `POST /api/mode` same body → same shape

## AI assistant (GenAI supports operations)
`GET /api/briefing` → `{"tick": 42, "summary": "situation report", "top_risks": ["..."], "recommended_actions": ["..."], "source": "llm|template"}`
`POST /api/assistant` body `{"question": "Why is Mirpur at risk?"}` → `{"answer": "...", "evidence": ["alert:9", "recommendation:21"], "source": "llm|template"}`
`GET /api/incidents/{alert_id}/explain` → `{"explanation": "...", "source": "llm|template"}`

## System health & observability
`GET /api/health` → `{"status": "ok"}` (liveness, no dependencies)
`GET /api/system/status`
```json
{"overall": "healthy|degraded|down",
 "components": {"backend_api": "healthy", "database": "healthy", "simulator": "healthy|degraded|down",
                "prediction_service": "healthy|fallback", "decision_engine": "healthy|fallback", "llm": "healthy|unavailable"},
 "circuit_breaker": "closed|open|half_open", "sse": "connected|reconnecting",
 "p95_latency_ms": 164, "error_rate": 0.004, "fallback_activations": 3, "uptime_s": 5400}
```
`GET /metrics` → Prometheus text format (HTTP + domain + intelligence metrics).

## Simulation control & chaos (🔒, proxies to simulator /admin/*)
`POST /api/sim/run` · `/api/sim/pause` · `/api/sim/step` body `{"n":1}` · `/api/sim/reset` → `{"tick": 43, "status": "PAUSED"}`
`POST /api/chaos/event` body = simulator `/admin/events` body, e.g. `{"type":"demand_spike","start_tick":45,"duration_ticks":12,"parameters":{"region_ids":["region-dhaka"],"multiplier":1.8}}`
`POST /api/chaos/fault` body = simulator `/admin/faults` body, e.g. `{"type":"error_rate","duration_seconds":60,"parameters":{"rate":0.3}}`
`POST /api/chaos/fault/clear` · `GET /api/chaos/events` · `GET /api/chaos/faults`

## Live updates
`GET /api/stream` (SSE): `tick {"tick","service_level"}` · `alert {alert}` · `recommendation {recommendation}` · `status {system status}`.
The dashboard must ALSO poll `/api/state` + `/api/system/status` every 3 s (fallback when the stream drops).
