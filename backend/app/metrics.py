"""Prometheus metrics: application, domain and intelligence layers (brief §14)."""
import time
from collections import deque

from prometheus_client import Counter, Gauge, Histogram

# --- simulator integration ---
SIM_REQUESTS = Counter("gta7_sim_requests_total", "Calls to the simulator", ["method", "endpoint", "outcome"])
SIM_LATENCY = Histogram("gta7_sim_request_seconds", "Simulator call latency", ["endpoint"],
                        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8))
CIRCUIT_STATE = Gauge("gta7_circuit_breaker_state", "0=closed 1=half_open 2=open")
SSE_CONNECTED = Gauge("gta7_sse_connected", "1 if simulator SSE stream is connected")
STALE_DATA = Gauge("gta7_stale_data", "1 if the simulator reports stale data")
DEGRADED = Gauge("gta7_degraded_mode", "1 if serving cached state in degraded mode")
INVALID_RESPONSES = Counter("gta7_invalid_sim_responses_total", "Simulator responses rejected by validation", ["endpoint"])
RECOVERIES = Counter("gta7_recoveries_total", "Recoveries from degraded mode")

# --- domain ---
SIM_TICK = Gauge("gta7_sim_tick", "Current simulator tick")
SERVICE_LEVEL = Gauge("gta7_service_level", "Simulator service level (served / total demand)")
UNMET_LITERS = Gauge("gta7_unmet_demand_liters", "Cumulative unmet demand")
OPEN_ALERTS = Gauge("gta7_open_alerts", "Open alerts", ["severity"])
PENDING_RECS = Gauge("gta7_pending_recommendations", "Recommendations waiting for review")
STATION_INVENTORY = Gauge("gta7_station_inventory_liters", "Station inventory", ["station", "fuel"])
DEPOT_INVENTORY = Gauge("gta7_depot_inventory_liters", "Depot inventory", ["depot", "fuel"])

# --- intelligence ---
RECOMMENDATIONS = Counter("gta7_recommendations_total", "Recommendations generated", ["mode"])
DECISIONS = Counter("gta7_decisions_total", "Operator/autopilot decisions", ["actor", "action", "result"])
SHORTAGE_ALERTS = Counter("gta7_shortage_alerts_total", "Shortage alerts raised")
ALERTS_RAISED = Counter("gta7_alerts_total", "Alerts raised", ["kind", "severity"])
FALLBACK_ACTIVATIONS = Counter("gta7_fallback_activations_total", "Fallback policy activations", ["component"])
PREDICTION_MAPE = Gauge("gta7_prediction_mape", "Recent forecast mean absolute percentage error")
MODEL_CONFIDENCE = Gauge("gta7_model_confidence", "Average confidence of latest recommendations")
PIPELINE_SECONDS = Histogram("gta7_pipeline_seconds", "Intelligence pipeline duration per tick",
                             buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5))
LLM_CALLS = Counter("gta7_llm_calls_total", "LLM calls", ["outcome"])


class RequestWindow:
    """Rolling window of API request timings for the in-app system status panel."""

    def __init__(self, size: int = 2000):
        self.items: deque[tuple[float, float, int]] = deque(maxlen=size)

    def add(self, duration_s: float, status: int) -> None:
        self.items.append((time.time(), duration_s, status))

    def stats(self, window_s: float = 300) -> dict:
        cutoff = time.time() - window_s
        recent = [(d, s) for t, d, s in self.items if t >= cutoff]
        if not recent:
            return {"p95_latency_ms": 0.0, "p50_latency_ms": 0.0, "error_rate": 0.0, "requests": 0}
        durs = sorted(d for d, _ in recent)
        errors = sum(1 for _, s in recent if s >= 500)

        def pct(p: float) -> float:
            return round(durs[min(len(durs) - 1, int(p * len(durs)))] * 1000, 1)

        return {"p95_latency_ms": pct(0.95), "p50_latency_ms": pct(0.5),
                "error_rate": round(errors / len(recent), 4), "requests": len(recent)}


REQUEST_WINDOW = RequestWindow()
