# Participant Brief — "Fuel Supply Intelligence & Resilience Platform" (summary)
Transcribed from the printed brief (BUP CSE FEST 26 Hackathon Finals). Build. Deploy. Observe. Respond.

**Final challenge:** Build an intelligent Fuel Supply Operations Platform that can observe a simulated fuel
network, identify emerging risks, recommend or simulate operational decisions, withstand disruptions, and
remain observable and usable when components fail. *"Your job is not only to build the system. Your job is to keep it working."*

Engineering loop to demonstrate: **Observe → Detect → Predict → Decide → Simulate → Act → Monitor → Recover**.
Judges must be able to **interact with and observe a working system**. Organizers may inject surprise domain and engineering events during development or judging.

## Evaluation (100%)
| Criterion | % | Assessed |
|---|---|---|
| Working Product & UX | 20 | functional app, operational workflow, usability, completeness |
| Intelligence & Decision Quality | 20 | usefulness/quality of AI/ML/optimization/detection, methodology |
| Architecture & Integration | 15 | backend engineering, simulator integration, component design, coherence |
| DevOps & Engineering Quality | 15 | deployment, automation, testing, maintainability |
| Resilience & Incident Response | 10 | failure handling, crisis response, fallback, recovery |
| Observability & Performance | 10 | monitoring, metrics, logs, health visibility, load testing |
| Demo & Problem Understanding | 10 | clear explanation, constraints, effective demo |

## Required deliverables (§19)
1. Working application (runnable end-to-end) 2. Source repo (code, setup, deps, deployment instructions)
3. Simulator integration 4. Intelligence component 5. Operator interface
6. **Architecture diagram**: simulator → data/backend → intelligence → decision → application → monitoring
7. **Deployment**: reproducible (`docker compose up`) 8. **Observability evidence**: logs, metrics, dashboards, alerts
9. **Resilience demonstration**: response to at least one meaningful failure 10. **Load-test evidence**: workload + measured results
11. Final live demo
Recommended (§20): CI/CD, automated tests, experiment tracking, model versioning, decision audit history, deployment versioning, simulation replay, scenario configuration, automated fallback, rollback.

## Application (§6): a meaningful subset of
current inventory · depot & station status · regional demand · shortage alerts · projected shortage risk · incoming supply ·
disruptions · recommended allocations · expected impact of decisions · system alerts · decision history · service health. Web app recommended.

## Intelligence (§7): at least one meaningful capability
Prediction: demand forecasting, shortage prediction, stockout probability, estimated supply arrival, transport delay prediction.
Detection: anomalous demand, abnormal inventory changes, supply-chain bottlenecks, emerging regional disruptions.
Decision: constrained optimization, heuristic / priority-based allocation, RL (optional), mathematical optimization, hybrid.
GenAI: incident explanation, state summarization, operator investigation assistance, human-readable decision explanations.
**"LLMs should support the operational system rather than merely provide a chatbot around the application."**
RL optional (§8); if used, show why it beats a reasonable heuristic.

## Decision support (§9): recommendations must be inspectable
Example card: station, fuel, projected stockout (hours), current inventory, expected demand, recommended allocation
(qty + source depot), **expected result (stockout risk 72% → 19%)**. Show why at risk, which signals influenced it,
constraints, expected impact, confidence/uncertainty, alternatives. **Humans can inspect important decisions.**

## Crisis handling (§10): system should show
Shipment delay → warning, shortage impact, decision response, recovery · Demand spike → risk change, forecast/detection response,
allocation adaptation · Depot constraint → constraint handling, reallocation, service impact · Regional disruption → alternative
allocation, recovery · Combined crisis → end-to-end resilience and failure boundaries. Show **detect → evaluate → respond → explain → monitor recovery**.

## Resilience (§11): define what happens when things go wrong
ML model unavailable → fallback allocation policy · Invalid simulator response → reject input + raise alert ·
Prediction confidence too low → human review requested · Backend dependency unavailable → retry / cached state / degraded mode.
Mechanisms: fallback, graceful degradation, retries, timeouts, health checks, cached state, validation, circuit breakers, rollback.

## DevOps (§12–13)
Minimum `docker compose up`. Show workflow Source → Build → Test → Package → Deploy → Health Check → Running. CI/CD strongly encouraged
(GitHub Actions). Advanced (optional, only if it helps): K8s, Helm, IaC, GitOps, rollback, blue/green, canary, autoscaling, queues.

## Observability (§14–15)
Application: request rate, latency, error rate, availability · System: CPU, memory · Intelligence: prediction error, model confidence,
shortage-alert rate, decision frequency, fallback activation · Logs: important actions, integration failures, decision events, recoveries.
Tools suggested: Prometheus, Grafana, OpenTelemetry, Loki, ELK, Jaeger. **System status panel** (Backend API, Database, Fuel Simulator,
Prediction Service, Decision Engine = Healthy; p95 latency; error rate).

## Load testing (§17)
Load-test ≥1 meaningful path (prediction API, decision API, simulator integration, dashboard backend, end-to-end decision).
Report avg, p50, p95, p99, throughput, error rate, concurrency, resource usage. Explain behavior and limits.

## Security & hygiene (§18) / Guardrails (§24)
No hard-coded secrets, validate external input, handle failed requests, document config, don't expose credentials,
**restrict sensitive operator actions**. Simulation only; label simulated results; document assumptions;
**preserve human review for consequential simulated decisions**.

## Suggested demo story (§22)
1 Normal ops → 2 Operator dashboard → 3 Demand starts increasing → 4 System detects risk → 5 Intelligence predicts shortage →
6 Allocation recommendation generated → 7 Operator inspects recommendation → 8 Allocation is simulated → 9 Crisis event occurs →
10 System adapts → 11 App/dependency failure injected → 12 Monitoring detects failure → 13 Fallback/recovery activates → 14 Operations continue.
