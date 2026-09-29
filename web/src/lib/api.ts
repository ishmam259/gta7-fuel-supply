// Typed client for docs/API_CONTRACT.md (contract v2).
// Mock mode: NEXT_PUBLIC_MOCK=1 mocks everything; NEXT_PUBLIC_MOCK_ENDPOINTS="briefing,assistant" mocks only those keys.
// A failed real call is NEVER replaced by mock data — the UI keeps the last good response and shows it as stale.
import * as mock from "./mock";
import type {
  Alert, AssistantAnswer, Briefing, Decision, Forecast, IncidentExplanation, MetricPoint, Mode,
  NetworkState, Recommendation, SimControlResult, SimulateBody, SimulateResult, SystemStatus,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8090").replace(/\/$/, "");
const MOCK_ALL = process.env.NEXT_PUBLIC_MOCK === "1";
const MOCK_KEYS = new Set((process.env.NEXT_PUBLIC_MOCK_ENDPOINTS || "").split(",").map((s) => s.trim()).filter(Boolean));
const TIMEOUT_MS = 8000;

export type EndpointKey =
  | "state" | "forecast" | "metricsHistory" | "alerts" | "recommendations" | "recommendation" | "simulate"
  | "approve" | "reject" | "decisions" | "mode" | "setMode" | "briefing" | "assistant" | "incident"
  | "systemStatus" | "sim" | "chaos";

export const isMocked = (k: EndpointKey) => MOCK_ALL || MOCK_KEYS.has(k);
export const anyMocked = () => MOCK_ALL || MOCK_KEYS.size > 0;

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

// ---- operator key (entered by the operator in the UI, kept in sessionStorage only — never in code)
const KEY_STORAGE = "gta7.operatorKey";
export function getOperatorKey(): string {
  try {
    return sessionStorage.getItem(KEY_STORAGE) || "";
  } catch {
    return "";
  }
}
export function setOperatorKey(k: string) {
  try {
    if (k) sessionStorage.setItem(KEY_STORAGE, k);
    else sessionStorage.removeItem(KEY_STORAGE);
    window.dispatchEvent(new Event("gta7-operator-key"));
  } catch {
    /* storage blocked: key just won't persist */
  }
}

async function request<T>(path: string, init: RequestInit & { operator?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body) headers["Content-Type"] = "application/json";
  if (init.operator) {
    const key = getOperatorKey();
    if (!key) throw new ApiError(401, "OPERATOR_KEY_REQUIRED", "Enter the operator key (top-right) to perform this action");
    headers["X-Operator-Key"] = key;
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers, signal: ctrl.signal, cache: "no-store" });
  } catch (e) {
    const aborted = e instanceof DOMException && e.name === "AbortError";
    throw new ApiError(0, aborted ? "TIMEOUT" : "NETWORK", aborted ? "Backend did not answer in time" : "Backend unreachable");
  } finally {
    clearTimeout(timer);
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    if (res.ok) throw new ApiError(res.status, "INVALID_JSON", "Backend returned invalid JSON");
  }
  if (!res.ok) {
    const d = (data as { detail?: { code?: string; message?: string } | string } | null)?.detail;
    const code = typeof d === "object" && d?.code ? d.code : `HTTP_${res.status}`;
    const msg = typeof d === "object" && d?.message ? d.message : typeof d === "string" ? d : res.statusText;
    throw new ApiError(res.status, code, msg || "Request failed");
  }
  return data as T;
}

const delay = <T,>(v: T): Promise<T> => new Promise((r) => setTimeout(() => r(structuredClone(v)), 150));
const q = (o: Record<string, string | number | undefined>) => {
  const p = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => v !== undefined && v !== "" && p.set(k, String(v)));
  const s = p.toString();
  return s ? `?${s}` : "";
};
const post = (body?: unknown) => ({ method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  state: () => (isMocked("state") ? delay(mock.mockState) : request<NetworkState>("/api/state")),

  forecast: (station_id?: string, fuel_type?: string) =>
    isMocked("forecast")
      ? delay(mock.mockForecast.filter((f) => (!station_id || f.station_id === station_id) && (!fuel_type || f.fuel_type === fuel_type)))
      : request<Forecast[]>(`/api/forecast${q({ station_id, fuel_type })}`),

  metricsHistory: (limit = 500) =>
    isMocked("metricsHistory") ? delay(mock.mockMetricsHistory) : request<MetricPoint[]>(`/api/metrics/history${q({ limit })}`),

  alerts: (status: "open" | "all" = "open", limit = 100) =>
    isMocked("alerts")
      ? delay(mock.mockAlerts.filter((a) => status === "all" || a.status === "open"))
      : request<Alert[]>(`/api/alerts${q({ status, limit })}`),

  recommendations: (status = "all") =>
    isMocked("recommendations")
      ? delay(mock.mockRecommendations.filter((r) => status === "all" || r.status === status))
      : request<Recommendation[]>(`/api/recommendations${q({ status })}`),

  recommendation: (id: number) =>
    isMocked("recommendation")
      ? delay(mock.mockRecommendations.find((r) => r.id === id) ?? mock.mockRecommendations[0])
      : request<Recommendation>(`/api/recommendations/${id}`),

  simulate: (body: SimulateBody) =>
    isMocked("simulate") ? delay(mock.mockSimulate) : request<SimulateResult>("/api/recommendations/simulate", post(body)),

  approve: (id: number, quantity?: number, note?: string) =>
    isMocked("approve")
      ? delay({ ...mock.mockRecommendations.find((r) => r.id === id)!, status: "executed" as const })
      : request<Recommendation>(`/api/recommendations/${id}/approve`, { ...post({ quantity, note: note || undefined }), operator: true }),

  reject: (id: number, note?: string) =>
    isMocked("reject")
      ? delay({ ...mock.mockRecommendations.find((r) => r.id === id)!, status: "rejected" as const })
      : request<Recommendation>(`/api/recommendations/${id}/reject`, { ...post({ note: note || "" }), operator: true }),

  decisions: (limit = 100) => (isMocked("decisions") ? delay(mock.mockDecisions) : request<Decision[]>(`/api/decisions${q({ limit })}`)),

  mode: () => (isMocked("mode") ? delay(mock.mockMode) : request<Mode>("/api/mode")),
  setMode: (m: Mode) => (isMocked("setMode") ? delay(m) : request<Mode>("/api/mode", { ...post(m), operator: true })),

  briefing: () => (isMocked("briefing") ? delay(mock.mockBriefing) : request<Briefing>("/api/briefing")),
  assistant: (question: string) =>
    isMocked("assistant") ? delay(mock.mockAssistant) : request<AssistantAnswer>("/api/assistant", post({ question })),
  incident: (alertId: number) =>
    isMocked("incident") ? delay(mock.mockIncident) : request<IncidentExplanation>(`/api/incidents/${alertId}/explain`),

  systemStatus: () => (isMocked("systemStatus") ? delay(mock.mockSystemStatus) : request<SystemStatus>("/api/system/status")),

  sim: (action: "run" | "pause" | "step" | "reset", n = 1) =>
    isMocked("sim")
      ? delay({ tick: 43, status: action === "run" ? "RUNNING" : "PAUSED" })
      : request<SimControlResult>(`/api/sim/${action}`, { ...post(action === "step" ? { n } : {}), operator: true }),

  chaosEvent: (body: Record<string, unknown>) =>
    isMocked("chaos") ? delay({ ok: true }) : request<unknown>("/api/chaos/event", { ...post(body), operator: true }),
  chaosFault: (body: Record<string, unknown>) =>
    isMocked("chaos") ? delay({ ok: true }) : request<unknown>("/api/chaos/fault", { ...post(body), operator: true }),
  chaosFaultClear: () => (isMocked("chaos") ? delay({ ok: true }) : request<unknown>("/api/chaos/fault/clear", { ...post({}), operator: true })),
  chaosEvents: () => (isMocked("chaos") ? delay([]) : request<unknown>("/api/chaos/events")),
  chaosFaults: () => (isMocked("chaos") ? delay([]) : request<unknown>("/api/chaos/faults")),
};

export const streamUrl = () => `${API_URL}/api/stream`;
