import { CheckCircle2, CircleAlert, Clock, Loader2, PauseCircle } from "lucide-react";
import type { JobStatus } from "@/lib/api";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";

const STYLES: Record<JobStatus, string> = {
  queued: "bg-muted text-muted-foreground",
  running: "bg-brand-soft text-foreground",
  awaiting_approval: "bg-warning-soft text-foreground",
  done: "bg-success-soft text-foreground",
  failed: "bg-danger-soft text-foreground",
  stopped: "bg-warning-soft text-foreground",
};

export function StatusBadge({ status, className, demo }: { status: JobStatus; className?: string; demo?: boolean }) {
  const s = t();
  const Icon =
    status === "done" ? CheckCircle2 : status === "failed" ? CircleAlert : status === "awaiting_approval" ? Clock : status === "stopped" ? PauseCircle : Loader2;
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold", STYLES[status] ?? STYLES.queued, className)}>
      <Icon className={cn("size-3.5", status === "running" || status === "queued" ? "animate-spin text-brand" : status === "done" ? "text-success" : status === "failed" ? "text-danger" : "text-warning")} aria-hidden />
      {s.status[status] ?? status}
      {demo && <span className="ml-1 rounded-full bg-foreground/10 px-1.5 py-px text-[10px] uppercase tracking-wide">{s.app.demoBadge}</span>}
    </span>
  );
}
