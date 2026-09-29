# Manual test guide (Ishmam's laptop)

Tick each box as you go. Every step says **what to do** and **what you should see**. Commands work in PowerShell or
Git Bash (use `curl.exe`, not `curl`, in Windows PowerShell). Operator key for testing: `change-me` (from `.env`).

## 0. Start clean
```bash
cd "C:\Users\16IRL8\Downloads\bup final\gta7-fuel-supply"
docker compose up -d --build
docker compose ps
```
- [ ] All services **Up/healthy**: `simulator-api`, `postgres`, `backend` (engine), `api` ×2, `web`, `gateway`, `prometheus`, `grafana`.

| What | URL |
|---|---|
| Operator console | http://localhost |
| API docs (Swagger) | http://localhost/docs |
| System status JSON | http://localhost/api/system/status |
| Grafana | http://localhost/grafana/ (anonymous view; admin/admin to edit) |
| Prometheus | http://localhost/prometheus/ |
| Simulator console | http://localhost:8000/admin |

Reset the simulator to a known state (tick 0, paused):
```bash
curl.exe -X POST -H "X-Operator-Key: change-me" http://localhost/api/sim/reset
```
- [ ] Console top bar shows **Tick 0 · PAUSED · HEALTHY**.

## 1. Operator key
1. Console → top-right **Operator key** → enter `change-me` → Save.
- [ ] The button changes to **Operator**. (Without it, approve / mode / chaos buttons are disabled.)

## 2. Normal operations: Observe → Detect → Predict → Decide
1. **Control & Chaos → Step** a few times (or `Run` for ~5 s, then `Pause`).
- [ ] Tick advances; **Pause stops it immediately** (no extra ticks after you click).
2. **Overview**
- [ ] KPI cards: service level ~100%, unmet 0 L, open alerts, pending recommendations.
- [ ] Network map shows 2 depots → 4 stations with D/P/O fill %; colours match risk.
- [ ] **Situation briefing** shows summary + top risks + recommended actions, badge **AI (LLM)**; actions link to the inbox.
3. **Stations & Depots**
- [ ] Every fuel shows `inventory / capacity` in litres (no "0 L – L"), stockout hours, **24 h stockout risk if no action**.
- [ ] An empty fuel says **STOCKOUT** (not OUTAGE); OUTAGE only for a station that is offline.
4. **History & Forecast**
- [ ] Service-level chart starts at tick 0 of this run; forecast chart has an uncertainty band; MAPE shown.

## 3. Decide → Simulate → Act (human in the loop)
1. **Recommendations** → open the top card.
- [ ] Card shows situation, recommended shipment (qty, depot, route, ETA), **expected impact before → after**, signals,
      constraints, confidence, alternatives, and an **AI (LLM)** explanation.
2. Click **Simulate** in the what-if box.
- [ ] Chart "with vs without shipment"; text "risk X% → Y%" (projection only, nothing sent).
3. **Approve & execute**.
- [ ] Toast "Recommendation #N executed"; card moves to **Executed**. Check it reached the simulator:
      `curl.exe http://localhost:8000/v1/allocations` → newest entry has `idempotency_key` `gta7-rec<N>-q<qty>`.
4. Open another card, type a note, click **Reject**.
- [ ] Toast "rejected"; **History → Decision audit** shows the reject with your note.
5. Toggle **Manual → Assisted**, step a few ticks, then back to **Manual**.
- [ ] In assisted mode only cards with confidence ≥ 0.8 and ≤ 5000 L auto-execute (actor `autopilot` in the audit);
      low-confidence cards stay for human review.
6. Click a **toast** notification.
- [ ] Alert toast opens **Alerts**; recommendation toast opens that card.

## 4. Crisis handling (Control & Chaos → Crisis events)
For each: inject → **Step** 2–4 ticks → check → then **Step** until the event ends.

| Crisis | Inject | You should see |
|---|---|---|
| Demand spike | Demand spike, Dhaka, ×1.8 | Critical **anomalous demand** alerts; cards cite "demand 1.8x normal"; risk rises |
| Route disruption | Route disruption, Gazipur → Mirpur | Disruption alert names the alternative; new cards use **route-patiya-mirpur**; old cards on the closed route disappear from the inbox |
| Depot constraint | Depot constraint, Gazipur | **Bottleneck** alert; cards say "Gazipur Depot constrained"; Mirpur load shifts to Patiya |
| Shipment delay | Shipment delay, 8 ticks | Disruption alerts "supply … delayed"; cards cite "upstream depot supply DELAYED" |
| Station outage | Station outage, Tongi | Critical alert; **no cards for Tongi** while offline |
| Supply shortfall | Supply shortfall, Patiya ×0.4 | Upcoming Patiya supplies shrink; shortage risk rises at Patiya-fed stations |

- [ ] During any crisis, approve a card whose route/depot just changed → it is **blocked** with
      "AVAILABILITY_CHANGED: …" instead of failing at the simulator.

## 5. Resilience (Control & Chaos → Engineering faults, 30–60 s each)
Watch **System Status** and the banner on every page.

| Fault | You should see | Then (after it expires) |
|---|---|---|
| Simulator down | Red banner **Degraded mode … circuit breaker OPEN**, Overall DEGRADED, last state still shown | "Simulator connection recovered" alert, HEALTHY |
| Flaky API (30%) | Mostly healthy; maybe short degraded blips | Recovers on its own |
| Slow API (+1.5 s) | p95 latency rises; with larger delays, degraded mode | Recovers |
| Stale data | Banner **STALE data**, warning alert, Data freshness = STALE | Clears |
| SSE disconnect | (affects new connections) Data keeps updating via polling | — |

- [ ] **Grafana** (http://localhost/grafana/ → GTA7 dashboard): breaker/degraded lines, simulator calls by outcome,
      recoveries counter move during the faults.

## 6. Scaling (engine + API replicas)
```bash
docker compose up -d --scale api=3 --no-recreate
docker compose ps api
curl.exe -s -D - -o NUL http://localhost/api/state        # repeat 4-6 times
```
- [ ] 3 `api` replicas running; the `X-GTA7-Upstream` header **rotates** across replica IPs.
- [ ] A write goes to the engine: `curl.exe -s -D - -o NUL -X POST -H "X-Operator-Key: change-me" -H "Content-Type: application/json" -d "{\"n\":1}" http://localhost/api/sim/step` → one fixed upstream IP.
- [ ] Grafana panels **API replicas up = 3** and **Requests served per replica** show three lines.
- [ ] Prometheus → Status → Targets (http://localhost/prometheus/targets): `gta7-api` lists 3 targets, all UP.

## 7. Load test
```bash
cd "C:\Users\16IRL8\Downloads\bup final\gta7-fuel-supply"
bash loadtest/run.sh 50
```
- [ ] `loadtest/results/50-vus.txt`: `http_req_failed 0.00%`, p95/p99 printed; compare with `docs/LOAD_TEST.md`.

## 8. Race conditions & dispatch limit (Q3 / Q4)
- [ ] Backend tests (includes back-to-back approvals, depot exhaustion, concurrent approvals, idempotency):
  `cd backend && .venv\Scripts\python -m pytest -q tests` → **all pass**.
- [ ] Audit: `curl.exe http://localhost:8000/v1/allocations` → for any depot, the quantities created in the same tick
  never exceed its `dispatch_capacity_per_tick` (Gazipur 12,000 L, Patiya 11,000 L), and
  `curl.exe http://localhost:8000/v1/depots` never shows negative inventory. Details: `docs/TESTING_REPORT.md`.

## 9. AI assistant
1. **AI Assistant** → click a suggested question, then type your own ("Why is Mirpur at risk and what should I do first?").
- [ ] Answer is specific (stations, litres, hours), cites evidence (`recommendation:N`, `alert:N`), badge **AI (LLM)**.
2. **Alerts** → **Explain** on any alert.
- [ ] Plain-language explanation; says so honestly when the cause is unknown.

## 10. Before judging
```bash
curl.exe -X POST -H "X-Operator-Key: change-me" http://localhost/api/sim/reset
curl.exe http://localhost/api/system/status
```
- [ ] Tick 0, PAUSED, overall **healthy**, llm healthy. Browser zoom ~125% for the projector. Operator key entered.
