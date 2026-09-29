"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { getOperatorKey } from "./api";

export interface PollResult<T> {
  data: T | undefined;
  error: string | null; // last error (data may still hold the last good value → show as stale)
  loading: boolean; // first load only
  fetching: boolean; // any request in flight (first load, poll or manual refresh)
  updatedAt: number | null;
  refresh: () => Promise<void>;
}

/**
 * Fetch on mount and every `intervalMs`. Keeps the last good value when a call fails
 * (cached state / degraded mode on the client side) and exposes the error separately.
 */
export function usePoll<T>(fn: () => Promise<T>, intervalMs = 3000, deps: unknown[] = []): PollResult<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const fnRef = useRef(fn);
  const inFlight = useRef(false);
  useEffect(() => {
    fnRef.current = fn;
  });

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setFetching(true);
    try {
      const v = await fnRef.current();
      setData(v);
      setError(null);
      setUpdatedAt(Date.now());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      inFlight.current = false;
      setFetching(false);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    // keep polling even in a background tab (an ops console often sits behind other windows); refresh at once on focus
    const tick = () => {
      if (!cancelled) void refresh();
    };
    const onVisible = () => document.visibilityState === "visible" && tick();
    void refresh();
    const id = intervalMs > 0 ? setInterval(tick, intervalMs) : undefined;
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      if (id) clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, intervalMs, ...deps]);

  return { data, error, loading, fetching, updatedAt, refresh };
}

export function useOperatorKey(): string {
  const [key, setKey] = useState("");
  useEffect(() => {
    const read = () => setKey(getOperatorKey());
    read();
    window.addEventListener("gta7-operator-key", read);
    return () => window.removeEventListener("gta7-operator-key", read);
  }, []);
  return key;
}
