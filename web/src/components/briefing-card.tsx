"use client";
import Link from "next/link";
import { ArrowRight, RefreshCw, Sparkles } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import type { Recommendation } from "@/lib/types";
import { Loading, SourceTag, StaleNote } from "./bits";
import { useLive } from "./live-provider";

/** Link a briefing action to its recommendation: "#21" in the text, else a pending rec for the station + fuel it names. */
function actionHref(text: string, pending: Recommendation[], stationName: (id: string) => string): string {
  const m = text.match(/#\s?(\d+)/);
  if (m) return `/recommendations?id=${m[1]}`;
  const t = text.toLowerCase();
  const hit =
    pending.find((r) => t.includes(stationName(r.station_id).toLowerCase().split(" ")[0]) && t.includes(r.fuel_type.toLowerCase())) ??
    pending.find((r) => t.includes(stationName(r.station_id).toLowerCase().split(" ")[0]));
  return hit ? `/recommendations?id=${hit.id}` : "/recommendations";
}

/** AI situation briefing (GenAI summarises the state; quantities come from deterministic code). */
export function BriefingCard() {
  const b = usePoll(api.briefing, 30000);
  const { state, bump } = useLive();
  const pending = usePoll(() => api.recommendations("pending"), 10000, [bump]);
  const stationName = (id: string) => state.data?.stations.find((s) => s.id === id)?.name ?? id.replace("station-", "");
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-4" /> Situation briefing
        </CardTitle>
        <div className="flex items-center gap-1.5">
          <SourceTag source={b.data?.source} />
          <Button size="icon-sm" variant="ghost" onClick={() => void b.refresh()} aria-label="Refresh briefing">
            <RefreshCw className={b.loading ? "animate-spin" : ""} />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <StaleNote error={b.error} updatedAt={b.updatedAt} />
        {!b.data && !b.error && <Loading />}
        {b.data && (
          <>
            <p className="leading-relaxed">{b.data.summary}</p>
            {b.data.top_risks.length > 0 && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Top risks</div>
                <ul className="list-disc space-y-0.5 pl-5">
                  {b.data.top_risks.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
            )}
            {b.data.recommended_actions.length > 0 && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Recommended actions</div>
                <ul className="space-y-1">
                  {b.data.recommended_actions.map((r) => (
                    <li key={r}>
                      <Link
                        href={actionHref(r, pending.data ?? [], stationName)}
                        className="group flex items-start gap-1.5 rounded-md px-1.5 py-1 hover:bg-muted"
                      >
                        <ArrowRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground group-hover:text-foreground" />
                        <span className="underline-offset-2 group-hover:underline">{r}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="text-[11px] text-muted-foreground">Briefing at tick {b.data.tick} · AI explains, it does not decide quantities.</div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
