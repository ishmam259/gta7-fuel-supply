# Load test (brief §17)

## Workload
Tool: **k6** (`grafana/k6` Docker image), script [`loadtest/load.js`](../loadtest/load.js), runner [`loadtest/run.sh`](../loadtest/run.sh).
Each virtual user (VU) loops over a realistic operator workflow, then thinks for 0.5 s:

1. `GET /api/state`: full network snapshot (what the dashboard polls)
2. `POST /api/recommendations/simulate`: what-if projection (runs the intelligence model; no writes, no allocations)
3. `GET /api/system/status`: health panel (component health, p95, error rate)

Fair comparison: simulator reset to the same seed and **paused at tick 0**, no crises or faults, same machine,
same endpoint mix, 30 s per run. **Only variable: 10 → 25 → 50 → 100 concurrent VUs.**
CPU/memory sampled continuously with `docker stats` during each run.

Run it: `./loadtest/run.sh <vus> [duration]` → `loadtest/results/<vus>-vus.txt` (k6 output) and `<vus>-vus-stats.txt` (docker stats).

## Results (all requests)
| VUs | avg | p50 | p95 | p99 | max | throughput | error rate | backend peak CPU / mem | simulator peak CPU / mem |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 8.8 ms | 5.9 ms | 22.8 ms | 57.1 ms | 85 ms | 56 req/s | **0.00%** | 30% / 123 MiB | 10% / 68 MiB |
| 25 | 14.7 ms | 9.1 ms | 43.6 ms | 97.9 ms | 234 ms | 136 req/s | **0.00%** | 57% / 124 MiB | 6% / 67 MiB |
| 50 | 42.5 ms | 29.8 ms | 117.9 ms | 223.9 ms | 572 ms | 236 req/s | **0.00%** | 92% / 125 MiB | 8% / 68 MiB |
| 100 | 240.9 ms | 192.3 ms | 558.8 ms | 1.04 s | 1.54 s | 243 req/s | **0.00%** | 103% / 137 MiB | 17% / 68 MiB |

Per endpoint (p50 / p95 / p99):

| VUs | `/api/state` | `/api/recommendations/simulate` | `/api/system/status` |
|---:|---|---|---|
| 10 | 4.4 / 17.9 / 36.6 ms | 9.4 / 40.8 / 77.6 ms | 3.9 / 13.8 / 32.6 ms |
| 25 | 7.2 / 36.3 / 88.7 ms | 16.2 / 75.5 / 110.3 ms | 6.1 / 22.4 / 49.3 ms |
| 50 | 25.0 / 100.4 / 237.1 ms | 52.5 / 140.7 / 243.9 ms | 16.5 / 66.8 / 121.0 ms |
| 100 | 163.4 / 409.1 / 934.9 ms | 327.8 / 565.9 / 611.9 ms | 114.1 / 748.2 / 1200 ms |

All k6 thresholds passed at every level (`http_req_failed < 5%`, `p95 < 2 s`).

## What this tells us (behaviour and limits)
- **No errors at any load**: 20,562 requests across the four runs, 0 failed. Under overload the system slows
  down but never drops requests.
- **Throughput scales almost linearly up to ~240 req/s (50 VUs)**, then **saturates**: at 100 VUs throughput stays
  at ~243 req/s while latency grows (requests queue). The knee is between 50 and 100 VUs.
- **The bottleneck is backend CPU**: it reaches ~100% of one core at 50–100 VUs because the API runs as a single
  process (the what-if endpoint is the most CPU-heavy: it runs the forecast model). Memory is flat (~125–137 MiB).
- **The simulator is protected**: its CPU stays at 6–17% because the backend serves reads from its cached, validated
  snapshot, caps concurrent simulator connections (the simulator's DB pool is small) and caches the health probe.
  Operator load does not turn into simulator load.
- **Practical capacity**: an operations centre has a handful of operators; at 10 concurrent users p95 is 23 ms.

## How we would scale further
Run several API worker processes behind a load balancer (the API is stateless apart from the database), move the
tick engine into its own single worker process, move SQLite to Postgres, and cache the what-if forecast per tick.

## Evidence
- Raw k6 output: `loadtest/results/{10,25,50,100}-vus.txt`; CPU/memory samples: `loadtest/results/*-vus-stats.txt`
- Grafana during the 100 VU run: [`evidence/grafana-load-test-100vus.jpg`](evidence/grafana-load-test-100vus.jpg)
  (request rate climbing to ~60 req/s per handler, p95 rising, **no 5xx**) and
  [`evidence/grafana-load-test-100vus-resources.jpg`](evidence/grafana-load-test-100vus-resources.jpg) (CPU, memory, domain panels)
