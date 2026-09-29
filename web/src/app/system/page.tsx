"use client";
import { Activity, BrainCircuit, Cpu, Database, ExternalLink, Gauge, Radio, Server, Sparkles, Workflow } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useLive } from "@/components/live-provider";
import { Kpi, Loading, PageHeader, StaleNote, StatusPill } from "@/components/bits";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { API_URL } from "@/lib/api";
import { num, pct, timeAgo, uptime } from "@/lib/format";
import { cn } from "@/lib/utils";

const GRAFANA_URL = process.env.NEXT_PUBLIC_GRAFANA_URL || "http://localhost:3001";
const PROMETHEUS_URL = process.env.NEXT_PUBLIC_PROMETHEUS_URL || "http://localhost:9090";

const COMPONENTS: { key: string; label: string; icon: LucideIcon; what: string }[] = [
  { key: "backend_api", label: "Backend API", icon: Server, what: "FastAPI service the console talks to" },
  { key: "database", label: "Database", icon: Database, what: "SQLite: recommendations, audit, alerts, metrics" },
  { key: "simulator", label: "Fuel Simulator", icon: Workflow, what: "BUP simulator link (resilient client)" },
  { key: "prediction_service", label: "Prediction Service", icon: BrainCircuit, what: "Demand forecast + stockout probability" },
  { key: "decision_engine", label: "Decision Engine", icon: Gauge, what: "Planner; falls back to rule policy" },
  { key: "llm", label: "GenAI (LLM)", icon: Sparkles, what: "Explanations; template fallback if unavailable" },
];

const DOT: Record<string, string> = { good: "bg-emerald-500", warn: "bg-amber-500", bad: "bg-red-500", neutral: "bg-zinc-400" };
const tone = (v: string) =>
  v === "healthy" || v === "closed" || v === "connected" ? "good" : v === "down" || v === "open" ? "bad" : v ? "warn" : "neutral";

export default function SystemPage() {
  const { status, state, stream } = useLive();
  const s = status.data;
  const fresh = state.data?.data_freshness;

  return (
    <>
      <PageHeader title="System status" subtitle="Is the platform itself healthy? Components, resilience mechanisms and performance (refreshes every 3 s)">
        <a href={GRAFANA_URL} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-sm hover:bg-muted">
          Grafana dashboards <ExternalLink className="size-3.5" />
        </a>
        <a href={PROMETHEUS_URL} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-sm hover:bg-muted">
          Prometheus <ExternalLink className="size-3.5" />
        </a>
        <a href={`${API_URL}/metrics`} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-sm hover:bg-muted">
          /metrics <ExternalLink className="size-3.5" />
        </a>
      </PageHeader>
      <StaleNote error={status.error} updatedAt={status.updatedAt} />
      {!s && !status.error && <Loading />}
      {!s && status.error && (
        <Card className="border-red-500/50">
          <CardContent className="py-6 text-sm">
            <div className="flex items-center gap-2 text-base font-semibold text-red-600">
              <span className="size-3 animate-pulse rounded-full bg-red-500" /> Backend API unreachable
            </div>
            <p className="mt-1 text-muted-foreground">The console keeps showing the last good network state and retries every 3 s. Check the backend container / health check.</p>
          </CardContent>
        </Card>
      )}
      {s && (
        <>
          <div
            className={cn(
              "flex flex-wrap items-center justify-between gap-3 rounded-xl border-2 px-5 py-4",
              s.overall === "healthy" ? "border-emerald-500/50 bg-emerald-500/5" : s.overall === "degraded" ? "border-amber-500/50 bg-amber-500/5" : "border-red-500/50 bg-red-500/5",
            )}
          >
            <div className="flex items-center gap-3">
              <span className={cn("size-4 rounded-full", DOT[tone(s.overall === "healthy" ? "healthy" : s.overall === "down" ? "down" : "x")], s.overall !== "healthy" && "animate-pulse")} />
              <div>
                <div className="text-lg font-semibold">Overall: {s.overall.toUpperCase()}</div>
                <div className="text-xs text-muted-foreground">
                  {s.overall === "healthy"
                    ? "All core components healthy."
                    : "One or more components degraded — platform keeps operating with fallbacks and cached state."}
                </div>
              </div>
            </div>
            <div className="text-right text-xs text-muted-foreground">
              uptime {uptime(s.uptime_s)} {s.tick != null && <>· backend at tick {s.tick}</>}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {COMPONENTS.map(({ key, label, icon: Icon, what }) => {
              const v = String(s.components?.[key] ?? "unknown");
              return (
                <div key={key} className="flex min-w-0 items-center justify-between gap-3 rounded-xl border bg-card p-4">
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted">
                      <Icon className="size-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="font-medium">{label}</div>
                      <div className="truncate text-xs text-muted-foreground">{what}</div>
                    </div>
                  </div>
                  <StatusPill value={v} />
                </div>
              );
            })}
          </div>

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi label="p95 latency" value={`${num(s.p95_latency_ms, 1)} ms`} tone={s.p95_latency_ms < 300 ? "good" : s.p95_latency_ms < 1000 ? "warn" : "bad"} hint={s.p50_latency_ms != null ? `p50 ${num(s.p50_latency_ms, 1)} ms` : "API requests, rolling window"} />
            <Kpi label="Error rate" value={pct(s.error_rate, 1)} tone={s.error_rate < 0.01 ? "good" : s.error_rate < 0.05 ? "warn" : "bad"} hint="5xx share, rolling window" />
            <Kpi label="Fallback activations" value={num(s.fallback_activations)} tone={s.fallback_activations ? "warn" : "good"} hint="rule policy / cached state used" />
            <Kpi label="Resources" value={s.memory_mb != null ? `${num(s.memory_mb)} MB` : "—"} hint={s.cpu_percent != null ? `CPU ${num(s.cpu_percent, 1)}% (backend process)` : undefined} />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Activity className="size-4" /> Resilience mechanisms
              </CardTitle>
              <CardDescription>What happens when something goes wrong (brief §11)</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-2">
              <Mech label="Circuit breaker (simulator)" value={s.circuit_breaker === "open" ? "open_breaker" : s.circuit_breaker} desc="Opens after repeated simulator failures → degraded mode, cached state, auto-execution paused; half-open probe on /v1/health." />
              <Mech label="Backend SSE link to simulator" value={s.sse} desc="Push hints from the simulator; REST resync on every tick, polling fallback when the stream drops." />
              <Mech label="Console live stream" value={stream === "off" ? "polling only" : stream} desc="This page's SSE to the backend; the console also polls every 3 s, so it keeps working without it." />
              <Mech
                label="Data freshness"
                value={fresh ? (fresh.stale ? "stale" : fresh.degraded ? "degraded" : "healthy") : "unknown"}
                desc={fresh ? `Last sync at tick ${fresh.last_sync_tick ?? "—"} (${timeAgo(fresh.last_sync_at)}). Stale = simulator sent X-Simulator-Stale.` : "No state yet"}
              />
              <Mech label="If prediction fails → fallback policy" value={String(s.components?.prediction_service ?? "—")} desc="Badge = current state of the prediction service. If forecasting fails, the decision engine switches to the rule-based fallback policy (reorder below 50% of capacity)." />
              <Mech label="If LLM fails → template fallback" value={String(s.components?.llm ?? "—")} desc="Badge = current state of the LLM. Every explanation/briefing has a deterministic template fallback, labelled 'template fallback' in the UI." />
            </CardContent>
          </Card>

          {s.last_error && (
            <Card className="border-amber-500/40">
              <CardContent className="flex items-start gap-2 py-3 text-sm">
                <Radio className="mt-0.5 size-4 text-amber-600" />
                <div>
                  <div className="font-medium">Last integration error</div>
                  <code className="break-all text-xs text-muted-foreground">{s.last_error}</code>
                </div>
              </CardContent>
            </Card>
          )}
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Cpu className="size-3" /> Backend {API_URL} · updated {status.updatedAt ? new Date(status.updatedAt).toLocaleTimeString() : "—"}
          </div>
        </>
      )}
    </>
  );
}

function Mech({ label, value, desc }: { label: string; value: string; desc: string }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{label}</span>
        <StatusPill value={value} />
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{desc}</p>
    </div>
  );
}
