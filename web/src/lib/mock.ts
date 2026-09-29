// Mock responses = the example JSON from docs/API_CONTRACT.md, slightly widened so every screen has content.
// Used only for endpoints listed in NEXT_PUBLIC_MOCK_ENDPOINTS (or all when NEXT_PUBLIC_MOCK=1).
import type {
  Alert, AssistantAnswer, Briefing, Decision, Forecast, IncidentExplanation, MetricPoint, Mode,
  NetworkState, Recommendation, SimulateResult, SystemStatus,
} from "./types";

export const mockState: NetworkState = {
  instance: { tick: 42, sim_time: "2026-01-01T10:30:00", status: "RUNNING" },
  metrics: { service_level: 0.981, served_demand_liters: 12345.6, unmet_demand_liters: 234.5, allocation_liters: 9800, allocation_failures: 2 },
  regions: [
    { id: "region-dhaka", name: "Dhaka Division", demand_factor: 1.0, demand_last_4h: { DIESEL: 4200, PETROL: 5100, OCTANE: 2300 } },
    { id: "region-chattogram", name: "Chattogram Division", demand_factor: 1.0, demand_last_4h: { DIESEL: 3900, PETROL: 3300, OCTANE: 1400 } },
  ],
  depots: [
    { id: "depot-gazipur", name: "Gazipur Depot", region_id: "region-dhaka", status: "OPEN", dispatch_capacity_per_tick: 12000, dispatch_used_this_tick: 3000,
      capacity: { DIESEL: 90000, PETROL: 70000, OCTANE: 45000 }, inventory: { DIESEL: 60000, PETROL: 45000, OCTANE: 26000 } },
    { id: "depot-patiya", name: "Patiya Depot", region_id: "region-chattogram", status: "OPEN", dispatch_capacity_per_tick: 10000, dispatch_used_this_tick: 0,
      capacity: { DIESEL: 80000, PETROL: 60000, OCTANE: 40000 }, inventory: { DIESEL: 52000, PETROL: 21000, OCTANE: 18000 } },
  ],
  stations: [
    { id: "station-mirpur", name: "Mirpur Fuel Station", region_id: "region-dhaka", status: "OPEN", demand_profile: "urban_high", demand_multiplier: 1.0,
      capacity: { DIESEL: 15000, PETROL: 14000, OCTANE: 9000 }, inventory: { DIESEL: 9000, PETROL: 9000, OCTANE: 5000 },
      risk: { DIESEL: { level: "ok", stockout_hours: 30.5, stockout_prob: 0.02 }, PETROL: { level: "watch", stockout_hours: 9.1, stockout_prob: 0.21 }, OCTANE: { level: "critical", stockout_hours: 3.2, stockout_prob: 0.74 } } },
    { id: "station-tongi", name: "Tongi Fuel Station", region_id: "region-dhaka", status: "OPEN", demand_profile: "highway", demand_multiplier: 1.0,
      capacity: { DIESEL: 18000, PETROL: 10000, OCTANE: 6000 }, inventory: { DIESEL: 12000, PETROL: 6500, OCTANE: 4100 },
      risk: { DIESEL: { level: "ok", stockout_hours: 22, stockout_prob: 0.04 }, PETROL: { level: "ok", stockout_hours: 18, stockout_prob: 0.06 }, OCTANE: { level: "ok", stockout_hours: 26, stockout_prob: 0.03 } } },
    { id: "station-coxsbazar", name: "Cox's Bazar Station", region_id: "region-chattogram", status: "OPEN", demand_profile: "urban_high", demand_multiplier: 1.0,
      capacity: { DIESEL: 14000, PETROL: 12000, OCTANE: 8000 }, inventory: { DIESEL: 7000, PETROL: 3000, OCTANE: 4200 },
      risk: { DIESEL: { level: "ok", stockout_hours: 16, stockout_prob: 0.08 }, PETROL: { level: "watch", stockout_hours: 7.5, stockout_prob: 0.33 }, OCTANE: { level: "ok", stockout_hours: 20, stockout_prob: 0.05 } } },
    { id: "station-karnaphuli", name: "Karnaphuli Fuel Station", region_id: "region-chattogram", status: "OPEN", demand_profile: "industrial", demand_multiplier: 1.0,
      capacity: { DIESEL: 20000, PETROL: 8000, OCTANE: 5000 }, inventory: { DIESEL: 14000, PETROL: 5000, OCTANE: 3000 },
      risk: { DIESEL: { level: "ok", stockout_hours: 28, stockout_prob: 0.02 }, PETROL: { level: "ok", stockout_hours: 21, stockout_prob: 0.04 }, OCTANE: { level: "ok", stockout_hours: 30, stockout_prob: 0.01 } } },
  ],
  routes: [
    { id: "route-gazipur-mirpur", source_depot_id: "depot-gazipur", destination_station_id: "station-mirpur", transit_ticks: 2, max_shipment: 7000, status: "DISRUPTED" },
    { id: "route-gazipur-tongi", source_depot_id: "depot-gazipur", destination_station_id: "station-tongi", transit_ticks: 1, max_shipment: 8000, status: "AVAILABLE" },
    { id: "route-patiya-coxsbazar", source_depot_id: "depot-patiya", destination_station_id: "station-coxsbazar", transit_ticks: 1, max_shipment: 7000, status: "AVAILABLE" },
    { id: "route-patiya-karnaphuli", source_depot_id: "depot-patiya", destination_station_id: "station-karnaphuli", transit_ticks: 1, max_shipment: 7000, status: "AVAILABLE" },
    { id: "route-patiya-mirpur", source_depot_id: "depot-patiya", destination_station_id: "station-mirpur", transit_ticks: 4, max_shipment: 6000, status: "AVAILABLE" },
    { id: "route-gazipur-karnaphuli", source_depot_id: "depot-gazipur", destination_station_id: "station-karnaphuli", transit_ticks: 5, max_shipment: 6000, status: "AVAILABLE" },
  ],
  in_transit: [{ id: 17, route_id: "route-gazipur-tongi", fuel_type: "DIESEL", quantity: 6000, status: "IN_TRANSIT", expected_arrival_tick: 44 }],
  upcoming_supply: [{ id: "supply-005", depot_id: "depot-patiya", fuel_type: "PETROL", quantity: 18000, planned_tick: 60, status: "DELAYED" }],
  active_events: [{ id: 3, type: "route_disruption", start_tick: 40, end_tick: 52, status: "ACTIVE", parameters: { route_ids: ["route-gazipur-mirpur"] } }],
  data_freshness: { stale: false, degraded: false, last_sync_tick: 42, last_sync_at: "2026-09-29T10:12:00Z" },
};

const curve = (base: number, n = 16) => Array.from({ length: n }, (_, i) => Math.round(base * (1 + 0.35 * Math.sin((i + 2) / 3)) * 10) / 10);

export const mockForecast: Forecast[] = mockState.stations.flatMap((s) =>
  (["DIESEL", "PETROL", "OCTANE"] as const).map((f, k) => {
    const per = curve(40 + 15 * k + s.id.length);
    return { station_id: s.id, fuel_type: f, horizon_ticks: 16, per_tick: per, lower: per.map((v) => Math.round(v * 0.8)), upper: per.map((v) => Math.round(v * 1.2)), mape_recent: 0.08 };
  }),
);

export const mockMetricsHistory: MetricPoint[] = Array.from({ length: 42 }, (_, i) => ({
  tick: i + 1,
  service_level: Math.min(1, 0.995 - (i > 30 ? (i - 30) * 0.002 : 0)),
  unmet_demand_liters: i > 30 ? (i - 30) * 20 : 0,
  allocation_liters: 8000 + (i % 5) * 400,
  open_alerts: i > 30 ? 3 : 1,
}));

export const mockAlerts: Alert[] = [
  { id: 9, tick: 42, severity: "critical", kind: "shortage_risk", entity: { type: "station", id: "station-mirpur", fuel_type: "OCTANE" },
    title: "Octane stockout in 3.2 h at Mirpur", detail: "Demand 1.8x normal (demand_spike, Dhaka)", status: "open", created_at: "2026-09-29T10:12:00Z" },
  { id: 8, tick: 40, severity: "warning", kind: "disruption", entity: { type: "route", id: "route-gazipur-mirpur" },
    title: "Route Gazipur → Mirpur disrupted", detail: "route_disruption event until tick 52", status: "open", created_at: "2026-09-29T10:10:00Z" },
  { id: 7, tick: 38, severity: "info", kind: "recovery", entity: { type: "system", id: "simulator" },
    title: "Simulator connection recovered", detail: "Circuit breaker closed after half-open probe", status: "resolved", created_at: "2026-09-29T10:05:00Z" },
];

export const mockRecommendations: Recommendation[] = [
  {
    id: 21, tick: 42, status: "pending", mode: "optimizer", station_id: "station-mirpur", fuel_type: "OCTANE",
    allocation: { source_depot_id: "depot-gazipur", route_id: "route-gazipur-mirpur", quantity: 5000, eta_tick: 44 },
    situation: { current_inventory: 5000, expected_demand_next_4h: 7400, projected_stockout_hours: 3.2 },
    expected_impact: { stockout_prob_before: 0.74, stockout_prob_after: 0.12, unmet_liters_avoided: 2400 },
    confidence: 0.86, requires_human_review: false,
    signals: ["demand 1.8x forecast (anomaly z=3.1)", "active demand_spike region-dhaka"],
    constraints: ["route max 7000 L", "depot dispatch left this tick 9000 L"],
    alternatives: [{ source_depot_id: "depot-patiya", route_id: "route-patiya-mirpur", quantity: 5000, eta_tick: 46, stockout_prob_after: 0.31 }],
    explanation: "Mirpur will run out of Octane in about 3 hours because demand is 1.8x normal. Sending 5,000 L from Gazipur arrives at tick 44 and cuts stockout risk from 74% to 12%.",
    sim_allocation_id: null, failure_reason: null,
  },
  {
    id: 20, tick: 41, status: "pending", mode: "heuristic", station_id: "station-coxsbazar", fuel_type: "PETROL",
    allocation: { source_depot_id: "depot-patiya", route_id: "route-patiya-coxsbazar", quantity: 4000, eta_tick: 42 },
    situation: { current_inventory: 3000, expected_demand_next_4h: 4100, projected_stockout_hours: 7.5 },
    expected_impact: { stockout_prob_before: 0.33, stockout_prob_after: 0.07, unmet_liters_avoided: 900 },
    confidence: 0.62, requires_human_review: true,
    signals: ["supply-005 PETROL DELAYED at depot-patiya"],
    constraints: ["depot PETROL stock 21000 L", "station headroom 9000 L"],
    alternatives: [],
    explanation: "Low confidence: the delayed Patiya petrol shipment makes the depot tight. Human review requested.",
    sim_allocation_id: null, failure_reason: null,
  },
  {
    id: 18, tick: 36, status: "executed", mode: "optimizer", station_id: "station-tongi", fuel_type: "DIESEL",
    allocation: { source_depot_id: "depot-gazipur", route_id: "route-gazipur-tongi", quantity: 6000, eta_tick: 44 },
    situation: { current_inventory: 6000, expected_demand_next_4h: 6900, projected_stockout_hours: 8 },
    expected_impact: { stockout_prob_before: 0.4, stockout_prob_after: 0.05, unmet_liters_avoided: 1500 },
    confidence: 0.9, requires_human_review: false, signals: [], constraints: [], alternatives: [],
    explanation: "Executed.", sim_allocation_id: 17, failure_reason: null,
  },
];

export const mockSimulate: SimulateResult = {
  projection_without: Array.from({ length: 16 }, (_, i) => ({ tick: 43 + i, inventory: Math.max(0, 5000 - i * 460) })),
  projection_with: Array.from({ length: 16 }, (_, i) => ({ tick: 43 + i, inventory: Math.max(0, 5000 - i * 460 + (i >= 1 ? 5000 : 0)) })),
  stockout_prob_before: 0.74,
  stockout_prob_after: 0.12,
};

export const mockDecisions: Decision[] = [
  { id: 5, tick: 36, actor: "operator", action: "approve", recommendation_id: 18, result: "OK", note: null, created_at: "2026-09-29T10:01:00Z" },
  { id: 4, tick: 36, actor: "system", action: "execute", recommendation_id: 18, result: "OK", note: "sim allocation 17", created_at: "2026-09-29T10:01:01Z" },
  { id: 3, tick: 30, actor: "operator", action: "reject", recommendation_id: 15, result: "OK", note: "route closing soon", created_at: "2026-09-29T09:55:00Z" },
];

export const mockMode: Mode = { mode: "manual", auto_confidence_threshold: 0.8, auto_max_quantity: 5000, auto_min_risk_drop: 0.2 };

export const mockBriefing: Briefing = {
  tick: 42,
  summary: "Network service level is 98.1%. Dhaka is under a demand spike and the Gazipur → Mirpur route is disrupted; Mirpur Octane is the top risk.",
  top_risks: ["Mirpur OCTANE stockout in 3.2 h (74%)", "Cox's Bazar PETROL watch (33%) — Patiya petrol supply delayed"],
  recommended_actions: ["Approve rec #21: 5,000 L Octane Gazipur → Mirpur", "Review rec #20 (low confidence)"],
  source: "template",
};

export const mockAssistant: AssistantAnswer = {
  answer: "Mirpur is at risk because Octane demand is 1.8x normal under an active demand spike, and its main route from Gazipur is disrupted. Recommendation #21 addresses this.",
  evidence: ["alert:9", "recommendation:21"],
  source: "template",
};

export const mockIncident: IncidentExplanation = {
  explanation: "This alert fired because the projected Octane stockout at Mirpur (3.2 h) is inside the 4 h planning horizon.",
  source: "template",
};

export const mockSystemStatus: SystemStatus = {
  overall: "healthy",
  components: { backend_api: "healthy", database: "healthy", simulator: "healthy", prediction_service: "healthy", decision_engine: "healthy", llm: "healthy" },
  circuit_breaker: "closed", sse: "connected", p95_latency_ms: 164, error_rate: 0.004, fallback_activations: 3, uptime_s: 5400,
};
