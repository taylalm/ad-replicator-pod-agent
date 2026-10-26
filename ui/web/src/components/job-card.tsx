"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, Clapperboard, PlayCircle } from "lucide-react";
import { StatusBadge } from "@/components/status-badge";
import { DeleteJob, EditableTitle } from "@/components/job-actions";
import { fileUrl, type JobRow } from "@/lib/api";
import { fmtDate, fmtDuration, hostOf } from "@/lib/format";
import { t } from "@/i18n";

export function JobCard({ job, index = 0, onDeleted, onRenamed }: {
  job: JobRow; index?: number; onDeleted?: (id: string) => void; onRenamed?: (id: string, title: string) => void;
}) {
  const s = t();
  const replayable = job.demo || job.status === "done";
  return (
    <motion.li
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: Math.min(index, 6) * 0.05 }}
      className="group relative flex gap-4 rounded-2xl bg-card p-3 shadow-soft ring-1 ring-foreground/8 transition-shadow hover:shadow-lift sm:p-4"
    >
      <Link href={`/job?id=${job.id}`} className="relative block w-20 shrink-0 overflow-hidden rounded-xl bg-surface ring-1 ring-foreground/8 outline-none focus-visible:ring-3 focus-visible:ring-ring/50 sm:w-24 aspect-9-16" aria-label={`${s.history.open}: ${job.title}`}>
        {job.thumbnail ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={fileUrl(job.thumbnail)} alt="" className="size-full object-cover transition-transform duration-500 group-hover:scale-[1.03]" loading="lazy" />
        ) : (
          <span className="grid size-full place-items-center text-muted-foreground"><Clapperboard className="size-6" aria-hidden /></span>
        )}
      </Link>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={job.status} demo={job.demo} />
          {job.verdict && <span className="text-xs font-semibold text-muted-foreground">Quality: {job.verdict}</span>}
        </div>
        <h3 className="mt-2 flex flex-wrap items-center gap-1.5 font-display text-lg font-medium leading-tight">
          <Link href={`/job?id=${job.id}`} className="outline-none after:absolute after:inset-0 after:rounded-2xl focus-visible:underline">{job.title}</Link>
          {onRenamed && !job.demo && <EditableRename job={job} onRenamed={onRenamed} />}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          {fmtDate(job.created_at)}{job.product_url ? ` · ${hostOf(job.product_url)}` : ""}{job.production_s ? ` · ${s.history.production(fmtDuration(job.production_s))}` : ""}{job.cost_per_video_usd != null ? ` · ${s.history.costPerVideo(`$${job.cost_per_video_usd.toFixed(2)}`)}` : ""}
        </p>
        {job.current_step != null && job.status !== "done" && <p className="mt-1 text-sm text-muted-foreground">{s.live.stepOf(job.current_step)}{s.steps.names[job.current_step] ? ` · ${s.steps.names[job.current_step]}` : ""}</p>}
        {job.error && <p className="mt-1 text-xs text-danger">{job.error}</p>}
        <div className="relative z-10 mt-auto flex flex-wrap gap-2 pt-3">
          {replayable && (
            <Link href={`/job?id=${job.id}&replay=1&speed=24`} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-muted px-3 text-xs font-semibold text-foreground outline-none hover:bg-brand-soft focus-visible:ring-3 focus-visible:ring-ring/50">
              <PlayCircle className="size-3.5" aria-hidden />{s.history.replay}
            </Link>
          )}
          <Link href={`/job?id=${job.id}`} className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs font-semibold text-brand outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
            {s.history.open}<ArrowRight className="size-3.5" aria-hidden />
          </Link>
          {onDeleted && !job.read_only && !job.demo && <span className="ml-auto"><DeleteJob id={job.id} compact onDeleted={() => onDeleted(job.id)} /></span>}
        </div>
      </div>
    </motion.li>
  );
}

/** Pencil-only rename on a card: the editor replaces the link title while open. */
function EditableRename({ job, onRenamed }: { job: JobRow; onRenamed: (id: string, title: string) => void }) {
  return <span className="relative z-10 [&>span>span:first-child]:sr-only"><EditableTitle id={job.id} title={job.title} onRenamed={t => onRenamed(job.id, t)} /></span>;
}
