import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate } from "k6/metrics";

// ============================================================
// CONFIGURATION
// ============================================================

const BASE_URL =
  __ENV.BASE_URL || "http://host.docker.internal:8090";

const TEST_VUS = Number(__ENV.VUS || 10);
const TEST_DURATION = __ENV.DURATION || "30s";

// Valid deterministic what-if request.
// This endpoint performs simulation only and does not create an allocation.
const SIMULATE_BODY = JSON.stringify({
  station_id: "station-mirpur",
  fuel_type: "DIESEL",
  source_depot_id: "depot-gazipur",
  route_id: "route-gazipur-mirpur",
  quantity: 3000,
});

const JSON_HEADERS = {
  headers: {
    "Content-Type": "application/json",
  },
};

// ============================================================
// CUSTOM METRICS
// ============================================================

const stateLatency = new Trend("state_latency", true);
const simulateLatency = new Trend("simulate_latency", true);
const statusLatency = new Trend("status_latency", true);

const stateErrors = new Rate("state_errors");
const simulateErrors = new Rate("simulate_errors");
const statusErrors = new Rate("status_errors");

// ============================================================
// TEST CONFIGURATION
// ============================================================

export const options = {
  vus: TEST_VUS,
  duration: TEST_DURATION,

  summaryTrendStats: [
    "avg",
    "min",
    "med",
    "p(90)",
    "p(95)",
    "p(99)",
    "max",
  ],

  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<2000"],
  },
};

// ============================================================
// LOAD TEST
// ============================================================

export default function () {
  // ----------------------------------------------------------
  // 1. GET /api/state
  // ----------------------------------------------------------

  let response = http.get(`${BASE_URL}/api/state`, {
    tags: {
      endpoint: "state",
    },
  });

  stateLatency.add(response.timings.duration);

  const stateOK = check(response, {
    "GET /api/state returned 200": (r) => r.status === 200,
  });

  stateErrors.add(!stateOK);

  // ----------------------------------------------------------
  // 2. POST /api/recommendations/simulate
  // ----------------------------------------------------------

  response = http.post(
    `${BASE_URL}/api/recommendations/simulate`,
    SIMULATE_BODY,
    {
      ...JSON_HEADERS,
      tags: {
        endpoint: "simulate",
      },
    }
  );

  simulateLatency.add(response.timings.duration);

  const simulateOK = check(response, {
    "POST /api/recommendations/simulate returned 200": (r) =>
      r.status === 200,
  });

  simulateErrors.add(!simulateOK);

  // ----------------------------------------------------------
  // 3. GET /api/system/status
  // ----------------------------------------------------------

  response = http.get(`${BASE_URL}/api/system/status`, {
    tags: {
      endpoint: "status",
    },
  });

  statusLatency.add(response.timings.duration);

  const statusOK = check(response, {
    "GET /api/system/status returned 200": (r) =>
      r.status === 200,
  });

  statusErrors.add(!statusOK);

  // Prevent each VU from becoming an unlimited tight loop.
  sleep(0.5);
}