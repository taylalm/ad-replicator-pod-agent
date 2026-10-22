"use client";

import { Clapperboard, ImageIcon, ShieldCheck } from "lucide-react";
import type { PaidCalls } from "@/lib/api";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";

export function PaidCallsPanel({ paid, compact = false }: { paid: PaidCalls; compact?: boolean }) {
  const s = t();
  const rows = [
    { key: "seedream", label: s.newJob.budget.seedream, icon: ImageIcon, used: paid.seedream, max: paid.budget.seedream },
    { key: "seedance", label: s.newJob.budget.seedance, icon: Clapperboard, used: paid.seedance, max: paid.budget.seedance },
    { key: "evaluator", label: s.newJob.budget.evaluator, icon: ShieldCheck, used: paid.evaluator, max: paid.budget.evaluator },
  ];
  const totalMax = paid.budget.seedream + paid.budget.seedance + paid.budget.evaluator; // 0 = no cap
  return (
    <div className={cn("rounded-2xl bg-card ring-1 ring-foreground/8", compact ? "p-4" : "p-5")}>
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">{s.live.paidCalls}</h3>
        <span className="text-sm tabular-nums text-muted-foreground">{totalMax > 0 ? s.live.ofBudget(paid.total, totalMax) : `${paid.total} · ${s.newJob.budget.noCap.toLowerCase()}`}</span>
      </div>
      <ul className="mt-3 space-y-3">
        {rows.map((r) => {
          const pct = r.max ? Math.min(100, (r.used / r.max) * 100) : 0;
          const over = r.max > 0 && r.used > r.max;
          return (
            <li key={r.key}>
              <div className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-1.5"><r.icon className="size-3.5 text-muted-foreground" aria-hidden />{r.label}</span>
                <span className={cn("tabular-nums", over ? "text-danger" : "text-muted-foreground")}>{r.max > 0 ? `${r.used} / ${r.max}` : `${r.used} · ${s.newJob.budget.noCap.toLowerCase()}`}</span>
              </div>
              <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={r.used} aria-valuemin={0} aria-valuemax={r.max} aria-label={r.label}>
                <div className={cn("h-full rounded-full transition-[width] duration-500", over ? "bg-danger" : "bg-brand")} style={{ width: `${pct}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
