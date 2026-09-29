"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { ArrowRight, Check, FlaskConical, Info, ShieldCheck, TriangleAlert, X } from "lucide-react";
import { useLive } from "@/components/live-provider";
import { Empty, Loading, PageHeader, Pill, Seg, StaleNote, StatusPill } from "@/components/bits";
import { WhatIfChart } from "@/components/whatif-chart";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { usePoll, useOperatorKey } from "@/lib/hooks";
import { hours, liters, nameOf, pct } from "@/lib/format";
import type { Allocation, Mode, NetworkState, Recommendation, SimulateResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUSES: [string, string][] = [
  ["pending", "Pending"], ["executed", "Executed"], ["failed", "Failed"], ["rejected", "Rejected"], ["all", "All"],
];

export default function RecommendationsPage() {
  return (
    <Suspense>
      <Inbox />
    </Suspense>
  );
}

function Inbox() {
  const { state, bump } = useLive();
  const params = useSearchParams();
  const wanted = Number(params.get("id")) || null;
  const [status, setStatus] = useState("pending");
  const recs = usePoll(() => api.recommendations(status), 5000, [status, bump]);
  const [selId, setSelId] = useState<number | null>(wanted);
  // opened from a toast / briefing link: select that card; if it is no longer pending, look in "all"
  const [seen, setSeen] = useState<number | null>(null);
  if (wanted !== seen) {
    setSeen(wanted);
    if (wanted) setSelId(wanted);
  }
  const missing = wanted != null && selId === wanted && recs.data && !recs.data.some((r) => r.id === wanted) && status !== "all";
  useEffect(() => {
    if (missing) setTimeout(() => setStatus("all"), 0);
  }, [missing]);
  const list = recs.data ?? [];
  const selected = list.find((r) => r.id === selId) ?? list[0];

  return (
    <>
      <PageHeader title="Recommendations inbox" subtitle="Every allocation is inspectable. Consequential actions need operator approval (human-in-the-loop).">
        <Seg value={status} onChange={setStatus} options={STATUSES} />
      </PageHeader>
      <ModeCard />
      <StaleNote error={recs.error} updatedAt={recs.updatedAt} />
      {!recs.data && !recs.error && <Loading />}
      {recs.data && list.length === 0 && (
        <Empty>No {status === "all" ? "" : status} recommendations. The planner proposes allocations when a station&apos;s stockout risk rises.</Empty>
      )}
      {list.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-[minmax(260px,340px)_1fr]">
          <div className="space-y-2 lg:max-h-[calc(100vh-220px)] lg:overflow-y-auto lg:pr-1">
            {list.map((r) => (
              <button
                key={r.id}
                onClick={() => setSelId(r.id)}
                className={cn(
                  "w-full rounded-xl border bg-card p-3 text-left transition-colors hover:border-foreground/30",
                  selected?.id === r.id && "border-primary ring-2 ring-primary/20",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">
                    #{r.id} {nameOf(state.data, r.station_id)}
                  </span>
                  <StatusPill value={r.status} />
                </div>
                <div className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>
                    {r.fuel_type} · {liters(r.allocation.quantity)}
                  </span>
                  <span className="flex items-center gap-1 tabular-nums">
                    <b className="text-red-600 dark:text-red-400">{pct(r.expected_impact.stockout_prob_before)}</b>
                    <ArrowRight className="size-3" />
                    <b className="text-emerald-600 dark:text-emerald-400">{pct(r.expected_impact.stockout_prob_after)}</b>
                  </span>
                </div>
                {r.requires_human_review && r.status === "pending" && (
                  <div className="mt-1.5 flex items-center gap-1 text-[11px] font-medium text-amber-700 dark:text-amber-400">
                    <TriangleAlert className="size-3" /> Human review requested
                  </div>
                )}
              </button>
            ))}
          </div>
          {selected && <Inspect key={selected.id} rec={selected} state={state.data} onChanged={() => void recs.refresh()} />}
        </div>
      )}
    </>
  );
}

function Inspect({ rec, state, onChanged }: { rec: Recommendation; state: NetworkState | undefined; onChanged: () => void }) {
  const opKey = useOperatorKey();
  const [qty, setQty] = useState(String(Math.round(rec.allocation.quantity)));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"" | "approve" | "reject">("");
  const [what, setWhat] = useState<{ alloc: Allocation; res: SimulateResult } | null>(null);
  const [simBusy, setSimBusy] = useState(false);
  const [simErr, setSimErr] = useState<string | null>(null);
  const station = state?.stations.find((s) => s.id === rec.station_id);
  const cap = station?.capacity[rec.fuel_type];
  const route = state?.routes.find((r) => r.id === rec.allocation.route_id);
  const qtyNum = Number(qty);
  const qtyInvalid = !Number.isFinite(qtyNum) || qtyNum <= 0 || (route ? qtyNum > route.max_shipment : false);

  const simulate = async (alloc: Allocation, quantity = alloc.quantity) => {
    setSimBusy(true);
    setSimErr(null);
    try {
      const res = await api.simulate({ station_id: rec.station_id, fuel_type: rec.fuel_type, source_depot_id: alloc.source_depot_id, route_id: alloc.route_id, quantity });
      setWhat({ alloc: { ...alloc, quantity }, res });
    } catch (e) {
      setSimErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSimBusy(false);
    }
  };

  useEffect(() => {
    // run the what-if for the proposed allocation as soon as the card opens
    const t = setTimeout(() => void simulate(rec.allocation), 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rec.id]);

  const act = async (kind: "approve" | "reject") => {
    setBusy(kind);
    try {
      const out = kind === "approve" ? await api.approve(rec.id, qtyNum, note) : await api.reject(rec.id, note);
      if (out.status === "failed") toast.error(`Allocation failed: ${out.failure_reason ?? "unknown"}`);
      else if (kind === "approve") toast.success(`Recommendation #${rec.id} ${out.status}`, { description: out.sim_allocation_id ? `Simulator allocation ${out.sim_allocation_id}` : undefined });
      else toast(`Recommendation #${rec.id} rejected`);
      onChanged();
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.code}: ${e.message}` : String(e);
      toast.error(kind === "approve" ? "Approve failed" : "Reject failed", { description: msg });
    } finally {
      setBusy("");
    }
  };

  const im = rec.expected_impact;
  return (
    <Card>
      <CardHeader className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-lg">
            #{rec.id} · {nameOf(state, rec.station_id)} · {rec.fuel_type}
          </CardTitle>
          <div className="flex flex-wrap items-center gap-1.5">
            <Pill tone={rec.mode === "fallback" ? "warn" : "neutral"}>{rec.mode}</Pill>
            <Pill tone={rec.confidence >= 0.8 ? "good" : rec.confidence >= 0.6 ? "warn" : "bad"}>confidence {pct(rec.confidence)}</Pill>
            <StatusPill value={rec.status} />
          </div>
        </div>
        <div className="text-xs text-muted-foreground">Generated at tick {rec.tick} · simulated decision support</div>
        {rec.requires_human_review && (
          <div className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
            <TriangleAlert className="size-4 shrink-0" /> Human review requested — confidence is low or the planner used a fallback. Will not auto-execute.
          </div>
        )}
        {rec.mode === "fallback" && (
          <div className="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs text-muted-foreground">
            <Info className="size-3.5" /> Produced by the rule-based fallback policy (prediction/optimizer unavailable).
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-5">
        {/* situation + allocation + impact: the brief §9 card */}
        <div className="grid gap-3 sm:grid-cols-3">
          <Box label="Situation">
            <Row k="Current inventory" v={liters(rec.situation.current_inventory)} />
            <Row k="Expected demand (4 h)" v={liters(rec.situation.expected_demand_next_4h)} />
            <Row k="Projected stockout" v={<b className="text-red-600 dark:text-red-400">{hours(rec.situation.projected_stockout_hours)}</b>} />
          </Box>
          <Box label="Recommended allocation">
            <div className="text-xl font-semibold tabular-nums">{liters(rec.allocation.quantity)}</div>
            <Row k="From" v={nameOf(state, rec.allocation.source_depot_id)} />
            <Row k="Route" v={<span title={rec.allocation.route_id}>{route ? `${route.transit_ticks} ticks · ${route.status.toLowerCase()}` : rec.allocation.route_id}</span>} />
            <Row k="ETA" v={`tick ${rec.allocation.eta_tick}`} />
          </Box>
          <Box label="Expected impact">
            <div className="flex items-baseline gap-2 text-xl font-semibold tabular-nums">
              <span className="text-red-600 dark:text-red-400">{pct(im.stockout_prob_before)}</span>
              <ArrowRight className="size-4 self-center" />
              <span className="text-emerald-600 dark:text-emerald-400">{pct(im.stockout_prob_after)}</span>
            </div>
            <div className="text-[11px] text-muted-foreground">stockout risk before → after</div>
            <RiskBars before={im.stockout_prob_before} after={im.stockout_prob_after} />
            <Row k="Unmet demand avoided" v={liters(im.unmet_liters_avoided)} />
          </Box>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <ListBox label="Why — signals that influenced it" items={rec.signals} empty="No extra signals" />
          <ListBox label="Constraints respected" items={rec.constraints} empty="No binding constraints" />
        </div>

        {rec.explanation && (
          <div className="rounded-lg bg-muted/60 p-3 text-sm">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Explanation</div>
            <p className="whitespace-pre-line leading-relaxed">{rec.explanation}</p>
          </div>
        )}

        {/* alternatives */}
        <div>
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Alternatives</div>
          {rec.alternatives.length === 0 && <div className="text-sm text-muted-foreground">No feasible alternative route/depot.</div>}
          <div className="space-y-1.5">
            {rec.alternatives.map((a, i) => (
              <div key={i} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm">
                <span>
                  {liters(a.quantity)} from <b>{nameOf(state, a.source_depot_id)}</b> · ETA tick {a.eta_tick} · risk after{" "}
                  <b>{pct(a.stockout_prob_after)}</b>
                </span>
                <Button size="xs" variant="outline" onClick={() => void simulate(a)} disabled={simBusy}>
                  <FlaskConical /> What-if
                </Button>
              </div>
            ))}
          </div>
        </div>

        {/* what-if */}
        <div className="rounded-xl border p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <FlaskConical className="size-4" /> What-if simulation
              <span className="font-normal text-muted-foreground">(projection only — nothing is sent to the simulator)</span>
            </div>
            <Button size="sm" variant="outline" disabled={simBusy || qtyInvalid} onClick={() => void simulate(rec.allocation, qtyNum)}>
              {simBusy ? "Simulating…" : `Simulate ${liters(qtyNum)}`}
            </Button>
          </div>
          {simErr && <div className="text-xs text-red-600">{simErr}</div>}
          {what && (
            <>
              <div className="mb-1 text-xs text-muted-foreground">
                {liters(what.alloc.quantity)} from {nameOf(state, what.alloc.source_depot_id)}: risk{" "}
                <b className="text-red-600 dark:text-red-400">{pct(what.res.stockout_prob_before)}</b> →{" "}
                <b className="text-emerald-600 dark:text-emerald-400">{pct(what.res.stockout_prob_after)}</b>
              </div>
              <WhatIfChart r={what.res} capacity={cap} />
            </>
          )}
        </div>

        {/* result for already-decided recommendations */}
        {rec.status !== "pending" && (
          <div
            className={cn(
              "rounded-lg border p-3 text-sm",
              rec.status === "failed" ? "border-red-500/40 bg-red-500/10" : rec.status === "executed" ? "border-emerald-500/40 bg-emerald-500/10" : "",
            )}
          >
            Status <b>{rec.status}</b>
            {rec.sim_allocation_id != null && <> · simulator allocation <b>{String(rec.sim_allocation_id)}</b></>}
            {rec.failure_reason && <> · reason: <b>{rec.failure_reason}</b></>}
          </div>
        )}

        {/* approval gate */}
        {rec.status === "pending" && (
          <div className="space-y-2 rounded-xl border-2 border-dashed p-3">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <ShieldCheck className="size-4" /> Operator decision
              {!opKey && <span className="font-normal text-amber-700 dark:text-amber-400">— enter the operator key (top right) to approve or reject</span>}
            </div>
            <div className="grid gap-2 sm:grid-cols-[160px_1fr]">
              <div>
                <label className="text-xs text-muted-foreground" htmlFor="qty">
                  Quantity (L){route ? ` · max ${route.max_shipment}` : ""}
                </label>
                <Input id="qty" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value.replace(/[^0-9.]/g, ""))} aria-invalid={qtyInvalid} />
              </div>
              <div>
                <label className="text-xs text-muted-foreground" htmlFor="note">
                  Note (audit log)
                </label>
                <Textarea id="note" rows={1} value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="optional — why you approved/overrode/rejected" />
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void act("approve")} disabled={!!busy || qtyInvalid || !opKey}>
                <Check /> {busy === "approve" ? "Executing…" : `Approve & execute ${liters(qtyNum)}`}
              </Button>
              <Button variant="destructive" onClick={() => void act("reject")} disabled={!!busy || !opKey}>
                <X /> {busy === "reject" ? "Rejecting…" : "Reject"}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ModeCard() {
  const opKey = useOperatorKey();
  const mode = usePoll(api.mode, 10000);
  const [busy, setBusy] = useState(false);
  const m = mode.data;
  const save = async (next: Mode) => {
    setBusy(true);
    try {
      await api.setMode(next);
      toast.success(`Decision mode: ${next.mode}`);
      await mode.refresh();
    } catch (e) {
      toast.error("Mode change failed", { description: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };
  if (!m) return null;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card px-4 py-3 text-sm">
      <div className="flex items-center gap-3">
        <Switch checked={m.mode === "assisted"} disabled={busy || !opKey} onCheckedChange={(v: boolean) => void save({ ...m, mode: v ? "assisted" : "manual" })} aria-label="Assisted mode" />
        <div>
          <div className="font-medium">{m.mode === "assisted" ? "Assisted mode (autopilot for safe cases)" : "Manual mode (operator approves everything)"}</div>
          <div className="text-xs text-muted-foreground">
            {m.mode === "assisted"
              ? `Auto-executes only when confidence ≥ ${pct(m.auto_confidence_threshold)} and quantity ≤ ${liters(m.auto_max_quantity)}; everything else waits for review. Paused in degraded mode.`
              : "No allocation reaches the simulator without an operator approval."}
          </div>
        </div>
      </div>
      {!opKey && <span className="text-xs text-muted-foreground">Operator key required to change</span>}
    </div>
  );
}

function Box({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1 rounded-xl border p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      {children}
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <span className="text-muted-foreground">{k}</span>
      <span className="whitespace-nowrap text-right">{v}</span>
    </div>
  );
}

function ListBox({ label, items, empty }: { label: string; items: string[]; empty: string }) {
  return (
    <div className="rounded-xl border p-3">
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      {items.length === 0 ? (
        <div className="text-sm text-muted-foreground">{empty}</div>
      ) : (
        <ul className="list-disc space-y-0.5 pl-5 text-sm">
          {items.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RiskBars({ before, after }: { before: number; after: number }) {
  return (
    <div className="space-y-1 py-1">
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full bg-red-500" style={{ width: `${Math.min(100, before * 100)}%` }} />
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full bg-emerald-500" style={{ width: `${Math.min(100, after * 100)}%` }} />
      </div>
    </div>
  );
}
