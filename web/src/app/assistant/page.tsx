"use client";
import { useState } from "react";
import Link from "next/link";
import { Bot, Send } from "lucide-react";
import { BriefingCard } from "@/components/briefing-card";
import { PageHeader, SourceTag } from "@/components/bits";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import type { AssistantAnswer } from "@/lib/types";

const SUGGESTIONS = [
  "Which station is most at risk right now and why?",
  "Why was the latest recommendation made?",
  "What is the impact of the active disruptions?",
  "Is the platform running in degraded or fallback mode?",
];

interface QA {
  q: string;
  a?: AssistantAnswer;
  err?: string;
}

/** Investigation assistant: answers from current state, alerts and recommendations (not a free chatbot). */
export default function AssistantPage() {
  const [q, setQ] = useState("");
  const [log, setLog] = useState<QA[]>([]);
  const [busy, setBusy] = useState(false);

  const ask = async (question: string) => {
    const text = question.trim();
    if (text.length < 2 || busy) return;
    setBusy(true);
    setQ("");
    setLog((l) => [{ q: text }, ...l]);
    try {
      const a = await api.assistant(text.slice(0, 500));
      setLog((l) => l.map((x, i) => (i === 0 ? { ...x, a } : x)));
    } catch (e) {
      setLog((l) => l.map((x, i) => (i === 0 ? { ...x, err: e instanceof Error ? e.message : String(e) } : x)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="AI assistant" subtitle="GenAI supports operations: it explains and investigates using live platform data. Quantities always come from the deterministic planner." />
      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bot className="size-4" /> Investigation assistant
            </CardTitle>
            <CardDescription>Grounded in current state, open alerts and pending recommendations — answers cite evidence.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void ask(q);
              }}
              className="flex gap-2"
            >
              <Textarea
                rows={2}
                maxLength={500}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void ask(q);
                  }
                }}
                placeholder="Ask about risks, alerts, recommendations or system health…"
              />
              <Button type="submit" disabled={busy || q.trim().length < 2} className="h-auto">
                <Send /> {busy ? "…" : "Ask"}
              </Button>
            </form>
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => void ask(s)} disabled={busy} className="rounded-full border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground">
                  {s}
                </button>
              ))}
            </div>
            <div className="space-y-3">
              {log.map((x, i) => (
                <div key={log.length - i} className="space-y-1.5 rounded-xl border p-3">
                  <div className="text-sm font-medium">Q: {x.q}</div>
                  {!x.a && !x.err && <div className="animate-pulse text-sm text-muted-foreground">Investigating…</div>}
                  {x.err && <div className="text-sm text-red-600">{x.err}</div>}
                  {x.a && (
                    <>
                      <p className="whitespace-pre-line text-sm leading-relaxed">{x.a.answer}</p>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <SourceTag source={x.a.source} />
                        {x.a.evidence.map((ev) => (
                          <Evidence key={ev} ev={ev} />
                        ))}
                      </div>
                    </>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <BriefingCard />
      </div>
    </>
  );
}

function Evidence({ ev }: { ev: string }) {
  const [kind] = ev.split(":");
  const href = kind === "alert" ? "/alerts" : kind === "recommendation" ? "/recommendations" : kind === "station" || kind === "depot" ? "/network" : undefined;
  const cls = "rounded-md border bg-muted px-1.5 py-0.5 font-mono text-[11px]";
  return href ? (
    <Link href={href} className={`${cls} hover:border-foreground/40`}>
      {ev}
    </Link>
  ) : (
    <span className={cls}>{ev}</span>
  );
}
