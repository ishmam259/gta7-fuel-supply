"use client";
import { Bar, BarChart, CartesianGrid, LabelList, Line, LineChart, XAxis, YAxis } from "recharts";
import { BrainCircuit, Calculator, Scale } from "lucide-react";
import { Empty, Kpi, Loading, PageHeader, Pill, SimulatedBadge, StaleNote } from "@/components/bits";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { liters, num, pct } from "@/lib/format";
import type { RlOfflineRow, RlRealResult, RlSummary } from "@/lib/types";

const LABEL: Record<string, string> = { no_action: "No action", deterministic_lp: "Deterministic (LP)", lp_24h: "Deterministic (LP)", rl: "RL-tuned" };
const COLOR: Record<string, string> = { no_action: "#9ca3af", deterministic_lp: "#2563eb", rl: "#16a34a" };

const slConfig = {
  no_action: { label: LABEL.no_action, color: COLOR.no_action },
  deterministic_lp: { label: LABEL.deterministic_lp, color: COLOR.deterministic_lp },
  rl: { label: LABEL.rl, color: COLOR.rl },
} satisfies ChartConfig;
const truckConfig = { trucks: { label: "Trucks sent", color: COLOR.deterministic_lp } } satisfies ChartConfig;

const pctDelta = (a: number, b: number) => (b ? Math.round(((a - b) / b) * 100) : 0);

export default function RlPage() {
  const q = usePoll(() => api.rlSummary(), 60000);
  const s: RlSummary | undefined = q.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title="RL vs Deterministic"
        subtitle="Same network, same crisis, same seed: what the learned policy changes compared with the deterministic optimizer"
      >
        <SimulatedBadge />
      </PageHeader>
      <StaleNote error={q.error} updatedAt={q.updatedAt} />
      {!s ? <Loading /> : !s.available ? <Empty>No saved RL results on the backend.</Empty> : <Body s={s} />}
    </div>
  );
}

function Body({ s }: { s: RlSummary }) {
  const real = s.real_simulator;
  const by = Object.fromEntries((real?.results ?? []).map((r) => [r.policy, r])) as Record<string, RlRealResult>;
  const lp = by.deterministic_lp, rl = by.rl, none = by.no_action;

  return (
    <>
      {lp && rl && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi label="Service level · Deterministic" value={pct(lp.service_level, 1)} hint={`${liters(lp.unmet_liters)} lost`} tone="good" />
          <Kpi label="Service level · RL" value={pct(rl.service_level, 1)} hint={`${liters(rl.unmet_liters)} lost`} tone="good" />
          <Kpi label="Trucks · Deterministic → RL" value={`${lp.trucks_sent} → ${rl.trucks_sent}`}
               hint={`${pctDelta(rl.trucks_sent, lp.trucks_sent)}% trucks, same service`} tone="good" />
          <Kpi label="No action (same crisis)" value={none ? pct(none.service_level, 1) : "—"}
               hint={none ? `${liters(none.unmet_liters)} lost` : undefined} tone="bad" />
        </div>
      )}

      {real && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Service level over time: real simulator</CardTitle>
              <CardDescription>
                {real.ticks} ticks ({real.ticks / 96} simulated days), every recommendation approved and sent. The deterministic
                line (dashed) sits under RL: both stay at 100%.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ChartContainer config={slConfig} className="h-72 w-full">
                <LineChart data={curveRows(real.results)} margin={{ left: 4, right: 12 }}>
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="tick" tickLine={false} axisLine={false} tickMargin={6} />
                  <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} width={42} tickLine={false} axisLine={false} />
                  <ChartTooltip content={<ChartTooltipContent labelFormatter={(v) => `tick ${v}`} />} />
                  <ChartLegend content={<ChartLegendContent />} />
                  <Line dataKey="no_action" stroke="var(--color-no_action)" strokeWidth={2} dot={false} />
                  <Line dataKey="rl" stroke="var(--color-rl)" strokeWidth={3} dot={false} />
                  <Line dataKey="deterministic_lp" stroke="var(--color-deterministic_lp)" strokeWidth={2} strokeDasharray="6 4" dot={false} />
                </LineChart>
              </ChartContainer>
              <div className="mt-3 flex flex-wrap gap-2">
                {real.crisis.map((e, i) => (
                  <Pill key={i} tone="warn">{e.type.replace("_", " ")} · tick +{e.offset} for {e.duration_ticks}</Pill>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Trucks sent</CardTitle>
              <CardDescription>Fewer, bigger deliveries for the same fuel.</CardDescription>
            </CardHeader>
            <CardContent>
              <ChartContainer config={truckConfig} className="h-56 w-full">
                <BarChart data={[lp, rl].filter(Boolean).map((r) => ({ name: LABEL[r.policy], trucks: r.trucks_sent, fill: COLOR[r.policy] }))}>
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="name" tickLine={false} axisLine={false} />
                  <YAxis hide />
                  <Bar dataKey="trucks" radius={6}>
                    <LabelList dataKey="trucks" position="top" className="fill-foreground" />
                  </Bar>
                </BarChart>
              </ChartContainer>
              <Table className="mt-2">
                <TableBody>
                  {[lp, rl].filter(Boolean).map((r) => (
                    <TableRow key={r.policy}>
                      <TableCell>{LABEL[r.policy]}</TableCell>
                      <TableCell className="text-right tabular-nums">{liters(r.liters_shipped)} shipped</TableCell>
                      <TableCell className="text-right tabular-nums">{r.rejected} rejected</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}

      {s.offline && (
        <Card>
          <CardHeader>
            <CardTitle>Offline evaluation: {s.offline.runs} unseen runs × {s.offline.days_per_run} days</CardTitle>
            <CardDescription>Same seeds for every policy (identical stock, crises and demand noise). Not used for training.</CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Scenario</TableHead><TableHead>Policy</TableHead>
                  <TableHead className="text-right">Service level</TableHead><TableHead className="text-right">Worst run</TableHead>
                  <TableHead className="text-right">Liters lost</TableHead><TableHead className="text-right">Trucks</TableHead>
                  <TableHead className="text-right">vs deterministic</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(["calm", "crisis"] as const).flatMap((sc) =>
                  (["no_action", "lp_24h", "rl"] as const).map((p) => {
                    const row: RlOfflineRow = s.offline![sc][p];
                    const base = s.offline![sc].lp_24h.trucks;
                    return (
                      <TableRow key={sc + p} className={p === "rl" ? "bg-emerald-50/60 dark:bg-emerald-950/30" : undefined}>
                        <TableCell className="capitalize">{sc}</TableCell>
                        <TableCell>{LABEL[p]}</TableCell>
                        <TableCell className="text-right tabular-nums">{pct(row.service_level, 2)}</TableCell>
                        <TableCell className="text-right tabular-nums">{pct(row.worst_run, 1)}</TableCell>
                        <TableCell className="text-right tabular-nums">{liters(row.unmet_liters)}</TableCell>
                        <TableCell className="text-right tabular-nums">{num(row.trucks, 1)}</TableCell>
                        <TableCell className="text-right tabular-nums">{p === "rl" ? `${pctDelta(row.trucks, base)}% trucks` : "—"}</TableCell>
                      </TableRow>
                    );
                  }),
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {s.policy && (
          <Card>
            <CardHeader>
              <CardTitle>What RL learned</CardTitle>
              <CardDescription>
                Target cover chosen per situation ({s.policy.states_learned} situations, trained on {s.policy.episodes} runs of 4 days
                {s.policy.train_seconds ? ` in ${Math.round(s.policy.train_seconds)} s` : ""}). Deterministic always uses 24 h.
              </CardDescription>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Cover left</TableHead><TableHead>Depot stock</TableHead><TableHead>Spike</TableHead>
                    <TableHead>Route</TableHead><TableHead className="text-right">RL picks</TableHead><TableHead className="text-right">Seen</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {s.policy.rows.slice(0, 10).map((r, i) => (
                    <TableRow key={i}>
                      <TableCell>{r.cover_left}</TableCell>
                      <TableCell>{r.depot_stock}</TableCell>
                      <TableCell>{r.spike ? <Pill tone="warn">spike</Pill> : "—"}</TableCell>
                      <TableCell>{r.route_open ? "open" : <Pill tone="bad">down</Pill>}</TableCell>
                      <TableCell className="text-right font-semibold tabular-nums">
                        <span className={r.chosen_cover_h > 24 ? "text-emerald-600" : r.chosen_cover_h < 24 ? "text-amber-600" : undefined}>
                          {r.chosen_cover_h} h
                        </span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{num(r.visits)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}

        {s.how_it_works && (
          <Card>
            <CardHeader>
              <CardTitle>How the two approaches differ</CardTitle>
              <CardDescription>RL only picks the target; the same optimizer still enforces every simulator rule.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <Row icon={Calculator} title="Deterministic (default)" text={s.how_it_works.deterministic} />
              <Row icon={BrainCircuit} title="RL-tuned (option, mode = rl)" text={s.how_it_works.rl} />
              <Row icon={Scale} title="Reward & training" text={`${s.how_it_works.reward} ${s.how_it_works.training}`} />
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200">
                <span className="font-semibold">Verdict: </span>{s.how_it_works.verdict}
              </div>
              <p className="text-xs text-muted-foreground">
                Saved results. Rerun: <code>python -m app.intel.compare_policies 192</code> (resets the simulator).
              </p>
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}

function Row({ icon: Icon, title, text }: { icon: typeof Calculator; title: string; text: string }) {
  return (
    <div className="flex gap-3">
      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div><div className="font-medium">{title}</div><div className="text-muted-foreground">{text}</div></div>
    </div>
  );
}

function curveRows(results: RlRealResult[]) {
  const rows = new Map<number, Record<string, number>>();
  for (const r of results) {
    for (const p of r.curve) {
      const row = rows.get(p.tick) ?? { tick: p.tick };
      row[r.policy] = Math.round(p.service_level * 1000) / 10;
      rows.set(p.tick, row);
    }
  }
  return [...rows.values()].sort((a, b) => a.tick - b.tick);
}
