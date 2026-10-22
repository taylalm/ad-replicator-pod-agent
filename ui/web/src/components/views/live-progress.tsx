"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Loader2, Send } from "lucide-react";
import { useMemo, useState } from "react";
import { ClipWorkbench } from "@/components/clip-workbench";
import { ErrorList } from "@/components/error-list";
import { FileThumb } from "@/components/file-thumb";
import { PaidCallsPanel } from "@/components/paid-calls";
import { RawLog } from "@/components/raw-log";
import { Scorecard } from "@/components/scorecard";
import { StepTimeline } from "@/components/step-timeline";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { fileUrl, type Job, type JobFile, type RawEvent } from "@/lib/api";
import { latestVersions } from "@/lib/format";
import { t } from "@/i18n";

type Group = { key: keyof ReturnType<typeof t>["live"]["groups"]; files: JobFile[]; aspect: "auto" | "portrait" | "square" };

function groupFiles(allFiles: JobFile[], withClips: boolean): Group[] {
  const files = latestVersions(allFiles);
  const pick = (re: RegExp, kinds: JobFile["kind"][] = ["image", "video"]) => files.filter((f) => re.test(f.name) && kinds.includes(f.kind));
  const groups: Group[] = [
    { key: "analysis", files: pick(/^(contact_sheet_|scene_\d+_start|watermark_check)/), aspect: "auto" },
    { key: "people", files: pick(/^(person_|product_|artwork_)/), aspect: "square" },
    { key: "clips", files: withClips ? [] : pick(/^clip_\d+[\w-]*\.(mp4|mov|webm)$/), aspect: "portrait" },
    { key: "final", files: pick(/^final_v\d+/), aspect: "portrait" },
    { key: "quality", files: pick(/^quality_round_/), aspect: "auto" },
  ];
  const used = new Set(groups.flatMap((g) => g.files.map((f) => f.name)));
  const secondary = /^(sample|source)\.(mp4|mov)$|^form_filled|^form_final|^error_step|^after_step|^scene_\d+_[\d.]+s\.|^check_|^probe|^cgt-|__[a-z0-9]{5}\.|^frame_clip_|^clip_\d+[\w-]*_\d+(\.\d+)?s?\.(jpe?g|png)$|_(sheet|band|zoom|zooms|frames|timeline)(_[\w-]+)?\.(jpe?g|png)$|^wm_\d+\.|^staging_scene_|^v\d+_|^in\d+\.|^step\d+\./i;
  groups.push({ key: "other", files: files.filter((f) => !used.has(f.name) && f.kind === "image" && !secondary.test(f.name)), aspect: "square" });
  return groups.filter((g) => g.files.length);
}

export function LiveProgress({ job, events, onSend }: { job: Job; events: RawEvent[]; onSend: (text: string) => Promise<unknown> }) {
  const s = t();
  const groups = useMemo(() => groupFiles(job.files, job.clips.length > 0), [job.files, job.clips.length]);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const stopped = job.status === "stopped" || job.status === "failed";

  const send = async () => {
    if (!reply.trim()) return;
    setBusy(true);
    try { await onSend(reply.trim()); setReply(""); } finally { setBusy(false); }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
      <aside className="space-y-4">
        <div className="rounded-3xl bg-card p-5 shadow-soft ring-1 ring-foreground/8">
          {job.current_step && <p className="mb-4 text-xs font-semibold uppercase tracking-wide text-brand">{s.live.stepOf(job.current_step)}</p>}
          <StepTimeline steps={job.steps} currentStep={job.current_step} />
        </div>
        <PaidCallsPanel paid={job.paid_calls} compact />
      </aside>

      <div className="space-y-6">
        <ErrorList errors={job.errors} />

        {stopped && (
          <section className="rounded-3xl bg-card p-5 ring-1 ring-foreground/8">
            <h2 className="font-display text-xl font-medium">{s.live.stoppedTitle}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{s.live.stoppedBody}</p>
            {job.last_agent_message && (
              <blockquote className="mt-3 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-xl bg-muted p-3 text-sm leading-relaxed">{job.last_agent_message}</blockquote>
            )}
            {!job.demo && (
              <div className="mt-3 flex gap-2">
                <Textarea value={reply} onChange={(e) => setReply(e.target.value)} placeholder={s.live.replyPlaceholder} rows={2} className="rounded-xl" aria-label={s.live.replyPlaceholder} />
                <Button className="self-end rounded-full bg-brand text-brand-foreground hover:bg-brand/90" onClick={send} disabled={busy || !reply.trim()}>
                  {busy ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}{s.live.send}
                </Button>
              </div>
            )}
          </section>
        )}

        <section aria-labelledby="outputs">
          <h2 id="outputs" className="mb-3 font-display text-xl font-medium">{s.live.outputs}</h2>
          {groups.length === 0 ? (
            <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-5">
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className="aspect-9-16 animate-pulse rounded-xl bg-muted" aria-hidden />
              ))}
              <p className="col-span-full text-sm text-muted-foreground">{s.live.noOutputs}</p>
            </div>
          ) : (
            <div className="space-y-6">
              <AnimatePresence initial={false}>
                {groups.map((g) => (
                  <motion.div key={g.key} layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="rounded-3xl bg-card p-4 ring-1 ring-foreground/8 sm:p-5">
                    <h3 className="mb-3 text-sm font-semibold text-muted-foreground">{s.live.groups[g.key]} <span className="font-normal">· {g.files.length}</span></h3>
                    <div className={g.aspect === "portrait" ? "grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6" : "grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-5"}>
                      {g.files.map((f, i) => (
                        <FileThumb key={f.name} file={f} index={i} aspect={g.aspect} onClick={() => window.open(fileUrl(f.local_url), "_blank", "noopener")} />
                      ))}
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </section>

        <ClipWorkbench job={job} onSend={onSend} />

        {job.quality.length > 0 && (
          <section aria-labelledby="live-scorecard" className="rounded-3xl bg-card p-5 ring-1 ring-foreground/8">
            <h2 id="live-scorecard" className="font-display text-xl font-medium">{s.results.scorecard}</h2>
            <p className="mt-1 mb-4 text-sm text-muted-foreground">{s.results.scorecardHint}</p>
            <Scorecard rounds={job.quality} />
          </section>
        )}

        <RawLog events={events} />
      </div>
    </div>
  );
}
