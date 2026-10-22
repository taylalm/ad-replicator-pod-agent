"use client";

import { AlertTriangle, CheckCircle2, ShieldAlert, XCircle } from "lucide-react";
import { useState } from "react";
import { fileUrl, type QualityRound } from "@/lib/api";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";

const ORDER = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"];

function tone(score: number | null) {
  if (score == null) return "muted";
  if (score >= 4) return "good";
  if (score === 3) return "warn";
  return "bad";
}

export function Scorecard({ rounds, needsReview }: { rounds: QualityRound[]; needsReview?: boolean }) {
  const s = t();
  const [active, setActive] = useState(rounds.length - 1);
  const r = rounds[Math.min(active, rounds.length - 1)];
  if (!r) return null;
  const pass = r.verdict === "PASS";
  return (
    <div className="space-y-5">
      <div className={cn("flex flex-wrap items-center gap-3 rounded-2xl p-4 ring-1", pass ? "bg-success-soft ring-success/30" : "bg-danger-soft ring-danger/30")}>
        {pass ? <CheckCircle2 className="size-6 text-success" aria-hidden /> : <XCircle className="size-6 text-danger" aria-hidden />}
        <div className="min-w-0 flex-1">
          <p className="font-display text-lg font-medium">{needsReview ? s.results.verdictReview : pass ? s.results.verdictPass : s.results.verdictFail}</p>
          {r.min_score != null && <p className="text-sm text-muted-foreground">{s.results.minScore(r.min_score)}{r.model ? ` · ${r.model}` : ""}</p>}
        </div>
        {rounds.length > 1 && (
          <div className="flex gap-1" role="tablist" aria-label={s.results.rounds}>
            {rounds.map((x, i) => (
              <button
                key={x.round}
                role="tab"
                aria-selected={i === active}
                onClick={() => setActive(i)}
                className={cn("rounded-full px-3 py-1 text-xs font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50", i === active ? "bg-foreground text-background" : "bg-card text-muted-foreground hover:text-foreground")}
              >
                {s.results.round(x.round)} · {x.verdict}
              </button>
            ))}
          </div>
        )}
      </div>
      {r.summary && <p className="text-[15px] leading-relaxed">{r.summary}</p>}
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label={s.results.scorecard}>
        {ORDER.map((k) => {
          const sc = r.scores[k];
          const tn = tone(sc?.score ?? null);
          return (
            <li key={k} className="flex flex-col gap-2 rounded-2xl bg-card p-4 ring-1 ring-foreground/8">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{k} · {s.results.criteria[k]}</span>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-sm font-bold tabular-nums",
                    tn === "good" && "bg-success-soft text-success",
                    tn === "warn" && "bg-warning-soft text-warning",
                    tn === "bad" && "bg-danger-soft text-danger",
                    tn === "muted" && "bg-muted text-muted-foreground",
                  )}
                  aria-label={`${s.results.criteria[k]}: ${sc?.score ?? "?"} of 5`}
                >
                  {sc?.score ?? "–"}/5
                </span>
              </div>
              <p className="text-sm leading-snug">{sc?.reason ?? s.results.criteriaLong[k]}</p>
              {sc?.evidence && <p className="mt-auto text-xs text-muted-foreground">{s.results.evidence} {sc.evidence}</p>}
            </li>
          );
        })}
      </ul>
      <div className="rounded-2xl bg-card p-4 ring-1 ring-foreground/8">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <ShieldAlert className={cn("size-4", r.hard_failures.length ? "text-danger" : "text-success")} aria-hidden />
          {s.results.hardFailures}
          <span className="font-normal text-muted-foreground">· {r.hard_failures.length ? r.hard_failures.length : s.results.noHardFailures}</span>
        </h3>
        {r.hard_failures.length > 0 && (
          <ul className="mt-2 space-y-2">
            {r.hard_failures.map((h, i) => (
              <li key={i} className="flex gap-2 text-sm">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
                <span><strong className="font-semibold">{h.kind.replace(/_/g, " ")}</strong>: {h.detail}{h.evidence ? <span className="text-muted-foreground"> ({h.evidence})</span> : null}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {r.sheets.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-muted-foreground">{s.results.evaluatorFrames}</h3>
          <div className="grid max-w-3xl grid-cols-2 items-start gap-3">
            {r.sheets.map((u, i) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img key={u} src={fileUrl(u)} alt={`${s.results.evaluatorFrames} ${i + 1}`} className="w-full rounded-xl ring-1 ring-foreground/8" loading="lazy" />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
