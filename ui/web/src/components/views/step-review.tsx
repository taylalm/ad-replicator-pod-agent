"use client";

import { motion } from "framer-motion";
import { Check, ChevronDown, Loader2, MessageSquareText } from "lucide-react";
import { useMemo, useState } from "react";
import { ClipWorkbench } from "@/components/clip-workbench";
import { FileThumb } from "@/components/file-thumb";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { fileUrl, type Job, type JobFile, type PersonPrompt, type ClipPrompt } from "@/lib/api";
import { fileLabel, latestVersions } from "@/lib/format";
import { t } from "@/i18n";

const SECONDARY = /^(sample|source)\.(mp4|mov)$|^form_filled|^after_step|^scene_\d+_[\d.]+s\.|^check_|^probe_page_full|^error_step|^extraction\.json$|^manifest\.json$|^paid_calls\.json$|^cgt-|__[a-z0-9]{5}\.|^frame_clip_|^clip_\d+[\w-]*_\d+(\.\d+)?s?\.(jpe?g|png)$|_(sheet|band|zoom|zooms|frames|timeline)(_[\w-]+)?\.(jpe?g|png)$|^wm_\d+\.|^staging_scene_|^v\d+_|^in\d+\.|^step\d+\./i;

/** Files worth showing for a step, most relevant first, media only. */
function stepFiles(files: JobFile[], n: number, currentClips?: Set<string>): JobFile[] {
  const isClip = (f: JobFile) => f.kind === "video" && /^clip_\d+/i.test(f.name);
  const pool = files.filter((f) => f.step === n && (f.kind === "image" || f.kind === "video") && !SECONDARY.test(f.name));
  // clip takes: the backend already picked the current take of each clip (clips.json first)
  const media = currentClips && currentClips.size
    ? [...latestVersions(pool.filter((f) => !isClip(f))), ...pool.filter((f) => isClip(f) && currentClips.has(f.name))]
    : latestVersions(pool);
  const rank = (f: JobFile) =>
    /^person_/.test(f.name) ? 0 : /^product_/.test(f.name) ? 1 : /^variant_|dialog/.test(f.name) ? 2 : /^artwork_/.test(f.name) ? 3 :
    /^clip_\d+[\w-]*\.(mp4|mov|webm)$/.test(f.name) ? 0 : /^final_v\d+\.mp4$/.test(f.name) ? 0 : /^contact_sheet_/.test(f.name) ? 0 : /_start\./.test(f.name) ? 1 : 5;
  return [...media].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}

function aspectFor(f: JobFile): "auto" | "portrait" | "square" {
  if (f.kind === "video" || /^final_v\d+_frame_|^scene_\d+_start/.test(f.name)) return "portrait";
  if (/^contact_sheet_|^quality_round_|^watermark_check|^probe/.test(f.name)) return "auto";
  return "square";
}

function firstSentences(text: string | null | undefined, max = 320): string {
  if (!text) return "";
  const clean = text.replace(/\*\*/g, "").replace(/^\s*[-*]\s+/gm, "").replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max);
  const end = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("; "));
  return (end > 120 ? cut.slice(0, end + 1) : cut) + " …";
}

export function StepReview({ job, onSend, replay }: { job: Job; onSend: (text: string) => Promise<unknown>; replay: boolean }) {
  const s = t();
  const n = job.awaiting_step ?? 0;
  const step = job.steps.find((st) => st.n === n);
  const [mode, setMode] = useState<"idle" | "changes">("idle");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"approve" | "changes" | null>(null);
  const [sent, setSent] = useState(false);
  const [showFull, setShowFull] = useState(false);
  const currentClips = useMemo(() => new Set(job.clips.map((c) => c.file)), [job.clips]);
  const current = useMemo(() => stepFiles(job.files, n, currentClips), [job.files, n, currentClips]);
  const earlier = useMemo(() => job.steps.filter((st) => st.n < n && st.status === "done").map((st) => ({ step: st, files: stepFiles(job.files, st.n, currentClips) })), [job.steps, job.files, n, currentClips]);
  const open = (f: JobFile) => window.open(fileUrl(f.local_url), "_blank", "noopener");

  const send = async (msg: string, kind: "approve" | "changes") => {
    setBusy(kind);
    try {
      await onSend(msg);
      setSent(true);
    } finally {
      setBusy(null);
    }
  };

  const bigGrid = current.length <= 4 && current.every((f) => aspectFor(f) !== "auto");

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="space-y-8">
        <section aria-labelledby="step-outputs">
          <h2 id="step-outputs" className="mb-3 font-display text-xl font-medium">{s.stepReview.outputs(step?.name ?? "")} <span className="text-base font-normal text-muted-foreground">· {current.length}</span></h2>
          {current.length === 0 ? (
            <p className="rounded-2xl bg-card p-6 text-sm text-muted-foreground ring-1 ring-foreground/8">{s.stepReview.noOutputs}</p>
          ) : (
            <div className={bigGrid ? "grid grid-cols-2 gap-4 sm:grid-cols-4" : "grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"}>
              {current.map((f, i) => (
                <FileThumb key={f.name} file={f} index={i} aspect={aspectFor(f)} caption={fileLabel(f.name)} onClick={() => open(f)} />
              ))}
            </div>
          )}
          {current.length > 0 && <p className="mt-2 text-xs text-muted-foreground">{s.stepReview.clickToOpen}</p>}
        </section>

        <PromptsPanel job={job} step={n} onSend={onSend} />

        {n >= 7 && <ClipWorkbench job={job} onSend={onSend} />}

        {earlier.length > 0 && (
          <section aria-labelledby="earlier">
            <h2 id="earlier" className="mb-3 font-display text-xl font-medium">{s.stepReview.earlier}</h2>
            <div className="space-y-3">
              {earlier.map(({ step: st, files }) => (
                <details key={st.n} className="group rounded-2xl bg-card ring-1 ring-foreground/8 open:shadow-soft">
                  <summary className="flex cursor-pointer list-none items-center gap-3 p-4">
                    <span className="flex size-7 items-center justify-center rounded-full bg-success-soft text-success"><Check className="size-4" aria-hidden /></span>
                    <span className="flex-1 text-sm"><span className="font-semibold">{s.live.stepOf(st.n)} · {st.name}</span>{files.length ? <span className="text-muted-foreground"> · {files.length} {s.stepReview.filesWord}</span> : null}</span>
                    <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden />
                  </summary>
                  <div className="space-y-3 px-4 pb-4">
                    {(st.latest_message || (st.n === 3 && job.plan_text)) ? (
                      <div className="rounded-xl bg-surface p-4 text-sm ring-1 ring-foreground/8"><Markdown text={st.latest_message || job.plan_text || ""} /></div>
                    ) : null}
                    {files.length > 0 && (
                      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                        {files.slice(0, 12).map((f, i) => <FileThumb key={f.name} file={f} index={i} aspect={aspectFor(f)} onClick={() => open(f)} />)}
                      </div>
                    )}
                  </div>
                </details>
              ))}
            </div>
          </section>
        )}
      </div>

      <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="rounded-3xl bg-card p-5 shadow-soft ring-1 ring-foreground/8">
          <h2 className="font-display text-xl font-medium">{s.plan.stepDecision}</h2>
          {step?.latest_message ? (
            <div className="mt-2 text-sm text-muted-foreground">
              {showFull ? <div className="text-sm"><Markdown text={step.latest_message} /></div> : <p>{firstSentences(step.latest_message)}</p>}
              {step.latest_message.length > 320 && (
                <button type="button" className="mt-1 text-xs font-semibold text-brand hover:underline" onClick={() => setShowFull((v) => !v)}>
                  {showFull ? s.stepReview.showLess : s.stepReview.showMore}
                </button>
              )}
            </div>
          ) : null}
          <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
            {(["seedream", "seedance", "evaluator"] as const).map((k) => (
              <div key={k} className="rounded-xl bg-muted p-2">
                <dt className="text-[11px] leading-tight text-muted-foreground">{s.newJob.budget[k]}</dt>
                <dd className="font-display text-xl font-medium tabular-nums">{job.paid_calls[k]}<span className="text-xs text-muted-foreground"> {job.paid_calls.budget[k] > 0 ? `/ ${job.paid_calls.budget[k]}` : `· ${s.newJob.budget.noCap.toLowerCase()}`}</span></dd>
              </div>
            ))}
          </dl>
          <p className="mt-1 text-center text-[11px] text-muted-foreground">{s.stepReview.paidSoFar}</p>
          {sent ? (
            <p role="status" className="mt-4 flex items-center gap-2 rounded-xl bg-success-soft px-3 py-2 text-sm"><Check className="size-4 text-success" aria-hidden />{s.plan.sent}</p>
          ) : mode === "idle" ? (
            <div className="mt-4 flex flex-col gap-2">
              <Button size="lg" className="h-11 rounded-full bg-brand text-base text-brand-foreground hover:bg-brand/90" onClick={() => send("APPROVE", "approve")} disabled={busy != null} data-testid="approve">
                {busy === "approve" ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
                {s.plan.approveStep}
              </Button>
              <Button variant="outline" size="lg" className="h-11 rounded-full" onClick={() => setMode("changes")} disabled={busy != null}>
                <MessageSquareText className="size-4" />{s.plan.requestChanges}
              </Button>
              {replay && <p className="text-center text-xs text-muted-foreground">{s.plan.replayApproveHint}</p>}
            </div>
          ) : (
            <div className="mt-4 space-y-2">
              <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={s.stepReview.changesPlaceholder} rows={4} className="rounded-xl" aria-label={s.plan.requestChanges} autoFocus />
              <div className="flex gap-2">
                <Button className="rounded-full bg-brand text-brand-foreground hover:bg-brand/90" onClick={() => send(`CHANGES: ${text.trim()}`, "changes")} disabled={!text.trim() || busy != null}>
                  {busy === "changes" ? <Loader2 className="size-4 animate-spin" /> : null}{s.plan.sendChanges}
                </Button>
                <Button variant="ghost" className="rounded-full" onClick={() => setMode("idle")}>{s.plan.cancel}</Button>
              </div>
            </div>
          )}
        </motion.div>
      </aside>
    </div>
  );
}


function latestByName<T extends { version?: number | string | null }>(items: T[], key: (x: T) => string): T[] {
  const best = new Map<string, T>();
  for (const it of items) {
    const k = key(it);
    const cur = best.get(k);
    if (!cur || Number(it.version ?? 0) >= Number(cur.version ?? 0)) best.set(k, it);
  }
  return [...best.values()];
}

/** Editable prompts for the AI people (step 4) and the clips (step 7); regenerates one item at a time. */
function PromptsPanel({ job, step, onSend }: { job: Job; step: number; onSend: (text: string) => Promise<unknown> }) {
  const s = t();
  const people = step >= 4 ? latestByName(job.prompts?.people ?? [], (p) => (p.name ?? p.file ?? "").toLowerCase()) : [];
  const clips = step >= 7 && !job.clips.length ? (job.prompts?.clips ?? []) : [];
  const items: Array<{ key: string; label: string; target: string; prompt: string; image?: string }> = [
    ...people.map((p: PersonPrompt) => ({ key: `person:${p.name}`, label: p.name ?? p.file ?? "", target: `person ${p.name ?? p.file}`, prompt: p.prompt,
      image: job.people.find((x) => (x.name ?? "").toLowerCase() === (p.name ?? "").toLowerCase())?.image })),
    ...clips.map((c: ClipPrompt) => ({ key: `clip:${c.id}`, label: c.id.replace("_", " "), target: `clip ${c.id}`, prompt: c.prompt })),
  ];
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [sent, setSent] = useState<Record<string, boolean>>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="prompts">
      <h2 id="prompts" className="mb-1 font-display text-xl font-medium">{s.stepReview.prompts}</h2>
      <p className="mb-3 text-sm text-muted-foreground">{s.stepReview.promptsHint}</p>
      <div className="space-y-3">
        {items.map((it) => {
          const draft = drafts[it.key] ?? it.prompt;
          const changed = draft.trim() !== it.prompt.trim();
          return (
            <details key={it.key} open={open[it.key]} onToggle={(e) => setOpen((o) => ({ ...o, [it.key]: (e.target as HTMLDetailsElement).open }))} className="group rounded-2xl bg-card ring-1 ring-foreground/8 open:shadow-soft">
              <summary className="flex cursor-pointer list-none items-center gap-3 p-4">
                {it.image ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={fileUrl(it.image)} alt="" className="size-10 rounded-lg object-cover" />
                ) : null}
                <span className="flex-1 text-sm font-semibold">{s.stepReview.promptFor(it.label)}</span>
                <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden />
              </summary>
              <div className="space-y-2 px-4 pb-4">
                <Textarea value={draft} onChange={(e) => setDrafts((d) => ({ ...d, [it.key]: e.target.value }))} rows={6} className="rounded-xl font-mono text-xs leading-relaxed" aria-label={s.stepReview.promptFor(it.label)} />
                <div className="flex items-center gap-2">
                  <Button size="sm" className="rounded-full bg-brand text-brand-foreground hover:bg-brand/90" disabled={!!sent[it.key] || !draft.trim()}
                    onClick={async () => { await onSend(`REGENERATE: ${it.target} | PROMPT: ${draft.trim()}`); setSent((x) => ({ ...x, [it.key]: true })); }}>
                    {sent[it.key] ? <Check className="size-4" /> : null}{sent[it.key] ? s.stepReview.regenerating : s.stepReview.regenerate}
                  </Button>
                  {changed && !sent[it.key] ? <span className="text-xs text-muted-foreground">edited</span> : null}
                </div>
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}
