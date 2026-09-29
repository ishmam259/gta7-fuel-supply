"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Bug, Eraser, Pause, Play, RotateCcw, SkipForward, Zap } from "lucide-react";
import { useLive } from "@/components/live-provider";
import { PageHeader, Pill, StatusPill } from "@/components/bits";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { usePoll, useOperatorKey } from "@/lib/hooks";
import { nameOf } from "@/lib/format";
import { FUELS, type NetworkState } from "@/lib/types";

// Simulator guide §7.8 — which target list each event type takes, plus its numeric parameter.
type EventType = "demand_spike" | "route_disruption" | "station_outage" | "depot_constraint" | "shipment_delay" | "supply_shortfall";
const EVENTS: Record<EventType, { label: string; brief: string; target: "region_ids" | "route_ids" | "station_ids" | "depot_ids"; num?: { key: string; label: string; def: number; step: number }; fuels?: boolean }> = {
  demand_spike: { label: "Demand spike", brief: "Risk change, forecast/detection response, allocation adaptation", target: "region_ids", num: { key: "multiplier", label: "Multiplier", def: 1.8, step: 0.1 } },
  shipment_delay: { label: "Shipment delay", brief: "Warning, shortage impact, decision response, recovery", target: "depot_ids", num: { key: "delay_ticks", label: "Delay (ticks)", def: 8, step: 1 }, fuels: true },
  depot_constraint: { label: "Depot constraint", brief: "Constraint handling, reallocation, service impact", target: "depot_ids" },
  route_disruption: { label: "Route disruption", brief: "Alternative allocation and recovery", target: "route_ids" },
  station_outage: { label: "Station outage", brief: "Station stops serving; recovery when resolved", target: "station_ids" },
  supply_shortfall: { label: "Supply shortfall", brief: "Incoming supply reduced by a factor", target: "depot_ids", num: { key: "factor", label: "Factor", def: 0.5, step: 0.1 }, fuels: true },
};

type FaultType = "latency" | "unavailable" | "error_rate" | "stale_data" | "stream_disconnect";
const FAULTS: { type: FaultType; label: string; desc: string; params?: Record<string, number> }[] = [
  { type: "unavailable", label: "Simulator down", desc: "All /v1 calls 503 → retries, circuit breaker opens, degraded mode + cached state" },
  { type: "error_rate", label: "Flaky API (30% errors)", desc: "Random 503s → retries with backoff absorb them", params: { rate: 0.3 } },
  { type: "latency", label: "Slow API (+1.5 s)", desc: "Every call delayed → timeouts, p95 latency rises", params: { delay_ms: 1500 } },
  { type: "stale_data", label: "Stale data", desc: "X-Simulator-Stale header → state marked stale in UI" },
  { type: "stream_disconnect", label: "SSE disconnect", desc: "Simulator stream refuses → poll fallback keeps ticking" },
];

export default function ControlPage() {
  const { state } = useLive();
  const opKey = useOperatorKey();
  const s = state.data;
  const tick = s?.instance.tick ?? 0;
  const [busy, setBusy] = useState("");
  const [n, setN] = useState("4");
  const events = usePoll(async () => (await api.chaosEvents()) as Record<string, unknown>[], 5000);
  const faults = usePoll(async () => (await api.chaosFaults()) as Record<string, unknown>[], 5000);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    try {
      await fn();
      toast.success(label);
      void events.refresh();
      void faults.refresh();
      void state.refresh();
    } catch (e) {
      toast.error(`${label} failed`, { description: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy("");
    }
  };

  return (
    <>
      <PageHeader title="Control & chaos" subtitle="Drive the simulation and inject crises / faults for the demo. Operator key required. Simulation only.">
        {!opKey && <Pill tone="warn">enter operator key to enable</Pill>}
      </PageHeader>

      <Card>
        <CardHeader>
          <CardTitle>Simulation</CardTitle>
          <CardDescription>
            Tick <b>{tick}</b> · <StatusPill value={s?.instance.status} />
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-2">
          <Button disabled={!opKey || !!busy} onClick={() => run("Simulation running", () => api.sim("run"))}>
            <Play /> Run
          </Button>
          <Button variant="outline" disabled={!opKey || !!busy} onClick={() => run("Simulation paused", () => api.sim("pause"))}>
            <Pause /> Pause
          </Button>
          <div className="flex items-end gap-1">
            <Input className="h-8 w-16" inputMode="numeric" value={n} onChange={(e) => setN(e.target.value.replace(/\D/g, ""))} aria-label="Ticks to step" />
            <Button variant="outline" disabled={!opKey || !!busy} onClick={() => run(`Stepped ${n || 1} tick(s)`, () => api.sim("step", Math.max(1, Math.min(200, Number(n) || 1))))}>
              <SkipForward /> Step
            </Button>
          </div>
          <Button
            variant="destructive"
            className="ml-auto"
            disabled={!opKey || !!busy}
            onClick={() => {
              if (window.confirm("Reset the simulator? This wipes all simulated allocations, events and history and reloads the scenario.")) void run("Simulation reset", () => api.sim("reset"));
            }}
          >
            <RotateCcw /> Reset
          </Button>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <EventCard state={s} tick={tick} disabled={!opKey || !!busy} onInject={(label, body) => run(label, () => api.chaosEvent(body))} />

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bug className="size-4" /> Engineering faults
            </CardTitle>
            <CardDescription>Injected into the simulator API — watch System Status, the degraded banner and recovery</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <FaultButtons disabled={!opKey || !!busy} onInject={(label, body) => run(label, () => api.chaosFault(body))} />
            <Button variant="outline" className="w-full" disabled={!opKey || !!busy} onClick={() => run("All faults cleared", () => api.chaosFaultClear())}>
              <Eraser /> Clear all faults (recover)
            </Button>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Timeline title="Recent events" rows={events.data} error={events.error} kind="event" state={s} />
        <Timeline title="Recent faults" rows={faults.data} error={faults.error} kind="fault" state={s} />
      </div>
    </>
  );
}

function EventCard({ state, tick, disabled, onInject }: { state?: NetworkState; tick: number; disabled: boolean; onInject: (label: string, body: Record<string, unknown>) => void }) {
  const [type, setType] = useState<EventType>("demand_spike");
  const def = EVENTS[type];
  const [targets, setTargets] = useState<string[]>([]);
  const [fuels, setFuels] = useState<string[]>([]);
  const [start, setStart] = useState("");
  const [dur, setDur] = useState("12");
  const [val, setVal] = useState("");

  const options: { id: string; name: string }[] =
    def.target === "region_ids" ? state?.regions ?? [] :
    def.target === "depot_ids" ? state?.depots ?? [] :
    def.target === "station_ids" ? state?.stations ?? [] :
    (state?.routes ?? []).map((r) => ({ id: r.id, name: `${nameOf(state, r.source_depot_id).replace(" Depot", "")} → ${nameOf(state, r.destination_station_id)}` }));

  const toggle = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const pick = (t: EventType) => {
    setType(t);
    setTargets([]);
    setFuels([]);
    setVal("");
  };

  const inject = () => {
    const parameters: Record<string, unknown> = { [def.target]: targets };
    if (def.num) parameters[def.num.key] = Number(val || def.num.def);
    if (def.fuels) parameters.fuel_types = fuels;
    onInject(`${def.label} injected`, { type, start_tick: Number(start || tick + 1), duration_ticks: Math.max(1, Number(dur) || 12), parameters });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Zap className="size-4" /> Crisis events
        </CardTitle>
        <CardDescription>Domain crises from the brief §10</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-1.5">
          {(Object.keys(EVENTS) as EventType[]).map((t) => (
            <button
              key={t}
              onClick={() => pick(t)}
              className={`rounded-lg border px-2.5 py-1 text-xs font-medium ${type === t ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
            >
              {EVENTS[t].label}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">Expected system response: {def.brief}.</p>
        <div>
          <div className="mb-1 text-xs text-muted-foreground">Targets ({def.target.replace("_ids", "s")}) — none selected = all</div>
          <div className="flex flex-wrap gap-1.5">
            {options.map((o) => (
              <button
                key={o.id}
                onClick={() => setTargets((a) => toggle(a, o.id))}
                className={`rounded-md border px-2 py-0.5 text-xs ${targets.includes(o.id) ? "border-sky-500 bg-sky-500/15 text-sky-700 dark:text-sky-300" : "text-muted-foreground hover:bg-muted"}`}
              >
                {o.name}
              </button>
            ))}
          </div>
        </div>
        {def.fuels && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Fuels:</span>
            {FUELS.map((f) => (
              <button
                key={f}
                onClick={() => setFuels((a) => toggle(a, f))}
                className={`rounded-md border px-2 py-0.5 text-xs ${fuels.includes(f) ? "border-sky-500 bg-sky-500/15" : "text-muted-foreground hover:bg-muted"}`}
              >
                {f}
              </button>
            ))}
          </div>
        )}
        <div className="grid grid-cols-3 gap-2">
          <Field label="Start tick">
            <Input inputMode="numeric" placeholder={String(tick + 1)} value={start} onChange={(e) => setStart(e.target.value.replace(/\D/g, ""))} />
          </Field>
          <Field label="Duration (ticks)">
            <Input inputMode="numeric" value={dur} onChange={(e) => setDur(e.target.value.replace(/\D/g, ""))} />
          </Field>
          {def.num && (
            <Field label={def.num.label}>
              <Input inputMode="decimal" placeholder={String(def.num.def)} value={val} onChange={(e) => setVal(e.target.value.replace(/[^0-9.]/g, ""))} />
            </Field>
          )}
        </div>
        <Button className="w-full" disabled={disabled} onClick={inject}>
          <Zap /> Inject {def.label.toLowerCase()}
        </Button>
      </CardContent>
    </Card>
  );
}

function FaultButtons({ disabled, onInject }: { disabled: boolean; onInject: (label: string, body: Record<string, unknown>) => void }) {
  const [secs, setSecs] = useState("60");
  return (
    <>
      <Field label="Duration (seconds, max 3600)">
        <Input inputMode="numeric" value={secs} onChange={(e) => setSecs(e.target.value.replace(/\D/g, ""))} />
      </Field>
      {FAULTS.map((f) => (
        <button
          key={f.type}
          disabled={disabled}
          onClick={() => onInject(`Fault "${f.label}" injected`, { type: f.type, duration_seconds: Math.max(1, Math.min(3600, Number(secs) || 60)), parameters: f.params ?? {} })}
          className="flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left text-sm hover:border-red-500/50 hover:bg-red-500/5 disabled:pointer-events-none disabled:opacity-50"
        >
          <span>
            <span className="font-medium">{f.label}</span>
            <span className="block text-xs text-muted-foreground">{f.desc}</span>
          </span>
          <Pill tone="bad" className="normal-case">
            {f.type}
          </Pill>
        </button>
      ))}
    </>
  );
}

function Timeline({ title, rows, error, kind, state }: { title: string; rows?: Record<string, unknown>[]; error: string | null; kind: "event" | "fault"; state?: NetworkState }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5 text-sm">
        {error && <div className="text-xs text-amber-700">{error}</div>}
        {rows && rows.length === 0 && <div className="text-muted-foreground">None yet</div>}
        {(rows ?? []).slice(0, 10).map((r, i) => {
          const params = (r.parameters ?? {}) as Record<string, unknown>;
          const detail = Object.entries(params)
            .map(([k, v]) => (Array.isArray(v) ? (v.length ? v.map((x) => nameOf(state, String(x))).join(", ") : `all ${k.replace("_ids", "s")}`) : `${k} ${v}`))
            .join(" · ");
          const active = kind === "fault" ? r.active === true : r.status === "ACTIVE";
          return (
            <div key={String(r.id ?? i)} className="flex items-center justify-between gap-2 rounded-lg border px-3 py-1.5">
              <div className="min-w-0">
                <div className="font-medium">{String(r.type ?? "?").replace(/_/g, " ")}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {kind === "event" ? `ticks ${r.start_tick}–${r.end_tick}` : `${r.duration_seconds ?? "?"} s`}
                  {detail ? ` · ${detail}` : ""}
                </div>
              </div>
              <StatusPill value={kind === "fault" ? (active ? "active" : "expired") : String(r.status ?? "")} className={active ? "border-red-500/40 bg-red-500/15 text-red-700 dark:text-red-400" : undefined} />
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}
