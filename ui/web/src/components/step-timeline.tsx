"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Check, Circle, Loader2, X } from "lucide-react";
import type { Step } from "@/lib/api";
import { fmtDuration, plainText } from "@/lib/format";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";

export function StepTimeline({ steps, currentStep, compact = false }: { steps: Step[]; currentStep: number | null; compact?: boolean }) {
  const s = t();
  return (
    <ol className="relative" aria-label="Progress">
      {steps.map((st, i) => {
        const isLast = i === steps.length - 1;
        const active = st.status === "running";
        const done = st.status === "done";
        const failed = st.status === "failed";
        const pending = st.status === "pending";
        return (
          <li key={st.n} className={cn("relative flex gap-3", compact ? "pb-3" : "pb-5", isLast && "pb-0")}>
            {!isLast && (
              <span
                aria-hidden
                className={cn("absolute left-[13px] top-7 h-[calc(100%-12px)] w-px", done ? "bg-success/50" : "bg-border")}
              />
            )}
            <span
              className={cn(
                "relative z-10 grid size-7 shrink-0 place-items-center rounded-full border text-xs font-semibold transition-colors",
                done && "border-success bg-success text-white",
                active && "border-brand bg-brand-soft text-brand",
                failed && "border-danger bg-danger text-white",
                pending && "border-border bg-card text-muted-foreground",
              )}
              aria-hidden
            >
              <AnimatePresence mode="popLayout" initial={false}>
                {done ? (
                  <motion.span key="done" initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: "spring", stiffness: 420, damping: 22 }}>
                    <Check className="size-3.5" strokeWidth={3} />
                  </motion.span>
                ) : active ? (
                  <motion.span key="run" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                    <Loader2 className="size-3.5 animate-spin" />
                  </motion.span>
                ) : failed ? (
                  <motion.span key="fail" initial={{ scale: 0.4 }} animate={{ scale: 1 }}>
                    <X className="size-3.5" strokeWidth={3} />
                  </motion.span>
                ) : (
                  <motion.span key="pend" className="text-[11px]">{st.n}</motion.span>
                )}
              </AnimatePresence>
            </span>
            <div className={cn("min-w-0 flex-1", compact ? "pt-0.5" : "pt-1")}>
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className={cn("text-sm font-semibold", pending && "text-muted-foreground", active && "text-foreground")}>
                  {s.steps.names[st.n] ?? st.name}
                </span>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {done && st.elapsed_s != null && s.steps.elapsed(fmtDuration(st.elapsed_s))}
                  {active && st.elapsed_s != null && s.steps.runningFor(fmtDuration(st.elapsed_s))}
                  {failed && s.steps.failed}
                  {st.rounds > 1 && ` · ${st.rounds}x`}
                </span>
              </div>
              {!compact && (st.latest_message || st.reason) && (
                <motion.p
                  key={st.latest_message ?? st.reason ?? ""}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={cn("mt-1 text-sm leading-relaxed text-muted-foreground", failed && "text-foreground")}
                  style={{ display: "-webkit-box", WebkitLineClamp: active || st.n === currentStep ? 8 : 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}
                >
                  {failed && st.reason ? st.reason : plainText(st.latest_message?.replace(/^STEP[^\n]*\n?/, "") ?? "")}
                </motion.p>
              )}
            </div>
            {compact && <Circle className="sr-only" />}
          </li>
        );
      })}
    </ol>
  );
}
