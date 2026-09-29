"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Bell, Sparkles } from "lucide-react";
import { useLive } from "@/components/live-provider";
import { Empty, Loading, PageHeader, Pill, Seg, SourceTag, StaleNote, StatusPill } from "@/components/bits";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { nameOf, timeAgo } from "@/lib/format";
import type { Alert, IncidentExplanation, Severity } from "@/lib/types";

const SEV_TONE: Record<Severity, "bad" | "warn" | "neutral"> = { critical: "bad", warning: "warn", info: "neutral" };
const SEV_BORDER: Record<Severity, string> = { critical: "border-l-red-500", warning: "border-l-amber-500", info: "border-l-sky-500" };

export default function AlertsPage() {
  return (
    <Suspense>
      <AlertsInner />
    </Suspense>
  );
}

function AlertsInner() {
  const { state, bump } = useLive();
  const focus = Number(useSearchParams().get("focus")) || null;
  const [status, setStatus] = useState<"open" | "all">(focus ? "all" : "open");
  const [sev, setSev] = useState<"" | Severity>("");
  const [kind, setKind] = useState("");
  const alerts = usePoll(() => api.alerts(status, 200), 5000, [status, bump]);

  const kinds = Array.from(new Set((alerts.data ?? []).map((a) => a.kind))).sort();
  const rows = (alerts.data ?? []).filter((a) => (!sev || a.severity === sev) && (!kind || a.kind === kind));
  const counts = (alerts.data ?? []).reduce<Record<string, number>>((m, a) => ((m[a.severity] = (m[a.severity] ?? 0) + 1), m), {});

  return (
    <>
      <PageHeader title="Alerts" subtitle="Shortage risk, anomalies, bottlenecks, disruptions and integration failures detected by the platform">
        <Seg value={status} onChange={(v) => setStatus(v as "open" | "all")} options={[["open", "Open"], ["all", "All"]]} />
        <Seg
          value={sev}
          onChange={(v) => setSev(v as "" | Severity)}
          options={[["", "Any severity"], ["critical", `Critical ${counts.critical ?? 0}`], ["warning", `Warning ${counts.warning ?? 0}`], ["info", `Info ${counts.info ?? 0}`]]}
        />
        <select className="h-8 rounded-lg border bg-background px-2 text-sm" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Filter by kind">
          <option value="">All kinds</option>
          {kinds.map((k) => (
            <option key={k} value={k}>
              {k.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </PageHeader>
      <StaleNote error={alerts.error} updatedAt={alerts.updatedAt} />
      {!alerts.data && !alerts.error && <Loading />}
      {alerts.data && rows.length === 0 && (
        <Empty>
          <Bell className="mx-auto mb-2 size-5" />
          No {status === "open" ? "open " : ""}alerts{sev || kind ? " matching the filter" : ""}. The network looks calm.
        </Empty>
      )}
      <div className="space-y-2">
        {rows.map((a) => (
          <AlertRow key={a.id} a={a} entityName={nameOf(state.data, a.entity?.id)} focused={a.id === focus} />
        ))}
      </div>
    </>
  );
}

function AlertRow({ a, entityName, focused }: { a: Alert; entityName: string; focused: boolean }) {
  useEffect(() => {
    if (focused) document.getElementById(`alert-${a.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focused, a.id]);
  const [exp, setExp] = useState<IncidentExplanation | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const explain = async () => {
    setBusy(true);
    setErr(null);
    try {
      setExp(await api.incident(a.id));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card id={`alert-${a.id}`} className={`border-l-4 ${SEV_BORDER[a.severity] ?? ""} ${a.status === "resolved" && !focused ? "opacity-70" : ""} ${focused ? "ring-2 ring-primary" : ""}`}>
      <CardContent className="space-y-2 py-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <Pill tone={SEV_TONE[a.severity] ?? "neutral"}>{a.severity}</Pill>
              <Pill>{a.kind.replace(/_/g, " ")}</Pill>
              <span className="font-medium">{a.title}</span>
            </div>
            <div className="mt-1 text-sm text-muted-foreground">{a.detail}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              #{a.id} · tick {a.tick} · {a.entity?.type} {entityName}
              {a.entity?.fuel_type ? ` · ${a.entity.fuel_type}` : ""} · {timeAgo(a.created_at)}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <StatusPill value={a.status} />
            <Button size="sm" variant="outline" onClick={explain} disabled={busy}>
              <Sparkles /> {busy ? "Explaining…" : "Explain"}
            </Button>
          </div>
        </div>
        {err && <div className="text-xs text-red-600">{err}</div>}
        {exp && (
          <div className="rounded-lg bg-muted/60 p-3 text-sm">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Incident explanation</span>
              <SourceTag source={exp.source} />
            </div>
            <p className="whitespace-pre-line leading-relaxed">{exp.explanation}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
