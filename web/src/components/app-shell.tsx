"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import {
  Activity, AlertTriangle, Bell, Bot, ClipboardList, Fuel, Gauge, History, Inbox, Menu, Network, ShieldAlert, X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { anyMocked } from "@/lib/api";
import { useLive } from "./live-provider";
import { OperatorKeyButton } from "./operator-key";
import { SimulatedBadge, StatusPill } from "./bits";

const NAV = [
  { href: "/", label: "Overview", icon: Gauge },
  { href: "/network", label: "Stations & Depots", icon: Network },
  { href: "/alerts", label: "Alerts", icon: Bell },
  { href: "/recommendations", label: "Recommendations", icon: Inbox },
  { href: "/history", label: "History & Forecast", icon: History },
  { href: "/assistant", label: "AI Assistant", icon: Bot },
  { href: "/system", label: "System Status", icon: Activity },
  { href: "/control", label: "Control & Chaos", icon: ShieldAlert },
];

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  return (
    <nav className="flex flex-col gap-0.5 p-2">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors",
              active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon className="size-4" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function DegradedBanner() {
  const { state, status } = useLive();
  const fresh = state.data?.data_freshness;
  const backendDown = !!state.error && !!status.error;
  const breakerOpen = status.data && status.data.circuit_breaker !== "closed";
  const msgs: string[] = [];
  if (backendDown) msgs.push(`Backend unreachable (${state.error}) — showing the last good state, retrying every 3 s`);
  else {
    if (fresh?.degraded || breakerOpen)
      msgs.push(`Degraded mode: simulator link ${status.data?.circuit_breaker === "open" ? "circuit breaker OPEN" : "unstable"} — serving cached state, auto-execution paused`);
    if (fresh?.stale) msgs.push("Simulator reports STALE data (X-Simulator-Stale) — values may lag");
    if (status.data?.overall === "down") msgs.push("System status: DOWN");
  }
  if (!msgs.length) return null;
  return (
    <div className="flex items-start gap-2 border-b border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-800 dark:text-red-300">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <div className="space-y-0.5">
        {msgs.map((m) => (
          <div key={m}>{m}</div>
        ))}
      </div>
    </div>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const { state, status, stream } = useLive();
  const inst = state.data?.instance;
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/85 px-3 backdrop-blur md:px-5">
      <button className="rounded-md p-1.5 hover:bg-muted md:hidden" onClick={onMenu} aria-label="Open menu">
        <Menu className="size-5" />
      </button>
      <SimulatedBadge />
      <div className="flex min-w-0 items-center gap-2 text-sm">
        <span className="text-muted-foreground">Tick</span>
        <b className="tabular-nums">{inst?.tick ?? "—"}</b>
        <span className="hidden text-muted-foreground sm:inline">·</span>
        <span className="hidden tabular-nums text-muted-foreground sm:inline">{inst?.sim_time?.replace("T", " ").slice(0, 16) ?? ""}</span>
        {inst && <StatusPill value={inst.status} />}
      </div>
      <div className="ml-auto flex items-center gap-2">
        {anyMocked() && <span className="rounded-md bg-fuchsia-500/15 px-1.5 py-0.5 text-[10px] font-bold text-fuchsia-700 dark:text-fuchsia-300">MOCK DATA</span>}
        <span className="hidden items-center gap-1.5 text-xs text-muted-foreground lg:flex" title="Live SSE stream from backend; the UI also polls every 3 s">
          <span className={cn("size-2 rounded-full", stream === "connected" ? "bg-emerald-500" : stream === "off" ? "bg-zinc-400" : "animate-pulse bg-amber-500")} />
          stream {stream}
        </span>
        {status.data && (
          <Link href="/system" className="hidden sm:block">
            <StatusPill value={status.data.overall} />
          </Link>
        )}
        {status.error && !status.data && <StatusPill value="down" />}
        <OperatorKeyButton />
      </div>
    </header>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r bg-sidebar md:flex">
        <Brand />
        <Nav />
        <Footer />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col bg-sidebar shadow-xl">
            <div className="flex items-center justify-between pr-2">
              <Brand />
              <button onClick={() => setOpen(false)} className="rounded-md p-1.5 hover:bg-muted" aria-label="Close menu">
                <X className="size-5" />
              </button>
            </div>
            <Nav onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenu={() => setOpen(true)} />
        <DegradedBanner />
        <main className="mx-auto w-full max-w-[1400px] flex-1 space-y-5 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2 px-4 py-4">
      <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <Fuel className="size-4" />
      </div>
      <div className="leading-tight">
        <div className="text-sm font-semibold">GTA 7 Fuel Ops</div>
        <div className="text-[11px] text-muted-foreground">Intelligence & Resilience</div>
      </div>
    </div>
  );
}

function Footer() {
  return (
    <div className="mt-auto space-y-1 border-t p-3 text-[11px] text-muted-foreground">
      <div className="flex items-center gap-1.5">
        <ClipboardList className="size-3" /> Decision support — humans approve consequential actions
      </div>
      <div>Simulation only · BUP Fuel Supply Simulator</div>
    </div>
  );
}
