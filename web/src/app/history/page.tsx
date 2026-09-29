"use client";
import { useState } from "react";
import { Area, AreaChart, Bar, CartesianGrid, ComposedChart, Line, XAxis, YAxis } from "recharts";
import { useLive } from "@/components/live-provider";
import { Empty, Loading, PageHeader, Pill, StaleNote } from "@/components/bits";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { fuelColor, liters, nameOf, pct, timeAgo } from "@/lib/format";
import { FUELS, type FuelType } from "@/lib/types";

const slConfig = {
  service_level: { label: "Service level", color: "#10b981" },
  unmet_demand_liters: { label: "Unmet demand (L)", color: "#ef4444" },
} satisfies ChartConfig;

const allocConfig = {
  allocation_liters: { label: "Allocated (L)", color: "#0ea5e9" },
  open_alerts: { label: "Open alerts", color: "#f59e0b" },
} satisfies ChartConfig;

export default function HistoryPage() {
  const { state, bump } = useLive();
  const hist = usePoll(() => api.metricsHistory(500), 5000);
  const decisions = usePoll(() => api.decisions(100), 5000, [bump]);
  const points = [...(hist.data ?? [])].sort((a, b) => a.tick - b.tick);

  return (
    <>
      <PageHeader title="History & forecast" subtitle="Service level over ticks, demand forecast with uncertainty band, and the decision audit trail" />
      <StaleNote error={hist.error} updatedAt={hist.updatedAt} />

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Service level over ticks</CardTitle>
            <CardDescription>served ÷ (served + unmet) — the headline outcome metric</CardDescription>
          </CardHeader>
          <CardContent>
            {!hist.data && !hist.error && <Loading />}
            {hist.data && points.length === 0 && <Empty>No history yet — run the simulation for a few ticks.</Empty>}
            {points.length > 0 && (
              <ChartContainer config={slConfig} className="aspect-auto h-64 w-full">
                <ComposedChart data={points} margin={{ left: 4, right: 4, top: 8 }}>
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="tick" tickLine={false} axisLine={false} fontSize={11} minTickGap={24} />
                  <YAxis yAxisId="sl" domain={[(min: number) => Math.max(0, Math.floor(min * 20) / 20), 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} tickLine={false} axisLine={false} fontSize={11} width={40} />
                  <YAxis yAxisId="un" orientation="right" tickLine={false} axisLine={false} fontSize={11} width={44} tickFormatter={(v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : v)} />
                  <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, p) => `tick ${p?.[0]?.payload?.tick}`} />} />
                  <ChartLegend content={<ChartLegendContent />} />
                  <Bar yAxisId="un" dataKey="unmet_demand_liters" fill="var(--color-unmet_demand_liters)" opacity={0.5} />
                  <Line yAxisId="sl" dataKey="service_level" stroke="var(--color-service_level)" strokeWidth={2.5} dot={false} />
                </ComposedChart>
              </ChartContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Allocations & alerts</CardTitle>
            <CardDescription>litres dispatched per tick vs open alert count</CardDescription>
          </CardHeader>
          <CardContent>
            {points.length > 0 ? (
              <ChartContainer config={allocConfig} className="aspect-auto h-64 w-full">
                <ComposedChart data={points} margin={{ left: 4, right: 4, top: 8 }}>
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="tick" tickLine={false} axisLine={false} fontSize={11} minTickGap={24} />
                  <YAxis yAxisId="l" tickLine={false} axisLine={false} fontSize={11} width={44} tickFormatter={(v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : v)} />
                  <YAxis yAxisId="a" orientation="right" allowDecimals={false} tickLine={false} axisLine={false} fontSize={11} width={28} />
                  <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, p) => `tick ${p?.[0]?.payload?.tick}`} />} />
                  <ChartLegend content={<ChartLegendContent />} />
                  <Bar yAxisId="l" dataKey="allocation_liters" fill="var(--color-allocation_liters)" opacity={0.7} />
                  <Line yAxisId="a" type="stepAfter" dataKey="open_alerts" stroke="var(--color-open_alerts)" strokeWidth={2} dot={false} />
                </ComposedChart>
              </ChartContainer>
            ) : (
              <Empty>No history yet</Empty>
            )}
          </CardContent>
        </Card>
      </div>

      <ForecastCard stations={state.data?.stations.map((s) => ({ id: s.id, name: s.name })) ?? []} tick={state.data?.instance.tick} />

      <Card>
        <CardHeader>
          <CardTitle>Decision audit history</CardTitle>
          <CardDescription>Every approve / reject / execution / fallback, who did it and the result</CardDescription>
        </CardHeader>
        <CardContent>
          <StaleNote error={decisions.error} updatedAt={decisions.updatedAt} />
          {!decisions.data && !decisions.error && <Loading />}
          {decisions.data && decisions.data.length === 0 && <Empty>No decisions yet. Approve or reject a recommendation to start the audit trail.</Empty>}
          {decisions.data && decisions.data.length > 0 && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>Tick</TableHead>
                    <TableHead>Actor</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Recommendation</TableHead>
                    <TableHead>Result</TableHead>
                    <TableHead>Note</TableHead>
                    <TableHead>When</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {decisions.data.map((d) => (
                    <TableRow key={d.id}>
                      <TableCell className="tabular-nums text-muted-foreground">{d.id}</TableCell>
                      <TableCell className="tabular-nums">{d.tick}</TableCell>
                      <TableCell>
                        <Pill tone={d.actor === "operator" ? "neutral" : d.actor === "autopilot" ? "warn" : "neutral"}>{d.actor}</Pill>
                      </TableCell>
                      <TableCell className="font-medium">{d.action}</TableCell>
                      <TableCell>{d.recommendation_id != null ? `#${d.recommendation_id}` : "—"}</TableCell>
                      <TableCell>
                        <Pill tone={d.result === "OK" ? "good" : "bad"} className="normal-case">
                          {d.result}
                        </Pill>
                      </TableCell>
                      <TableCell className="max-w-[260px] truncate text-muted-foreground" title={d.note ?? ""}>
                        {d.note || "—"}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">{timeAgo(d.created_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </>
  );
}

function ForecastCard({ stations, tick }: { stations: { id: string; name: string }[]; tick?: number }) {
  const { state } = useLive();
  const [stationId, setStationId] = useState("");
  const [fuel, setFuel] = useState<FuelType>("OCTANE");
  const sid = stationId || stations[0]?.id || "";
  const fc = usePoll(() => (sid ? api.forecast(sid, fuel) : Promise.resolve([])), 10000, [sid, fuel]);
  const f = fc.data?.[0];
  const base = tick ?? 0;
  const data =
    f?.per_tick.map((v, i) => ({
      tick: base + i + 1,
      demand: Math.round(v),
      band: [Math.round(f.lower[i] ?? v), Math.round(f.upper[i] ?? v)] as [number, number],
    })) ?? [];
  const total = f?.per_tick.reduce((a, b) => a + b, 0);
  const inv = state.data?.stations.find((s) => s.id === sid)?.inventory[fuel];
  const config = {
    demand: { label: "Forecast demand / tick (L)", color: fuelColor[fuel] },
    band: { label: "Uncertainty band", color: fuelColor[fuel] },
  } satisfies ChartConfig;

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>Demand forecast (next 16 ticks = 4 h)</CardTitle>
          <CardDescription>hour-of-day profile × demand multiplier, band = ± residual spread</CardDescription>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select className="h-8 rounded-lg border bg-background px-2 text-sm" value={sid} onChange={(e) => setStationId(e.target.value)} aria-label="Station">
            {stations.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <select className="h-8 rounded-lg border bg-background px-2 text-sm" value={fuel} onChange={(e) => setFuel(e.target.value as FuelType)} aria-label="Fuel">
            {FUELS.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <StaleNote error={fc.error} updatedAt={fc.updatedAt} />
        {!fc.data && !fc.error && <Loading />}
        {fc.data && !f && <Empty>No forecast for {nameOf(state.data, sid)} {fuel} yet.</Empty>}
        {f && (
          <>
            <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
              <span>
                Expected next 4 h: <b>{liters(total)}</b>
              </span>
              <span>
                In stock: <b>{liters(inv)}</b>
              </span>
              <span>
                Recent error (MAPE): <b>{f.mape_recent == null ? "—" : pct(f.mape_recent, 1)}</b>
              </span>
            </div>
            <ChartContainer config={config} className="aspect-auto h-64 w-full">
              <AreaChart data={data} margin={{ left: 4, right: 8, top: 8 }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="tick" tickLine={false} axisLine={false} fontSize={11} />
                <YAxis tickLine={false} axisLine={false} fontSize={11} width={44} />
                <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, p) => `tick ${p?.[0]?.payload?.tick}`} />} />
                <ChartLegend content={<ChartLegendContent />} />
                <Area dataKey="band" stroke="none" fill="var(--color-band)" fillOpacity={0.18} isAnimationActive={false} />
                <Area dataKey="demand" stroke="var(--color-demand)" strokeWidth={2.5} fill="none" isAnimationActive={false} />
              </AreaChart>
            </ChartContainer>
          </>
        )}
      </CardContent>
    </Card>
  );
}

