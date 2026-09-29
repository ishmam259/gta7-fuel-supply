import type { NetworkState, RiskLevel } from "./types";

export const liters = (v: number | string | null | undefined) => {
  const n = typeof v === "string" ? Number(v) : v;
  return n === null || n === undefined || !Number.isFinite(n) ? "—" : `${Math.round(n).toLocaleString("en-US")} L`;
};
export const pct = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(digits)}%`;
export const hours = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : v > 99 ? "> 99 h" : `${v.toFixed(1)} h`;
export const num = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: digits });

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

export function uptime(s: number | undefined): string {
  if (!s && s !== 0) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m ${s % 60}s`;
}

/** Friendly entity name ("station-mirpur" → "Mirpur Fuel Station") using the current state when available. */
export function nameOf(state: NetworkState | undefined, id: string | undefined | null): string {
  if (!id) return "—";
  const hit =
    state?.stations.find((s) => s.id === id) ?? state?.depots.find((d) => d.id === id) ?? state?.regions.find((r) => r.id === id);
  if (hit) return hit.name;
  return id.replace(/^(station|depot|region|route)-/, "").replace(/-/g, " → ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export const RISK_ORDER: Record<RiskLevel, number> = { outage: 3, critical: 2, watch: 1, ok: 0 };

export const riskClass: Record<RiskLevel, string> = {
  ok: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30",
  watch: "bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30",
  critical: "bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/30",
  outage: "bg-zinc-900 text-white border-zinc-900 dark:bg-zinc-100 dark:text-zinc-900",
};

export const riskBar: Record<RiskLevel, string> = {
  ok: "bg-emerald-500",
  watch: "bg-amber-500",
  critical: "bg-red-500",
  outage: "bg-zinc-500",
};

export function statusTone(s: string | undefined): "good" | "warn" | "bad" | "neutral" {
  const v = (s || "").toLowerCase();
  if (["healthy", "ok", "open", "available", "closed", "connected", "running", "executed", "resolved", "scheduled", "arrived", "delivered", "llm"].includes(v))
    return "good";
  if (["degraded", "watch", "constrained", "delayed", "half_open", "reconnecting", "fallback", "pending", "paused", "warning", "template", "in_transit"].includes(v))
    return "warn";
  if (["down", "critical", "outage", "disrupted", "closed_route", "failed", "rejected", "unavailable", "open_breaker", "error"].includes(v))
    return "bad";
  return "neutral";
}

export const toneClass = {
  good: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30",
  warn: "bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30",
  bad: "bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/30",
  neutral: "bg-muted text-muted-foreground border-border",
};

export const fuelColor: Record<string, string> = { DIESEL: "#0ea5e9", PETROL: "#f59e0b", OCTANE: "#a855f7" };
