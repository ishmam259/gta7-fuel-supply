# Resilience Test Report

## Environment

- Simulator: BUP Fuel Supply Simulator 1.0.0
- Platform: local Docker deployment (`docker compose up`: simulator, backend, web console, Prometheus, Grafana)
- Test date: 29 September 2026

## Method

Faults were injected through the simulator's `/admin/faults` endpoint (via our operator-only
`/api/chaos/fault` proxy or the console's Control & Chaos page) while platform traffic continued
through `/v1/*`. The `/admin/*` API bypasses injected faults, while `/v1/*` is affected.
We observed the operator console (System Status, Overview, Alerts) and the Grafana
"GTA7 Fuel Ops – Platform Health" dashboard during and after each fault.
Tools: `scripts/faults/test_fault.py`, presets in `backend/app/scenarios.py`.

## Results

| Fault | Configuration | Expected Platform Behaviour | Actual Behaviour | Result |
|---|---|---|---|---|
| Unavailable | all `/v1` calls 503, 40 s | Retry, circuit breaker, cached state | Retries with backoff; after 2 failed syncs **degraded mode** (red banner "circuit breaker OPEN – serving cached state, auto-execution paused", critical alert, last known state still shown); breaker **OPEN** after ~8 s (Grafana breaker = 2, calls switch to `circuit_open`); half-open probe; **automatic recovery** when the fault ends ("Simulator connection recovered" alert, breaker back to 0, `recoveries` counter +1) | PASS |
| Error rate | 50 % random 503, 45 s | Retry transient failures | Retries absorb most errors (503 outcomes visible in Grafana); short degraded blips when a whole sync fails, each followed by automatic recovery; no crash, no wrong decisions; operator API stayed at 0 % 5xx | PASS |
| Latency | +6000 ms per call (> 4 s client timeout), 50 s | Continue operating, latency visible | Calls time out instead of hanging; after ~25–30 s (3 attempts × 2 syncs) degraded mode with "simulator link unstable – serving cached state"; overview KPIs and network map stay usable; the AI briefing reports the integration failure; recovers automatically | PASS |
| Stale data | `X-Simulator-Stale: true`, 45 s | Detect stale header and warn operator | Warning alert "Simulator reports stale data – values may lag; decisions use the latest trusted state", banner in the console, Data freshness = **STALE**; clears automatically when the fault ends | PASS |
| Stream disconnect | new `/v1/stream` connections refused, 90 s | Poll fallback + reconnect + REST resync | Backend SSE link shows **RECONNECTING** (reconnect with backoff), while REST polling keeps state current: simulator stepped to tick 3 during the fault and Data freshness stayed **HEALTHY** (synced 2 s ago); overall status HEALTHY | PASS |
| Invalid response | (unit test) malformed body / out-of-range values | Reject input + raise alert | Schema validation rejects the response, last good state kept, `integration_failure` alert raised (`tests/test_sim_client.py`) | PASS |
| ML / optimiser failure | (unit + code path) exception in `app.intel` | Fallback allocation policy | Rule-based fallback policy used automatically, `gta7_fallback_activations_total` incremented, "Fallback allocation policy active" alert (`tests/test_fallback_policy.py`) | PASS |

## Evidence

Screenshots are stored under `docs/evidence/`:

| Scenario | Console (localhost:3000) | Grafana (localhost:3001) |
|---|---|---|
| Unavailable | `fault-unavailable-console-breaker-open.jpg`, `fault-unavailable-dashboard.png` | `fault-unavailable-grafana-breaker-open.jpg`, `fault-unavailable-grafana.png` |
| Unavailable – recovery | `fault-unavailable-recovery-console.jpg` | `fault-unavailable-recovery-grafana.jpg` |
| Error rate 50 % | – | `fault-error-rate-50-grafana.jpg` |
| Latency 6 s | `fault-latency-6s-console.jpg` | – |
| Stale data | `fault-stale-data-alerts.jpg`, `fault-stale-data-system.jpg` | – |
| Stream disconnect | `fault-stream-disconnect-system.jpg` | – |
| Normal operation | – | `grafana_normal.png` |

## Findings

- Every injected failure is **detected, shown to the operator, contained and recovered from automatically**;
  the console never goes blank: it always shows the last trusted state and says clearly that it is degraded or stale.
- **Auto-execution is paused in degraded mode**, so no decision is made on data we cannot trust.
- Hysteresis (2 failed syncs before degraded mode) prevents alert flapping on single transient errors;
  at 50 % error rate some short degraded episodes still occur, and each one recovers on its own.
- Found by testing: the simulator's database connection pool is small (5 + 10 overflow). Uncapped parallel reads
  made the simulator itself time out. The backend now caps concurrent simulator connections at 4 and caches the
  health probe, so operator load does not become simulator load (see `LOAD_TEST.md`).
- Found by testing: the health probe (which bypasses faults) used to reset the stale flag; fixed and covered by a test.

## Known limitations

- Detection of a total outage takes a few seconds (retries + 2 failed syncs) by design; latency faults take
  ~25–30 s to declare degraded mode because each call waits for its timeout.
- A stream disconnect only affects new connections; an already-open stream stays up (verified by forcing a
  reconnect with a backend restart during the fault).
- Single backend instance in this deployment: if the backend itself dies, Docker restarts it
  (`restart: unless-stopped`) and it resyncs from the simulator, but there is no hot standby.
