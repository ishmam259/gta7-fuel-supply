"use client";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { riskBar, riskClass, statusTone, toneClass, pct, hours, liters } from "@/lib/format";
import type { FuelRisk, RiskLevel } from "@/lib/types";
import { AlertTriangle, Loader2 } from "lucide-react";

export function Pill({ children, tone = "neutral", className }: { children: ReactNode; tone?: keyof typeof toneClass; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide whitespace-nowrap", toneClass[tone], className)}>
      {children}
    </span>
  );
}

export function StatusPill({ value, className }: { value: string | undefined | null; className?: string }) {
  return (
    <Pill tone={statusTone(value ?? "")} className={className}>
      {(value ?? "unknown").replace(/_/g, " ")}
    </Pill>
  );
}

export function RiskBadge({ level, className }: { level: RiskLevel | undefined; className?: string }) {
  const l = level ?? "ok";
  return (
    <span className={cn("inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide", riskClass[l], className)}>
      {l}
    </span>
  );
}

export function SimulatedBadge({ className }: { className?: string }) {
  return (
    <span
      title="All data comes from the BUP Fuel Supply Simulator — not real fuel infrastructure."
      className={cn("inline-flex items-center rounded-md border border-dashed border-sky-500/50 bg-sky-500/10 px-1.5 py-0.5 text-[10px] font-bold tracking-widest text-sky-700 dark:text-sky-300", className)}
    >
      SIMULATED
    </span>
  );
}

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function Kpi({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "good" | "warn" | "bad" }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-1 text-2xl font-semibold tabular-nums",
          tone === "good" && "text-emerald-600 dark:text-emerald-400",
          tone === "warn" && "text-amber-600 dark:text-amber-400",
          tone === "bad" && "text-red-600 dark:text-red-400",
        )}
      >
        {value}
      </div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

/** Inventory vs capacity bar, colored by risk level. */
export function InvBar({ fuel, inv, cap, risk }: { fuel: string; inv: number | undefined; cap: number | undefined; risk?: FuelRisk }) {
  const ratio = cap ? Math.max(0, Math.min(1, (inv ?? 0) / cap)) : 0;
  const level = risk?.level ?? (ratio < 0.15 ? "critical" : ratio < 0.3 ? "watch" : "ok");
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium">{fuel}</span>
        <span className="tabular-nums text-muted-foreground">
          {liters(inv)} / {liters(cap)}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full transition-all", riskBar[level])} style={{ width: `${ratio * 100}%` }} />
      </div>
      {risk && (
        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
          <span>
            stockout in <b className="text-foreground">{hours(risk.stockout_hours)}</b>
          </span>
          <span className="flex items-center gap-1">
            p={pct(risk.stockout_prob)} <RiskBadge level={risk.level} />
          </span>
        </div>
      )}
    </div>
  );
}

export function StaleNote({ error, updatedAt }: { error: string | null; updatedAt: number | null }) {
  if (!error) return null;
  return (
    <div className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
      <AlertTriangle className="size-3.5 shrink-0" />
      <span>
        {error}.{" "}
        {updatedAt ? `Showing last good data from ${new Date(updatedAt).toLocaleTimeString()}.` : "No data yet — retrying every few seconds."}
      </span>
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> {label}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">{children}</div>;
}

export function SourceTag({ source }: { source: "llm" | "template" | undefined }) {
  if (!source) return null;
  return (
    <Pill tone={source === "llm" ? "good" : "neutral"} className="normal-case">
      {source === "llm" ? "AI (LLM)" : "template fallback"}
    </Pill>
  );
}

/** Small segmented control (filters). */
export function Seg({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <div className="inline-flex rounded-lg border p-0.5">
      {options.map(([v, label]) => (
        <button
          key={v}
          onClick={() => onChange(v)}
          className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${value === v ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
