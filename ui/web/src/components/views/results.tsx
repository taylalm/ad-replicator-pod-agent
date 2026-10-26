"use client";

import { motion } from "framer-motion";
import { ChevronDown, FileText, Loader2, Send, Wand2 } from "lucide-react";
import { useState } from "react";
import { ClipWorkbench } from "@/components/clip-workbench";
import { DownloadAll } from "@/components/download-parts";
import { DownloadButton } from "@/components/download-button";
import { CaptionEditor } from "@/components/caption-editor";
import { PaidCallsPanel } from "@/components/paid-calls";
import { RawLog } from "@/components/raw-log";
import { Scorecard } from "@/components/scorecard";
import { StepTimeline } from "@/components/step-timeline";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Textarea } from "@/components/ui/textarea";
import { VideoCompare } from "@/components/video-compare";
import { fileUrl, type Job, type RawEvent } from "@/lib/api";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";

export function Results({ job, events, onSend }: { job: Job; events: RawEvent[]; onSend: (text: string) => Promise<unknown> }) {
  const s = t();
  const [revision, setRevision] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const final = job.finals[job.finals.length - 1];
  const names = new Set(job.files.map((f) => f.name));
  const cleanName = names.has("final_clean.mp4") ? "final_clean.mp4" : final && names.has(final.file.replace(/\.mp4$/, "_clean.mp4")) ? final.file.replace(/\.mp4$/, "_clean.mp4") : null;
  const sendRevision = async () => {
    if (!revision.trim()) return;
    setBusy(true);
    try { await onSend(`REVISION: ${revision.trim()}`); setSent(true); setRevision(""); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <VideoCompare sampleSrc={fileUrl(job.sample_url)} finalSrc={fileUrl(job.final_url)} downloadName={final?.file} />
        <div className="flex flex-wrap items-center gap-2">
          <DownloadButton url={job.final_url} name={final?.file ?? "final.mp4"} label={s.results.finalWithText} />
          {cleanName && <DownloadButton url={`/api/jobs/${encodeURIComponent(job.id)}/files/${cleanName}`} name={cleanName} label={s.results.cleanMaster} />}
        </div>
      </div>

      <CaptionEditor jobId={job.id} />

      {final?.frames.length ? (
        <section aria-labelledby="frames">
          <h2 id="frames" className="mb-3 font-sans text-sm font-semibold text-muted-foreground">{s.results.frames}</h2>
          <div className="grid max-w-3xl grid-cols-3 gap-2 sm:grid-cols-6">
            {final.frames.map((u, i) => (
              <motion.div key={u} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.04 }} className="aspect-9-16 overflow-hidden rounded-lg bg-surface ring-1 ring-foreground/8">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={fileUrl(u)} alt={`Frame ${i + 1}`} className="size-full object-cover" loading="lazy" />
              </motion.div>
            ))}
          </div>
        </section>
      ) : null}

      <ClipWorkbench job={job} onSend={onSend} />

      <div className="grid gap-8">
        <section aria-labelledby="personalization">
          <h2 id="personalization" className="font-display text-2xl font-medium">{s.results.personalization}</h2>
          <p className="mt-1 mb-4 text-sm text-muted-foreground">{s.results.personalizationHint}</p>
          <div className="space-y-3">
            {job.products.length === 0 && job.people.length === 0 && (
              <p className="rounded-2xl bg-card p-6 text-center text-sm text-muted-foreground ring-1 ring-foreground/8">{s.common.none}</p>
            )}
            {(job.products.length ? job.products : job.people.map((p) => ({ name: "", image: "", file: "", artwork: null, person: p.name }))).map((pr, i) => {
              const person = job.people.find((p) => p.name.toLowerCase() === (pr.person ?? "").toLowerCase()) ?? job.people[i] ?? null;
              return (
                <motion.div key={pr.file || pr.person || i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }} className="grid grid-cols-[1fr_1fr_auto] items-center gap-3 rounded-2xl bg-card p-3 ring-1 ring-foreground/8 sm:p-4">
                  <figure className="min-w-0">
                    <div className="aspect-square overflow-hidden rounded-xl bg-surface ring-1 ring-foreground/8">
                      {person ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={fileUrl(person.image)} alt={person.name} className="size-full object-cover" loading="lazy" />
                      ) : <span className="grid size-full place-items-center text-xs text-muted-foreground">{s.common.none}</span>}
                    </div>
                    <figcaption className="mt-1.5 truncate text-sm font-semibold">{person?.name ?? pr.person ?? "–"}</figcaption>
                    {person?.image ? <DownloadButton url={person.image} className="mt-1" label={s.common.download} /> : null}
                  </figure>
                  <figure className="min-w-0">
                    <div className="aspect-square overflow-hidden rounded-xl bg-surface ring-1 ring-foreground/8">
                      {pr.image ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={fileUrl(pr.image)} alt={pr.name} className="size-full object-cover" loading="lazy" />
                      ) : <span className="grid size-full place-items-center text-xs text-muted-foreground">{s.common.none}</span>}
                    </div>
                    <figcaption className="mt-1.5 truncate text-sm text-muted-foreground">{pr.name}</figcaption>
                    {pr.image ? <DownloadButton url={pr.image} className="mt-1" label={s.common.download} /> : null}
                  </figure>
                  <figure className="w-16 sm:w-20">
                    <div className="aspect-[3/4] overflow-hidden rounded-lg bg-surface ring-1 ring-foreground/8">
                      {pr.artwork ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={fileUrl(pr.artwork)} alt={s.results.artwork} className="size-full object-cover" loading="lazy" />
                      ) : null}
                    </div>
                    <figcaption className="mt-1.5 text-[11px] leading-tight text-muted-foreground">{s.results.artwork}</figcaption>
                    {pr.artwork ? <DownloadButton url={pr.artwork} className="mt-1 px-2" label="" /> : null}
                  </figure>
                </motion.div>
              );
            })}
          </div>
        </section>
      </div>

      {job.quality.length > 0 && (
        <section aria-labelledby="scorecard">
          <h2 id="scorecard" className="font-display text-2xl font-medium">{s.results.scorecard}</h2>
          <p className="mt-1 mb-4 text-sm text-muted-foreground">{s.results.scorecardHint}</p>
          <Scorecard rounds={job.quality} needsReview={job.quality[job.quality.length - 1]?.verdict !== "PASS" && job.status === "done"} />
        </section>
      )}

      <section aria-labelledby="revision" className="rounded-3xl bg-card p-5 shadow-soft ring-1 ring-foreground/8 sm:p-6">
        <h2 id="revision" className="flex items-center gap-2 font-display text-2xl font-medium"><Wand2 className="size-5 text-brand" aria-hidden />{s.results.revision}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{s.results.revisionHint}</p>
        {sent ? (
          <p role="status" className="mt-4 rounded-xl bg-success-soft px-3 py-2 text-sm">{s.plan.sent}</p>
        ) : (
          <div className="mt-4 flex flex-col gap-3 sm:flex-row">
            <Textarea value={revision} onChange={(e) => setRevision(e.target.value)} placeholder={s.results.revisionPlaceholder} rows={2} className="min-h-12 flex-1 rounded-xl" aria-label={s.results.revision} />
            <Button className="h-11 self-end rounded-full bg-brand px-5 text-brand-foreground hover:bg-brand/90" onClick={sendRevision} disabled={busy || !revision.trim()}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}{s.results.sendRevision}
            </Button>
          </div>
        )}
        {!sent && (
          <Button variant="outline" size="sm" className="mt-3 rounded-full" disabled={busy}
            onClick={async () => { setBusy(true); try { await onSend(`REVISION: ${s.results.removeTextMessage}`); setSent(true); } finally { setBusy(false); } }}>
            {s.results.removeText}
          </Button>
        )}
      </section>

      <DownloadAll jobId={job.id} />

      <HowMade job={job} events={events} />
    </div>
  );
}

function HowMade({ job, events }: { job: Job; events: RawEvent[] }) {
  const s = t();
  const [open, setOpen] = useState(false);
  const report = job.files.find((f) => f.name === "report.md");
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-3xl bg-card ring-1 ring-foreground/8">
      <CollapsibleTrigger className="flex w-full items-center gap-3 rounded-3xl px-5 py-4 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
        <span className="flex-1 font-display text-xl font-medium">{s.results.howMade}</span>
        <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="grid gap-6 border-t border-border p-5 lg:grid-cols-[360px_minmax(0,1fr)]">
          <div className="space-y-4">
            <StepTimeline steps={job.steps} currentStep={job.current_step} />
            <PaidCallsPanel paid={job.paid_calls} compact />
            {report && (
              <a href={fileUrl(report.local_url)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm font-semibold text-brand hover:underline">
                <FileText className="size-4" aria-hidden />{s.results.report}
              </a>
            )}
          </div>
          <RawLog events={events} defaultOpen />
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
