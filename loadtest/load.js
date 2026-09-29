import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate } from "k6/metrics";

// Mixed operator workload: read state, run a what-if, read system status, think 0.5 s.
// /api/recommendations/simulate is projection-only: it never creates an allocation.
const BASE_URL = __ENV.BASE_URL || "http://host.docker.internal:8090";
const TEST_VUS = Number(__ENV.VUS || 10);
const TEST_DURATION = __ENV.DURATION || "30s";

const SIMULATE_BODY = JSON.stringify({
  station_id: "station-mirpur",
  fuel_type: "DIESEL",
  source_depot_id: "depot-gazipur",
  route_id: "route-gazipur-mirpur",
  quantity: 3000,
});
const JSON_HEADERS = { headers: { "Content-Type": "application/json" } };

const stateLatency = new Trend("state_latency", true);
const simulateLatency = new Trend("simulate_latency", true);
const statusLatency = new Trend("status_latency", true);
const stateErrors = new Rate("state_errors");
const simulateErrors = new Rate("simulate_errors");
const statusErrors = new Rate("status_errors");

export const options = {
  vus: TEST_VUS,
  duration: TEST_DURATION,
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<2000"],
  },
};

export default function () {
  let r = http.get(`${BASE_URL}/api/state`, { tags: { endpoint: "state" } });
  stateLatency.add(r.timings.duration);
  stateErrors.add(!check(r, { "GET /api/state returned 200": (x) => x.status === 200 }));

  r = http.post(`${BASE_URL}/api/recommendations/simulate`, SIMULATE_BODY, { ...JSON_HEADERS, tags: { endpoint: "simulate" } });
  simulateLatency.add(r.timings.duration);
  simulateErrors.add(!check(r, { "POST /api/recommendations/simulate returned 200": (x) => x.status === 200 }));

  r = http.get(`${BASE_URL}/api/system/status`, { tags: { endpoint: "status" } });
  statusLatency.add(r.timings.duration);
  statusErrors.add(!check(r, { "GET /api/system/status returned 200": (x) => x.status === 200 }));

  sleep(0.5);
}
