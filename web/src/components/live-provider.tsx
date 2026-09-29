"use client";
// App-wide live data: polls /api/state + /api/system/status every 3 s (contract: poll is the fallback)
// and listens to /api/stream (SSE) to refresh immediately on ticks, alerts and new recommendations.
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api, isMocked, streamUrl } from "@/lib/api";
import { usePoll, type PollResult } from "@/lib/hooks";
import type { Alert, NetworkState, Recommendation, SystemStatus } from "@/lib/types";

type StreamState = "connected" | "reconnecting" | "off";

interface Live {
  state: PollResult<NetworkState>;
  status: PollResult<SystemStatus>;
  stream: StreamState;
  /** increments whenever the stream reports a new alert/recommendation → pages refetch their lists */
  bump: number;
  /** true when the dashboard has no fresh data (backend unreachable or backend reports degraded/stale) */
  degraded: boolean;
}

const Ctx = createContext<Live | null>(null);

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const state = usePoll(api.state, 3000);
  const status = usePoll(api.systemStatus, 3000);
  const [stream, setStream] = useState<StreamState>("off");
  const [bump, setBump] = useState(0);
  const router = useRouter();
  const routerRef = useRef(router);
  // the stream re-sends a recommendation every time it is refreshed → toast each id only once
  const toasted = useRef(new Set<string>());
  const refreshState = useRef(state.refresh);
  const refreshStatus = useRef(status.refresh);
  useEffect(() => {
    refreshState.current = state.refresh;
    refreshStatus.current = status.refresh;
    routerRef.current = router;
  });

  useEffect(() => {
    if (isMocked("state")) return;
    let es: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    let backoff = 1000;

    const connect = () => {
      if (closed) return;
      es = new EventSource(streamUrl());
      es.onopen = () => {
        backoff = 1000;
        setStream("connected");
      };
      es.addEventListener("tick", () => void refreshState.current());
      es.addEventListener("status", () => void refreshStatus.current());
      es.addEventListener("alert", (ev) => {
        setBump((b) => b + 1);
        try {
          const a = JSON.parse((ev as MessageEvent).data) as Alert;
          const key = `alert-${a.id}`;
          if (a.severity === "info" || a.status === "resolved" || toasted.current.has(key)) return;
          toasted.current.add(key);
          const open = () => routerRef.current.push(`/alerts?focus=${a.id}`);
          const opts = { id: key, description: a.detail, action: { label: "View", onClick: open } };
          if (a.severity === "critical") toast.error(a.title, opts);
          else toast.warning(a.title, opts);
        } catch {
          /* ignore malformed event, polling still covers it */
        }
      });
      es.addEventListener("recommendation", (ev) => {
        setBump((b) => b + 1);
        try {
          const r = JSON.parse((ev as MessageEvent).data) as Recommendation;
          const key = `rec-${r.id}`;
          if (r.status !== "pending" || toasted.current.has(key)) return;
          toasted.current.add(key);
          const open = () => routerRef.current.push(`/recommendations?id=${r.id}`);
          toast.info(`New recommendation #${r.id}`, {
            id: key,
            description: `${r.allocation.quantity.toLocaleString("en-US")} L ${r.fuel_type} → ${r.station_id.replace("station-", "")} · click to inspect`,
            action: { label: "Inspect", onClick: open },
          });
        } catch {
          /* ignore */
        }
      });
      es.onerror = () => {
        setStream("reconnecting");
        es?.close();
        retry = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 15000);
      };
    };
    connect();
    return () => {
      closed = true;
      es?.close();
      if (retry) clearTimeout(retry);
    };
  }, []);

  const degraded =
    !!state.error ||
    !!status.error ||
    !!state.data?.data_freshness?.stale ||
    !!state.data?.data_freshness?.degraded ||
    (status.data ? status.data.overall !== "healthy" : false);

  return <Ctx.Provider value={{ state, status, stream, bump, degraded }}>{children}</Ctx.Provider>;
}

export function useLive(): Live {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLive must be used inside LiveProvider");
  return v;
}
