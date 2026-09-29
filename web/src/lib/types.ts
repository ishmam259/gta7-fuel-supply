// Types mirror docs/API_CONTRACT.md (contract v2). Keep in sync when Ishmam announces a new version.

export type FuelType = "DIESEL" | "PETROL" | "OCTANE";
export const FUELS: FuelType[] = ["DIESEL", "PETROL", "OCTANE"];
export type FuelMap = Partial<Record<FuelType, number>>;

export type RiskLevel = "ok" | "watch" | "critical" | "outage";

export interface FuelRisk {
  level: RiskLevel;
  stockout_hours: number | null;
  stockout_prob: number;
}

export interface Instance {
  tick: number;
  sim_time: string;
  status: string;
}

export interface NetworkMetrics {
  service_level: number;
  served_demand_liters: number;
  unmet_demand_liters: number;
  allocation_liters: number;
  allocation_failures: number;
}

export interface Region {
  id: string;
  name: string;
  demand_factor: number;
  demand_last_4h: FuelMap;
}

export interface Depot {
  id: string;
  name: string;
  region_id: string;
  status: string;
  dispatch_capacity_per_tick: number;
  dispatch_used_this_tick: number;
  capacity: FuelMap;
  inventory: FuelMap;
}

export interface Station {
  id: string;
  name: string;
  region_id: string;
  status: string;
  demand_profile: string;
  demand_multiplier: number;
  capacity: FuelMap;
  inventory: FuelMap;
  risk: Partial<Record<FuelType, FuelRisk>>;
}

export interface Route {
  id: string;
  source_depot_id: string;
  destination_station_id: string;
  transit_ticks: number;
  max_shipment: number;
  status: string;
}

export interface InTransit {
  id: number;
  route_id: string;
  fuel_type: FuelType;
  quantity: number;
  status: string;
  expected_arrival_tick: number;
}

export interface UpcomingSupply {
  id: string;
  depot_id: string;
  fuel_type: FuelType;
  quantity: number;
  planned_tick: number;
  status: string;
}

export interface SimEvent {
  id: number;
  type: string;
  start_tick: number;
  end_tick: number;
  status: string;
  parameters: Record<string, unknown>;
}

export interface DataFreshness {
  stale: boolean;
  degraded: boolean;
  last_sync_tick: number | null;
  last_sync_at: string | null;
}

export interface NetworkState {
  instance: Instance;
  metrics: NetworkMetrics;
  regions: Region[];
  depots: Depot[];
  stations: Station[];
  routes: Route[];
  in_transit: InTransit[];
  upcoming_supply: UpcomingSupply[];
  active_events: SimEvent[];
  data_freshness: DataFreshness;
}

export interface Forecast {
  station_id: string;
  fuel_type: FuelType;
  horizon_ticks: number;
  per_tick: number[];
  lower: number[];
  upper: number[];
  mape_recent: number | null;
}

export interface MetricPoint {
  tick: number;
  service_level: number;
  unmet_demand_liters: number;
  allocation_liters: number;
  open_alerts: number;
}

export type Severity = "info" | "warning" | "critical";

export interface Alert {
  id: number;
  tick: number;
  severity: Severity;
  kind: string;
  entity: { type: string; id: string; fuel_type?: FuelType | null };
  title: string;
  detail: string;
  status: "open" | "resolved";
  created_at: string;
}

export type RecStatus = "pending" | "approved" | "executed" | "rejected" | "failed";

export interface Allocation {
  source_depot_id: string;
  route_id: string;
  quantity: number;
  eta_tick: number;
}

export interface Alternative extends Allocation {
  stockout_prob_after: number;
}

export interface Recommendation {
  id: number;
  tick: number;
  status: RecStatus;
  mode: "optimizer" | "heuristic" | "fallback";
  station_id: string;
  fuel_type: FuelType;
  allocation: Allocation;
  situation: { current_inventory: number; expected_demand_next_4h: number; projected_stockout_hours: number | null };
  expected_impact: { stockout_prob_before: number; stockout_prob_after: number; unmet_liters_avoided: number };
  confidence: number;
  requires_human_review: boolean;
  signals: string[];
  constraints: string[];
  alternatives: Alternative[];
  explanation: string;
  sim_allocation_id: number | string | null;
  failure_reason: string | null;
}

export interface SimulateBody {
  station_id: string;
  fuel_type: FuelType;
  source_depot_id: string;
  route_id: string;
  quantity: number;
}

export interface SimulateResult {
  projection_without: { tick: number; inventory: number }[];
  projection_with: { tick: number; inventory: number }[];
  stockout_prob_before: number;
  stockout_prob_after: number;
}

export interface Decision {
  id: number;
  tick: number;
  actor: "operator" | "autopilot" | "system";
  action: string;
  recommendation_id: number | null;
  result: string;
  note: string | null;
  created_at: string;
}

export interface Mode {
  mode: "manual" | "assisted";
  auto_confidence_threshold: number;
  auto_max_quantity: number;
}

export interface Briefing {
  tick: number;
  summary: string;
  top_risks: string[];
  recommended_actions: string[];
  source: "llm" | "template";
}

export interface AssistantAnswer {
  answer: string;
  evidence: string[];
  source: "llm" | "template";
}

export interface IncidentExplanation {
  explanation: string;
  source: "llm" | "template";
}

export type Health = "healthy" | "degraded" | "down" | "fallback" | "unavailable";

export interface SystemStatus {
  overall: "healthy" | "degraded" | "down";
  components: Record<string, Health | string>;
  circuit_breaker: "closed" | "open" | "half_open";
  sse: "connected" | "reconnecting";
  p95_latency_ms: number;
  error_rate: number;
  fallback_activations: number;
  uptime_s: number;
  // extras the backend currently sends (not in contract, optional)
  p50_latency_ms?: number;
  last_error?: string | null;
  tick?: number | null;
  cpu_percent?: number;
  memory_mb?: number;
}

export interface SimControlResult {
  tick: number;
  status: string;
}
