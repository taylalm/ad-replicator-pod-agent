"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { Suspense, useMemo } from "react";
import { JobHeader } from "@/components/views/job-header";
import { LiveProgress } from "@/components/views/live-progress";
import { StepReview } from "@/components/views/step-review";
import { PlanApproval } from "@/components/views/plan-approval";
import { Results } from "@/components/views/results";
import { Skeleton } from "@/components/ui/skeleton";
import { useJob } from "@/hooks/use-job";
import { fmtDuration } from "@/lib/format";
import { t } from "@/i18n";

export default function JobPage() {
  return (
    <Suspense fallback={<JobSkeleton />}>
      <JobScreen />
    </Suspense>
  );
}

function JobScreen() {
  const s = t();
  const search = useSearchParams();
  const id = search.get("id") ?? "";
  const replay = useMemo(() => ({
    enabled: search.get("replay") === "1",
    speed: search.has("speed") ? Number(search.get("speed")) : 24,
    startT: search.has("t") ? Number(search.get("t")) : 0,
  }), [search]);
  const { job, events, error, send, replayT, jumpTo, replayPaused, setReplayPaused } = useJob(id, replay);

  if (error === "backend" && !job) return <p role="alert" className="rounded-2xl bg-danger-soft p-4 text-sm">{s.app.backendDown}</p>;
  if (error && !job) {
    return (
      <div className="rounded-3xl bg-card p-10 text-center ring-1 ring-foreground/8">
        <p className="font-display text-2xl">{s.common.notFound}</p>
        <Link href="/" className="mt-4 inline-block text-sm font-semibold text-brand hover:underline">{s.common.backToHistory}</Link>
      </div>
    );
  }
  if (!job) return <JobSkeleton />;

  const view = job.awaiting_approval ? (job.awaiting_step && job.awaiting_step !== 3 ? "step" : "plan") : job.status === "done" ? "results" : "live";
  const stepWait = job.awaiting_approval && job.awaiting_step && job.awaiting_step !== 3 ? job.steps.find((st) => st.n === job.awaiting_step) : null;
  const title = view === "step" && stepWait ? s.plan.stepTitle(stepWait.n, stepWait.name) : view === "plan" ? s.plan.title : view === "results" ? (job.quality.at(-1)?.verdict === "PASS" || !job.quality.length ? s.results.ready : s.results.readyWithReview) : s.live.title;
  const finalLen = job.inputs.options?.length_s ? `${job.inputs.options.length_s} s` : "";
  const subtitle = view === "step" ? s.plan.stepSubtitle : view === "plan" ? undefined : view === "results" ? s.results.subtitle(finalLen) : s.live.subtitle;

  return (
    <div className="space-y-8">
      <JobHeader
        job={job}
        title={title}
        subtitle={subtitle}
        replay={replay.enabled ? { enabled: true, speed: replay.speed, t: replayT, paused: replayPaused, onPause: () => setReplayPaused((p) => !p), onJumpEnd: () => jumpTo((job.replay?.total_s ?? 0) + 2) } : undefined}
      />
      <AnimatePresence mode="wait" initial={false}>
        <motion.div key={view} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.25 }}>
          {view === "plan" && <PlanApproval job={job} onSend={send} replay={replay.enabled} />}
          {view === "step" && <StepReview job={job} onSend={send} replay={replay.enabled} />}
          {view === "live" && <LiveProgress job={job} events={events} onSend={send} />}
          {view === "results" && <Results job={job} events={events} onSend={send} />}
        </motion.div>
      </AnimatePresence>
      <p className="text-xs text-muted-foreground">{s.common.sessionId}: <span className="font-mono">{job.session_id}</span>{job.elapsed_s ? ` · ${fmtDuration(job.elapsed_s)}` : ""}</p>
    </div>
  );
}

function JobSkeleton() {
  return (
    <div className="space-y-8" aria-busy="true">
      <div className="space-y-3"><Skeleton className="h-4 w-40" /><Skeleton className="h-6 w-32 rounded-full" /><Skeleton className="h-10 w-80" /></div>
      <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
        <Skeleton className="h-96 rounded-3xl" />
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-5">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="aspect-9-16 rounded-xl" />)}</div>
      </div>
    </div>
  );
}
