"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ExternalLink, FastForward, Pause, Play } from "lucide-react";
import { DeleteJob, EditableTitle } from "@/components/job-actions";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import type { Job } from "@/lib/api";
import { fmtDate, fmtDuration, fmtTokens, hostOf } from "@/lib/format";
import { t } from "@/i18n";

export function JobHeader({ job, title, subtitle, replay }: {
  job: Job; title: string; subtitle?: string;
  replay?: { enabled: boolean; speed: number; t: number; paused: boolean; onPause: () => void; onJumpEnd: () => void };
}) {
  const s = t();
  const router = useRouter();
  const [name, setName] = useState(job.title);
  return (
    <header className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <Link href="/" className="inline-flex items-center gap-1 rounded-md outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
          <ArrowLeft className="size-3.5" aria-hidden />{s.common.backToHistory}
        </Link>
        <span aria-hidden>·</span>
        {job.demo || replay?.enabled ? <span>{name}</span> : <EditableTitle id={job.id} title={name} onRenamed={setName} />}
        {!job.read_only && !replay?.enabled && <span className="ml-auto"><DeleteJob id={job.id} onDeleted={() => router.push("/")} /></span>}
      </div>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-2xl">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={job.status} demo={job.demo} />
            {replay?.enabled && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-xs font-semibold">
                <FastForward className="size-3.5" aria-hidden />{s.live.replayBadge} · {s.live.replaySpeed(replay.speed)} · {fmtDuration(replay.t)}
              </span>
            )}
          </div>
          <h1 className="mt-3 font-display text-3xl font-medium tracking-tight sm:text-4xl">{title}</h1>
          {subtitle && <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">{subtitle}</p>}
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:auto-cols-max sm:grid-flow-col sm:grid-cols-none lg:text-right">
          <Meta label={s.common.createdAt}>{fmtDate(job.created_at)}</Meta>
          <Meta label={s.live.productionTime}>{job.production ? fmtDuration(job.production.production_s) : "–"}</Meta>
          {job.production?.waiting_s ? <Meta label={s.live.waitingTime}>{fmtDuration(job.production.waiting_s)}</Meta> : null}
          {job.production?.cost_per_video_usd != null && (
            <Meta label={s.live.costPerVideo}>
              <span title={s.live.costTitle(`$${(job.production.cost_total_usd ?? job.production.cost_per_video_usd).toFixed(2)}`)}>${job.production.cost_per_video_usd.toFixed(2)}</span>
            </Meta>
          )}
          <Meta label={s.common.product}>
            {job.inputs.product_url ? (
              <a href={job.inputs.product_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand underline-offset-2 hover:underline">
                {hostOf(job.inputs.product_url)}<ExternalLink className="size-3" aria-hidden />
              </a>
            ) : "–"}
          </Meta>
          <Meta label={s.common.tokens}>{fmtTokens(job.usage.input_tokens + job.usage.output_tokens)} · {job.usage.tool_calls} {s.common.toolCalls}</Meta>
        </dl>
      </div>
      {replay?.enabled && replay.speed > 0 && job.status !== "done" && (
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="rounded-full" onClick={replay.onPause} aria-pressed={replay.paused}>
            {replay.paused ? <Play className="size-3.5" /> : <Pause className="size-3.5" />}{replay.paused ? s.results.play : s.results.pause}
          </Button>
          <Button variant="ghost" size="sm" className="rounded-full" onClick={replay.onJumpEnd}><FastForward className="size-3.5" />{s.live.skipToEnd}</Button>
        </div>
      )}
    </header>
  );
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="truncate font-medium">{children}</dd>
    </div>
  );
}

