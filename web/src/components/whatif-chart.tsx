"use client";
import { CartesianGrid, Line, LineChart, ReferenceLine, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import type { SimulateResult } from "@/lib/types";

const config = {
  without: { label: "Without shipment", color: "#ef4444" },
  with: { label: "With shipment", color: "#10b981" },
} satisfies ChartConfig;

/** Projected station inventory with vs without the proposed allocation (what-if, no writes). */
export function WhatIfChart({ r, capacity }: { r: SimulateResult; capacity?: number }) {
  const byTick = new Map<number, { tick: number; without?: number; with?: number }>();
  r.projection_without.forEach((p) => byTick.set(p.tick, { tick: p.tick, without: Math.round(p.inventory) }));
  r.projection_with.forEach((p) => byTick.set(p.tick, { ...(byTick.get(p.tick) ?? { tick: p.tick }), with: Math.round(p.inventory) }));
  const data = Array.from(byTick.values()).sort((a, b) => a.tick - b.tick);
  return (
    <ChartContainer config={config} className="aspect-auto h-52 w-full">
      <LineChart data={data} margin={{ left: 4, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="tick" tickLine={false} axisLine={false} fontSize={11} />
        <YAxis tickLine={false} axisLine={false} fontSize={11} width={48} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
        <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="4 4" />
        {capacity ? <ReferenceLine y={capacity} stroke="#71717a" strokeDasharray="4 4" label={{ value: "capacity", fontSize: 10, position: "insideTopRight" }} /> : null}
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(v) => `tick ${v}`} />} />
        <ChartLegend content={<ChartLegendContent />} />
        <Line dataKey="without" stroke="var(--color-without)" strokeWidth={2} dot={false} strokeDasharray="5 3" />
        <Line dataKey="with" stroke="var(--color-with)" strokeWidth={2.5} dot={false} />
      </LineChart>
    </ChartContainer>
  );
}
