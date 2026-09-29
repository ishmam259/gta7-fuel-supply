"use client";
import { RefreshCw, Sparkles } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { Loading, SourceTag, StaleNote } from "./bits";

/** AI situation briefing (GenAI summarises the state; quantities come from deterministic code). */
export function BriefingCard() {
  const b = usePoll(api.briefing, 30000);
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
                <ul className="list-disc space-y-0.5 pl-5">
                  {b.data.recommended_actions.map((r) => (
                    <li key={r}>{r}</li>
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
