"use client";
import { Truck, Warehouse, Fuel as FuelIcon, MapPin } from "lucide-react";
import { useLive } from "@/components/live-provider";
import { Empty, InvBar, Loading, PageHeader, RiskBadge, StaleNote, StatusPill } from "@/components/bits";
import { worstRisk } from "@/components/network-map";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { FUELS } from "@/lib/types";
import { liters, nameOf, num } from "@/lib/format";

export default function NetworkPage() {
  const { state } = useLive();
  const s = state.data;
  if (!s) return state.error ? <StaleNote error={state.error} updatedAt={null} /> : <Loading label="Connecting to backend…" />;
  const tick = s.instance.tick;

  return (
    <>
      <PageHeader title="Stations & depots" subtitle="Inventory vs capacity, stockout risk, incoming supply and shipments in transit" />
      <StaleNote error={state.error} updatedAt={state.updatedAt} />

      <section className="space-y-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          <FuelIcon className="size-4" /> Stations
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          {s.stations.map((st) => {
            const incoming = s.in_transit.filter((t) => s.routes.find((r) => r.id === t.route_id)?.destination_station_id === st.id);
            const routes = s.routes.filter((r) => r.destination_station_id === st.id);
            return (
              <Card key={st.id} id={st.id}>
                <CardHeader className="flex flex-row items-start justify-between gap-2">
                  <div className="min-w-0">
                    <CardTitle className="truncate">{st.name}</CardTitle>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <MapPin className="size-3" /> {nameOf(s, st.region_id)}
                      </span>
                      <span>· profile {st.demand_profile.replace(/_/g, " ")}</span>
                      <span className={st.demand_multiplier > 1.05 ? "font-semibold text-amber-600 dark:text-amber-400" : ""}>
                        · demand ×{num(st.demand_multiplier, 2)}
                      </span>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <StatusPill value={st.status} />
                    <RiskBadge level={worstRisk(st)} label={st.status !== "OPEN" ? "outage" : undefined} />
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {FUELS.map((f) => (
                    <InvBar key={f} fuel={f} inv={st.inventory[f]} cap={st.capacity[f]} risk={st.risk?.[f]} />
                  ))}
                  <div className="rounded-lg bg-muted/50 p-2.5 text-xs">
                    <div className="mb-1 font-semibold">Incoming</div>
                    {incoming.length === 0 && <div className="text-muted-foreground">No shipments in transit</div>}
                    {incoming.map((t) => (
                      <div key={t.id} className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-1">
                          <Truck className="size-3" /> {t.fuel_type} {liters(t.quantity)} from {nameOf(s, s.routes.find((r) => r.id === t.route_id)?.source_depot_id)}
                        </span>
                        <span className="text-muted-foreground">
                          tick {t.expected_arrival_tick} ({Math.max(0, t.expected_arrival_tick - tick)} left)
                        </span>
                      </div>
                    ))}
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {routes.map((r) => (
                        <span key={r.id} className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground" title={`max ${r.max_shipment} L`}>
                          from {nameOf(s, r.source_depot_id).replace(" Depot", "")} · {r.transit_ticks}t · <StatusText v={r.status} />
                        </span>
                      ))}
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          <Warehouse className="size-4" /> Depots
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          {s.depots.map((d) => {
            const supply = s.upcoming_supply.filter((u) => u.depot_id === d.id);
            const used = d.dispatch_used_this_tick ?? 0;
            return (
              <Card key={d.id} id={d.id}>
                <CardHeader className="flex flex-row items-start justify-between gap-2">
                  <div>
                    <CardTitle>{d.name}</CardTitle>
                    <div className="text-xs text-muted-foreground">{nameOf(s, d.region_id)}</div>
                  </div>
                  <StatusPill value={d.status} />
                </CardHeader>
                <CardContent className="space-y-3">
                  {FUELS.map((f) => (
                    <InvBar key={f} fuel={f} inv={d.inventory[f]} cap={d.capacity[f]} />
                  ))}
                  <div className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="font-medium">Dispatch this tick</span>
                      <span className="tabular-nums text-muted-foreground">
                        {liters(used)} / {liters(d.dispatch_capacity_per_tick)}
                      </span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div
                        className={used / d.dispatch_capacity_per_tick > 0.9 ? "h-full bg-red-500" : "h-full bg-sky-500"}
                        style={{ width: `${Math.min(100, (used / (d.dispatch_capacity_per_tick || 1)) * 100)}%` }}
                      />
                    </div>
                  </div>
                  <div className="rounded-lg bg-muted/50 p-2.5 text-xs">
                    <div className="mb-1 font-semibold">Upcoming supply</div>
                    {supply.length === 0 && <div className="text-muted-foreground">None scheduled</div>}
                    {supply.map((u) => (
                      <div key={u.id} className="flex items-center justify-between gap-2 py-0.5">
                        <span>
                          {u.fuel_type} {liters(u.quantity)}
                        </span>
                        <span className="flex items-center gap-1.5 text-muted-foreground">
                          tick {u.planned_tick} <StatusPill value={u.status} />
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Routes</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Route</TableHead>
                  <TableHead>Transit</TableHead>
                  <TableHead>Max shipment</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.routes.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-medium">
                      {nameOf(s, r.source_depot_id).replace(" Depot", "")} → {nameOf(s, r.destination_station_id)}
                    </TableCell>
                    <TableCell>{r.transit_ticks} ticks</TableCell>
                    <TableCell>{liters(r.max_shipment)}</TableCell>
                    <TableCell>
                      <StatusPill value={r.status} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Regional demand (last 4 h)</CardTitle>
          </CardHeader>
          <CardContent>
            {s.regions.length === 0 && <Empty>No regions</Empty>}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Region</TableHead>
                  <TableHead>Factor</TableHead>
                  {FUELS.map((f) => (
                    <TableHead key={f} className="text-right">
                      {f}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.regions.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-medium">{r.name}</TableCell>
                    <TableCell className={r.demand_factor > 1.05 ? "font-semibold text-amber-600 dark:text-amber-400" : ""}>×{num(r.demand_factor, 2)}</TableCell>
                    {FUELS.map((f) => (
                      <TableCell key={f} className="text-right tabular-nums">
                        {liters(r.demand_last_4h?.[f])}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function StatusText({ v }: { v: string }) {
  const bad = v !== "AVAILABLE";
  return <b className={bad ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}>{v.toLowerCase()}</b>;
}
