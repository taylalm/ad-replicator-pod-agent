"use client";

import { useRef } from "react";
import { ExternalLink } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { CostBreakdown, CostPart } from "@/lib/api";
import { fmtDuration, fmtTokens } from "@/lib/format";
import { t } from "@/i18n";

const PARTS: CostPart[] = ["agent_model", "runtime", "tools", "seedance", "seedream", "checks"];
const PRICING_URL = "https://docs.byteplus.com/en/docs/modelark/model-pricing";

export const usd = (v: number) => `$${v.toFixed(2)}`;

/** The breakdown by step behind the Tokens and Cost figures of the job header. */
export function CostDialog({ cost, open, onOpenChange }: { cost: CostBreakdown; open: boolean; onOpenChange: (open: boolean) => void }) {
  const s = t().live.costDialog;
  const priced = cost.total_usd != null;
  const top = useRef<HTMLHeadingElement>(null);  // open at the top (the default focus is the last link, which scrolls down)
  const label = (p: CostPart) => {
    const c = cost.counts;
    switch (p) {
      case "runtime": return s.parts.runtime(usd(cost.runtime_per_h ?? 0));
      case "seedance": return s.parts.seedance(c.seedance_tasks);
      case "seedream": return s.parts.seedream(c.seedream_images);
      case "checks": return s.parts.checks(c.checks);
      default: return s.parts[p];
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] overflow-y-auto rounded-2xl p-6 sm:max-w-2xl" initialFocus={top}>
        <DialogHeader>
          <DialogTitle ref={top} tabIndex={-1} className="font-display text-2xl outline-none">{s.title}</DialogTitle>
          <DialogDescription className="text-sm leading-relaxed">
            {cost.mode === "example" ? s.example : s.full}
          </DialogDescription>
        </DialogHeader>

        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {priced && <Figure label={s.total} value={usd(cost.total_usd!)} strong />}
          <Figure label={s.runtime} value={fmtDuration(cost.runtime_s)} />
          <Figure label={s.tokens} value={fmtTokens(cost.tokens.total)}
            hint={s.tokensDetail(fmtTokens(cost.tokens.input + cost.tokens.cached), fmtTokens(cost.tokens.cached), fmtTokens(cost.tokens.output))} />
          <Figure label={s.toolCalls} value={String(cost.tool_calls)} />
        </dl>

        <div className="overflow-x-auto">
          <table className="w-full text-sm tabular-nums [&_td:not(:first-child)]:whitespace-nowrap [&_th]:whitespace-nowrap">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-2 pr-3 font-medium">{s.step}</th>
                <th className="py-2 pr-3 text-right font-medium">{s.time}</th>
                <th className="hidden py-2 pr-3 text-right font-medium sm:table-cell">{s.tokens}</th>
                {priced && <th className="py-2 text-right font-medium">{s.cost}</th>}
              </tr>
            </thead>
            <tbody>
              {cost.steps.map(r => {
                const parts = PARTS.filter(p => (r.parts?.[p] ?? 0) >= 0.005);
                return (
                  <tr key={r.n} className="border-b border-border/60 align-top last:border-0">
                    <td className="py-2 pr-3">
                      <span className="font-medium">{r.n === 99 ? "" : `${r.n}. `}{r.name}</span>
                      {priced && parts.length > 1 && (
                        <span className="block text-xs text-muted-foreground">
                          {parts.map(p => `${s.short[p]} ${usd(r.parts![p])}`).join(" · ")}
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-right">{r.runtime_s ? fmtDuration(r.runtime_s) : "–"}</td>
                    <td className="hidden py-2 pr-3 text-right sm:table-cell">{r.tokens ? fmtTokens(r.tokens) : "–"}</td>
                    {priced && <td className="py-2 text-right font-medium">{usd(r.usd ?? 0)}</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {priced && cost.parts && (
          <section>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{s.byItem}</h3>
            <table className="w-full text-sm tabular-nums">
              <tbody>
                {PARTS.map(p => (
                  <tr key={p} className="border-b border-border/60 last:border-0">
                    <td className="py-1.5 pr-3">{label(p)}</td>
                    <td className="py-1.5 text-right">{usd(cost.parts![p])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        {priced && (
          <p className="text-xs leading-relaxed text-muted-foreground">
            {s.footnote}{" "}
            <a href={PRICING_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand underline-offset-2 hover:underline">
              {s.pricing}<ExternalLink className="size-3" aria-hidden />
            </a>
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Figure({ label, value, hint, strong }: { label: string; value: string; hint?: string; strong?: boolean }) {
  return (
    <div className="rounded-xl bg-muted/60 px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={strong ? "font-display text-xl font-medium" : "text-base font-medium"}>{value}</dd>
      {hint && <dd className="text-xs text-muted-foreground">{hint}</dd>}
    </div>
  );
}
