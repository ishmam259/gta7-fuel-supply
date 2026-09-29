"use client";
import Link from "next/link";
import { ArrowRight, CalendarClock, Truck, Zap } from "lucide-react";
import { useLive } from "@/components/live-provider";
import { NetworkMap } from "@/components/network-map";
import { BriefingCard } from "@/components/briefing-card";
import { Empty, Kpi, Loading, PageHeader, RiskBadge, StaleNote, StatusPill } from "@/components/bits";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { RISK_ORDER, hours, liters, nameOf, pct } from "@/lib/format";
import type { FuelType, RiskLevel } from "@/lib/types";

export default function Overview() {
  const { state, bump } = useLive();
  const alerts = usePoll(() => api.alerts("open", 100), 5000, [bump]);
  const pending = usePoll(() => api.recommendations("pending"), 5000, [bump]);
  const s = state.data;

  if (!s) return state.error ? <StaleNote error={state.error} updatedAt={null} /> : <Loading label="Connecting to backend…" />;

  const risks = s.stations
    .flatMap((st) =>
      (Object.entries(st.risk) as [FuelType, { level: RiskLevel; stockout_hours: number | null; stockout_prob: number }][]).map(([fuel, r]) => ({
        station: st,
        fuel,
        ...r,
      })),
    )
    .sort((a, b) => RISK_ORDER[b.level] - RISK_ORDER[a.level] || b.stockout_prob - a.stockout_prob || (a.stockout_hours ?? 1e9) - (b.stockout_hours ?? 1e9))
    .slice(0, 6);
  const sl = s.metrics.service_level;
  const openAlerts = alerts.data?.length;
  const crit = alerts.data?.filter((a) => a.severity === "critical").length ?? 0;

  return (
    <>
      <PageHeader title="Operations overview" subtitle="Observe → Detect → Predict → Decide → Simulate → Act → Monitor → Recover" />
      <StaleNote error={state.error} updatedAt={state.updatedAt} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Service level" value={pct(sl, 1)} tone={sl >= 0.98 ? "good" : sl >= 0.95 ? "warn" : "bad"} hint={`served ${liters(s.metrics.served_demand_liters)}`} />
        <Kpi label="Unmet demand" value={liters(s.metrics.unmet_demand_liters)} tone={s.metrics.unmet_demand_liters > 0 ? "warn" : "good"} hint={`${s.metrics.allocation_failures} allocation failures`} />
        <Kpi label="Open alerts" value={openAlerts ?? "—"} tone={crit ? "bad" : openAlerts ? "warn" : "good"} hint={`${crit} critical`} />
        <Kpi
          label="Pending recommendations"
          value={pending.data?.length ?? "—"}
          tone={pending.data?.length ? "warn" : "good"}
          hint={<Link href="/recommendations" className="underline-offset-2 hover:underline">open inbox →</Link>}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Network map</CardTitle>
            <Link href="/network" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
              details <ArrowRight className="size-3" />
            </Link>
          </CardHeader>
          <CardContent>
            <NetworkMap state={s} />
          </CardContent>
        </Card>
        <BriefingCard />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Top shortage risks</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5">
            {risks.map((r) => (
              <div key={`${r.station.id}-${r.fuel}`} className="flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm">
                <div className="min-w-0">
                  <div className="truncate font-medium">
                    {r.station.name} · {r.fuel}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {liters(r.station.inventory[r.fuel])} left · stockout in {hours(r.stockout_hours)}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs tabular-nums text-muted-foreground" title="24 h stockout risk if no action">24 h risk {pct(r.stockout_prob)}</span>
                  <RiskBadge level={r.level} />
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <div className="grid gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="size-4" /> Active disruptions & events
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5">
              {s.active_events.length === 0 && <Empty>No active events — normal operations</Empty>}
              {s.active_events.map((e) => (
                <div key={e.id} className="flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm">
                  <div className="min-w-0">
                    <div className="font-medium">{e.type.replace(/_/g, " ")}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      ticks {e.start_tick}–{e.end_tick} · {describeParams(e.parameters, s)}
                    </div>
                  </div>
                  <StatusPill value={e.status} />
                </div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CalendarClock className="size-4" /> Incoming supply & in transit
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5 text-sm">
              {s.upcoming_supply.slice(0, 4).map((u) => (
                <div key={u.id} className="flex items-center justify-between gap-2">
                  <span className="truncate">
                    {nameOf(s, u.depot_id)} · {u.fuel_type} · {liters(u.quantity)}
                  </span>
                  <span className="flex items-center gap-2 text-xs text-muted-foreground">
                    tick {u.planned_tick} <StatusPill value={u.status} />
                  </span>
                </div>
              ))}
              {s.in_transit.map((t) => (
                <div key={t.id} className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 truncate">
                    <Truck className="size-3.5" /> {t.route_id.replace("route-", "")} · {t.fuel_type} · {liters(t.quantity)}
                  </span>
                  <span className="text-xs text-muted-foreground">arrives tick {t.expected_arrival_tick}</span>
                </div>
              ))}
              {!s.upcoming_supply.length && !s.in_transit.length && <Empty>Nothing scheduled</Empty>}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function describeParams(p: Record<string, unknown>, s: Parameters<typeof nameOf>[0]): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(p ?? {})) {
    if (Array.isArray(v)) parts.push(v.map((x) => nameOf(s, String(x))).join(", "));
    else parts.push(`${k.replace(/_/g, " ")} ${v}`);
  }
  return parts.join(" · ") || "—";
}
