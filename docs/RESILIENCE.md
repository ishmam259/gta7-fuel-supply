# Resilience Test Report

## Environment

- Simulator: BUP Fuel Supply Simulator 1.0.0
- Platform: local Docker deployment
- Test date: 29 September 2026

## Method

Faults were injected through the simulator's `/admin/faults`
endpoint while platform traffic continued through `/v1/*`.

The `/admin/*` API bypasses injected faults, while `/v1/*`
is affected.

## Results

| Fault | Configuration | Expected Platform Behaviour | Actual Behaviour | Result |
|---|---|---|---|---|
| Latency | 1000 ms | Continue operating, latency visible | TODO | TODO |
| Unavailable | 30 sec | Retry, circuit breaker, cached state | TODO | TODO |
| Error rate | 50% | Retry transient failures | TODO | TODO |
| Stale data | 30 sec | Detect stale header and warn operator | TODO | TODO |
| Stream disconnect | 30 sec | Poll fallback + reconnect + REST resync | TODO | TODO |

## Evidence

Screenshots and logs are stored under:

`docs/evidence/`

## Findings

TODO after testing.

## Known limitations

TODO after testing.