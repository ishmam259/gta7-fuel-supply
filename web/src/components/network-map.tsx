"use client";
// Depots (left) → stations (right). Route line color = route status; dashed = in-transit shipment on it.
import { cn } from "@/lib/utils";
import { RISK_ORDER } from "@/lib/format";
import type { NetworkState, RiskLevel } from "@/lib/types";

const ROUTE_COLOR: Record<string, string> = { AVAILABLE: "#10b981", DISRUPTED: "#ef4444", DELAYED: "#f59e0b", CLOSED: "#71717a" };
const RISK_FILL: Record<RiskLevel, string> = { ok: "#10b981", watch: "#f59e0b", critical: "#ef4444", outage: "#52525b" };

export function worstRisk(s: NetworkState["stations"][number]): RiskLevel {
  if (s.status && s.status !== "OPEN") return "outage";
  return Object.values(s.risk ?? {}).reduce<RiskLevel>((w, r) => (r && RISK_ORDER[r.level] > RISK_ORDER[w] ? r.level : w), "ok");
}

export function NetworkMap({ state, onSelect }: { state: NetworkState; onSelect?: (id: string) => void }) {
  const W = 760;
  const rowH = 78;
  const rows = Math.max(state.depots.length, state.stations.length, 2);
  const H = rows * rowH + 30;
  const depotY = (i: number) => 15 + (H - 30) * ((i + 0.5) / state.depots.length);
  const stationY = (i: number) => 15 + (H - 30) * ((i + 0.5) / state.stations.length);
  const dX = 150;
  const sX = W - 190;
  const moving = new Map<string, number>();
  state.in_transit.forEach((t) => moving.set(t.route_id, (moving.get(t.route_id) ?? 0) + t.quantity));

  return (
    <div className="w-full overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full min-w-[560px]" role="img" aria-label="Fuel network: depots to stations">
        {state.routes.map((r) => {
          const di = state.depots.findIndex((d) => d.id === r.source_depot_id);
          const si = state.stations.findIndex((s) => s.id === r.destination_station_id);
          if (di < 0 || si < 0) return null;
          const y1 = depotY(di);
          const y2 = stationY(si);
          const color = ROUTE_COLOR[r.status] ?? "#71717a";
          const qty = moving.get(r.id);
          const mx = (dX + sX) / 2;
          const my = (y1 + y2) / 2;
          return (
            <g key={r.id}>
              <title>{`${r.id} · ${r.status} · ${r.transit_ticks} ticks · max ${r.max_shipment} L`}</title>
              <path d={`M ${dX + 60} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${sX - 10} ${y2}`} fill="none" stroke={color} strokeWidth={r.status === "AVAILABLE" ? 2 : 3}
                strokeDasharray={r.status === "AVAILABLE" ? undefined : "6 4"} opacity={0.85} />
              {qty ? (
                <g>
                  <circle r="5" fill="#0ea5e9">
                    <animateMotion dur="3s" repeatCount="indefinite" path={`M ${dX + 60} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${sX - 10} ${y2}`} />
                  </circle>
                  <text x={mx} y={my - 6} textAnchor="middle" className="fill-sky-600 text-[10px] font-semibold dark:fill-sky-400">
                    {Math.round(qty).toLocaleString()} L moving
                  </text>
                </g>
              ) : r.status !== "AVAILABLE" ? (
                <text x={mx} y={my - 6} textAnchor="middle" fill={color} className="text-[10px] font-bold">
                  {r.status}
                </text>
              ) : null}
            </g>
          );
        })}
        {state.depots.map((d, i) => {
          const y = depotY(i);
          const tot = Object.values(d.inventory).reduce((a, b) => a + (b ?? 0), 0);
          const cap = Object.values(d.capacity).reduce((a, b) => a + (b ?? 0), 0);
          const bad = d.status !== "OPEN";
          return (
            <g key={d.id} className={cn(onSelect && "cursor-pointer")} onClick={() => onSelect?.(d.id)}>
              <rect x={dX - 140} y={y - 26} width={200} height={52} rx={10} className="fill-card stroke-border" strokeWidth={1.5}
                stroke={bad ? "#ef4444" : undefined} />
              <text x={dX - 128} y={y - 7} className="fill-foreground text-[12px] font-semibold">{d.name}</text>
              <text x={dX - 128} y={y + 9} className="fill-muted-foreground text-[10px]">
                {d.status} · {Math.round((tot / (cap || 1)) * 100)}% full · dispatch {Math.round(d.dispatch_used_this_tick)}/{Math.round(d.dispatch_capacity_per_tick)}
              </text>
              <rect x={dX - 128} y={y + 14} width={176} height={4} rx={2} className="fill-muted" />
              <rect x={dX - 128} y={y + 14} width={176 * Math.min(1, tot / (cap || 1))} height={4} rx={2} fill="#0ea5e9" />
            </g>
          );
        })}
        {state.stations.map((s, i) => {
          const y = stationY(i);
          const lvl = worstRisk(s);
          return (
            <g key={s.id} className={cn(onSelect && "cursor-pointer")} onClick={() => onSelect?.(s.id)}>
              <rect x={sX - 10} y={y - 26} width={190} height={52} rx={10} className="fill-card" stroke={RISK_FILL[lvl]} strokeWidth={lvl === "ok" ? 1.5 : 2.5} />
              <circle cx={sX + 6} cy={y - 10} r={5} fill={RISK_FILL[lvl]}>
                {lvl === "critical" && <animate attributeName="opacity" values="1;0.3;1" dur="1.2s" repeatCount="indefinite" />}
              </circle>
              <text x={sX + 17} y={y - 6} className="fill-foreground text-[12px] font-semibold">{s.name.length > 24 ? s.name.slice(0, 23) + "…" : s.name}</text>
              <text x={sX + 2} y={y + 12} className="fill-muted-foreground text-[10px]">
                {(["DIESEL", "PETROL", "OCTANE"] as const).map((f) => {
                  const r = s.risk?.[f];
                  return (
                    <tspan key={f} fill={r ? RISK_FILL[r.level] : undefined} fontWeight={r && r.level !== "ok" ? 700 : 400}>
                      {f[0]} {s.capacity[f] ? Math.round(((s.inventory[f] ?? 0) / s.capacity[f]!) * 100) : 0}%{"  "}
                    </tspan>
                  );
                })}
                · {s.status}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <Legend color="#10b981" label="route available / station ok" />
        <Legend color="#f59e0b" label="watch" />
        <Legend color="#ef4444" label="disrupted / critical" />
        <Legend color="#0ea5e9" label="shipment in transit" />
        <span>D/P/O = Diesel/Petrol/Octane fill %</span>
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="size-2.5 rounded-full" style={{ background: color }} /> {label}
    </span>
  );
}
