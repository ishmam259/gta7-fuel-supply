# Tasks — who owns what (build until 14:00, freeze 14:00, submit by 15:15)
Each person works ONLY in their folders, on their own branch, and merges to `main` every ~45 min
(`git pull --rebase origin main` first). Shared files (`docs/API_CONTRACT.md`, `CLAUDE.md`, root `docker-compose.yml`, `.env.example`) → ask Ishmam.

Checkpoint 1 at **12:00**: full loop works end-to-end (state → risk → recommendation → approve → allocation visible in simulator).

## A · Ishmam Tahmid — backend core, integration, DevOps (branch `be-core`)
Owns `backend/app/` except `backend/app/intel/` · `docker-compose.yml` · `.github/workflows/` · `backend/Dockerfile`
1. FastAPI skeleton, settings from env, JSON logging, `/api/health`, CORS for :3000. **(first 30 min, push early)**
2. Resilient simulator client: httpx, timeouts, retry+exponential backoff on 503/timeouts, circuit breaker, Pydantic validation of every response, `X-Simulator-Stale` handling, cached last-good state.
3. State sync: SSE listener with reconnect + REST resync on each tick; poll fallback. `/api/state`, `/api/metrics/history`.
4. SQLite (SQLModel): recommendations, decisions (audit), alerts, metrics_history.
5. Executor + approval flow: `/api/recommendations*`, `/api/decisions`, `/api/mode`; idempotency key; map every simulator 409/503 code to a clear failure_reason.
6. `/api/system/status`, `/metrics` (prometheus-fastapi-instrumentator + custom counters/gauges), `/api/stream`.
7. Chaos/sim proxies `/api/sim/*`, `/api/chaos/*` behind `X-Operator-Key`.
8. `docker-compose.yml` with simulator + backend + web + prometheus + grafana; healthchecks; GitHub Actions CI (lint, pytest, docker build, compose up + health check).

## B · Farhan Tahsin Khan — intelligence (branch `intel`)
Owns `backend/app/intel/` (pure Python functions + Pydantic models; Ishmam's code calls them)
1. `forecast.py`: per (station, fuel) demand per tick for next 16 ticks from demand-history (hour-of-day profile × demand_multiplier), residual std, rolling MAPE (prediction-error metric).
2. `risk.py`: stockout hours + stockout probability, risk level ok/watch/critical/outage, supply ETA incl. DELAYED arrivals.
3. `detect.py`: anomalous demand (z-score), abnormal inventory change, bottleneck (depot dispatch saturation / low depot stock), disruption detection from events/route/station/depot status → alert objects.
4. `planner.py`: priority heuristic + constrained optimizer (scipy `linprog` HiGHS optional), obeys ALL simulator limits, backup routes, alternatives, expected impact (prob before→after), confidence; `fallback_policy()` rule-based used when forecast fails.
5. `genai.py`: Gemini (fallback Groq, then template) for recommendation explanations, incident explanation, situation briefing, investigation assistant answering from current state/alerts/recommendations (not a free chatbot). Always return `source: llm|template`.
6. Unit tests with a fixed snapshot fixture (`backend/tests/intel/`). Key function signatures agreed with Ishmam in the first 30 min, written at the top of `backend/app/intel/__init__.py`.

## C · Mahmudul Hasan Sakib — operator dashboard (branch `web`)
Owns `web/` (Next.js + Tailwind + shadcn; scaffold with prep/SCAFFOLD_RECIPES §1)
1. API client from `docs/API_CONTRACT.md` with **mock mode** (contract example JSON) until backend is ready; `NEXT_PUBLIC_API_URL`.
2. Overview: KPI cards (service level, unmet L, open alerts, pending recs), network map/diagram (2 depots → 4 stations, route status colors), "SIMULATED" badge, degraded-mode banner.
3. Stations & depots: inventory bars per fuel vs capacity, risk badges, stockout hours, incoming supply, in-transit.
4. Alerts panel + Recommendations inbox: inspect card (situation, signals, constraints, confidence, alternatives, expected impact risk before→after, explanation), what-if simulate, approve/reject (operator key), mode toggle.
5. Decision history (audit), service-level chart over ticks, forecast chart.
6. System Status page (components, circuit breaker, p95, error rate, fallbacks) + link to Grafana.
7. Chaos/Control panel (run/pause/step, inject event/fault presets) for the demo. AI briefing + investigation box.
8. `web/Dockerfile`.

## D · Kazi Badrul Hasan — crisis, resilience, observability evidence, load test, pitch (branch `ops`)
Owns `ops/` (prometheus.yml, grafana provisioning + dashboard JSON), `scripts/`, `loadtest/`, `docs/RESILIENCE.md`, `docs/LOAD_TEST.md`, README sections, slides
1. Crisis scenario scripts (`scripts/scenarios/*.py` or `.sh` using the admin API): shipment delay, demand spike, depot constraint, regional/route disruption, combined crisis — each with expected system behavior.
2. Fault drills: latency, unavailable, error_rate, stale_data, stream_disconnect → record what the platform shows (screenshots/logs) in `docs/RESILIENCE.md` (the §11 table).
3. Prometheus + Grafana provisioning: dashboards for request rate, latency p50/p95, error rate, CPU/mem, domain + intelligence metrics (service level, open alerts, fallback activations, decision frequency, prediction error).
4. Load test with k6 (docker `grafana/k6`) or Locust on `/api/state`, `/api/recommendations/simulate`, `/api/system/status`: report avg/p50/p95/p99, throughput, error rate, concurrency levels, CPU/mem → `docs/LOAD_TEST.md`.
5. A/B evidence: same seed + same crisis script, service level with platform vs no action.
6. From 13:30: README (setup, architecture diagram, credits), slides (prep/GTA7_Pitch_Template.pptx), `docs/DEMO_SCRIPT.md` following brief §22.
