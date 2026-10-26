"use client";

import { Bot, Check, Clapperboard, ImageIcon, Loader2, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { DownloadButton } from "@/components/download-button";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { fileUrl, genApi, type Clip, type Draft, type ExportState, type GenInput, type GenRun, type Job, type WebTake } from "@/lib/api";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";

export type GenStatus = { run: GenRun | null; takes: WebTake[]; models: { video: Record<string, string>; image: Record<string, string> } };

/** One poll for the whole clip workbench: faster while a generation runs. */
export function useGen(jobId: string, enabled: boolean) {
  const [status, setStatus] = useState<GenStatus | null>(null);
  const refresh = useCallback(() => genApi.status(jobId).then(setStatus).catch(() => undefined), [jobId]);
  useEffect(() => { if (enabled) void refresh(); }, [enabled, refresh]);
  useEffect(() => {
    if (!enabled || status?.run?.state !== "running") return;
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [enabled, status?.run?.state, refresh]);
  return { status, refresh };
}

const fileApi = (job: Job, name: string) => `/api/jobs/${encodeURIComponent(job.id)}/files/${name}`;

function Verdict({ take }: { take: WebTake }) {
  const s = t();
  const v = take.check?.verdict;
  return (
    <div className="space-y-1 text-xs">
      <span className={cn("inline-flex rounded-md px-1.5 py-0.5 font-semibold", v === "PASS" ? "bg-success-soft text-success" : v ? "bg-danger/10 text-danger" : "bg-muted text-muted-foreground")}>
        {v ? s.studio.check(v) : s.studio.noCheck}
      </span>
      {take.check?.summary ? <p className="text-muted-foreground">{take.check.summary}</p> : null}
      {take.check?.issues?.length ? (
        <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">{take.check.issues.map((i, k) => <li key={k}><span className="font-semibold">{i.kind.replace(/_/g, " ")}</span>: {i.detail}</li>)}</ul>
      ) : null}
    </div>
  );
}

export function ClipStudio({ job, clip, gen, refresh, prompt, stillPrompt, firstFrame, images, attachments, onLoadDraft, onRebuild }: {
  job: Job; clip: Clip; gen: GenStatus | null; refresh: () => Promise<unknown>;
  prompt: string; stillPrompt: string; firstFrame: string | null; images: string[];
  attachments: { path: string; note?: string }[];
  onLoadDraft: (d: Draft) => void;
  onRebuild?: (st: ExportState) => void;
}) {
  const s = t();
  const [videoModel, setVideoModel] = useState(clip.model?.includes("glwxh") ? "seedance-2.0-fast" : clip.model?.includes("z2gxf") ? "seedance-2.0-mini" : clip.model?.includes("wf5mn") ? "seedance-2.0" : "seedance-2.5");
  const [imageModel, setImageModel] = useState("seedream-5.0-pro");
  const [duration, setDuration] = useState(Math.round(clip.duration_s ?? 5));
  const [resolution, setResolution] = useState("480p");
  const [audio, setAudio] = useState(true);
  const [payoff, setPayoff] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const [target, setTarget] = useState("clip");
  const [draftSent, setDraftSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const run = gen?.run;
  const running = run?.state === "running";
  const mine = running && run?.clip === clip.id;
  const takes = (gen?.takes ?? []).filter((x) => x.clip === clip.id);
  const stills = takes.filter((x) => x.kind === "still").reverse();
  const clipTakes = takes.filter((x) => x.kind === "clip").reverse();
  const readOnly = !!job.demo || !!job.read_only;

  const go = async (kind: "still" | "clip") => {
    setError(null); setBusy(true);
    try {
      const stillRefs = (clip.still_references ?? []).filter((r) => r.file).map((r) => r.file!);
      const inputs: GenInput[] = kind === "still"
        // the still's own inputs when recorded; otherwise edit the current first frame with the clip's @Image inputs
        ? (stillRefs.length ? stillRefs : [...(firstFrame ? [firstFrame] : []), ...images]).map((f) => ({ file: f, role: "reference" as const }))
        : [...(firstFrame ? [{ file: firstFrame, role: "first_frame" as const }] : []), ...images.map((f) => ({ file: f, role: "reference" as const }))];
      await genApi.generate(job.id, kind === "still"
        ? { kind, clip: clip.id, prompt: stillPrompt, inputs, model: imageModel }
        : { kind, clip: clip.id, prompt, inputs, model: videoModel, duration, resolution, audio, payoff: payoff.trim() || undefined });
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const accept = async (file: string) => {
    setError(null);
    try {
      const r = await genApi.accept(job.id, file);
      if (r.rebuild) onRebuild?.(r.rebuild);  // a clip take goes straight into the ad
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  const askAgent = async () => {
    setError(null); setBusy(true);
    try {
      await genApi.draft(job.id, { clip: clip.id, target, feedback: feedback.trim(), model: target === "still" ? imageModel : videoModel, attachments });
      setDraftSent(true); setFeedback("");
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const drafts = [...(clip.drafts ?? [])].reverse();
  const select = "rounded-md border border-input bg-background px-1.5 py-1 text-xs";

  return (
    <div className="space-y-4 border-t border-foreground/8 pt-4">
      {/* agent rewrite: short feedback in any language -> a reviewed English draft */}
      <section className="space-y-2 rounded-xl bg-surface p-3">
        <h4 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase"><Bot className="size-3.5" aria-hidden />{s.studio.askAgent}</h4>
        <p className="text-xs text-muted-foreground">{s.studio.askAgentHint}</p>
        <Textarea value={feedback} rows={2} onChange={(e) => setFeedback(e.target.value)} placeholder={s.studio.feedbackPlaceholder} disabled={readOnly} className="rounded-lg text-sm" aria-label={s.studio.askAgent} />
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label className="inline-flex items-center gap-1">{s.studio.target}
            <select className={select} value={target} onChange={(e) => setTarget(e.target.value)} disabled={readOnly}>
              <option value="clip">{s.studio.targets.clip}</option><option value="still">{s.studio.targets.still}</option><option value="both">{s.studio.targets.both}</option>
            </select>
          </label>
          {attachments.length ? <span className="text-muted-foreground">{s.studio.attachments(attachments.length)}</span> : null}
          <Button size="sm" className="rounded-full" onClick={askAgent} disabled={readOnly || busy || !feedback.trim()}><Sparkles className="size-3.5" />{s.studio.sendDraft}</Button>
          {draftSent ? <span role="status" className="text-success">{s.studio.draftSent}</span> : null}
        </div>
        {drafts.map((d) => (
          <div key={d.file} className="space-y-1.5 rounded-lg bg-card p-2.5 ring-1 ring-foreground/8">
            <p className="text-xs font-semibold">{s.studio.draftFrom(d.file)}</p>
            {d.changes?.length ? <ul className="list-disc pl-4 text-xs">{d.changes.map((c, i) => <li key={i}>{c}</li>)}</ul> : null}
            {d.warnings?.length ? <ul className="list-disc pl-4 text-xs text-danger">{d.warnings.map((c, i) => <li key={i}>{c}</li>)}</ul> : null}
            <details className="text-xs"><summary className="cursor-pointer text-muted-foreground">{s.studio.showPrompt}</summary><p className="mt-1 whitespace-pre-wrap font-mono text-[11px]">{d.prompt}</p></details>
            <Button size="sm" variant="outline" className="rounded-full" onClick={() => onLoadDraft(d)}>{s.studio.loadDraft}</Button>
          </div>
        ))}
      </section>

      {/* opening still (Seedream) */}
      {(clip.still_prompt != null || firstFrame) ? (
        <section className="space-y-2">
          <h4 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase"><ImageIcon className="size-3.5" aria-hidden />{s.studio.still}</h4>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label className="inline-flex items-center gap-1">{s.studio.imageModel}
              <select className={select} value={imageModel} onChange={(e) => setImageModel(e.target.value)} disabled={readOnly}>
                {Object.entries(gen?.models.image ?? { "seedream-5.0-pro": "Seedream 5.0 pro" }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <Button size="sm" variant="outline" className="rounded-full" onClick={() => go("still")} disabled={readOnly || busy || running || stillPrompt.trim().length < 20}>
              {mine && run?.kind === "still" ? <Loader2 className="size-3.5 animate-spin" /> : <ImageIcon className="size-3.5" />}{mine && run?.kind === "still" ? s.studio.working(run?.step) : s.studio.genStill}
            </Button>
          </div>
          {stills.length ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {stills.map((st) => (
                <figure key={st.file} className={cn("space-y-1 rounded-lg p-1.5 ring-1", st.file === firstFrame ? "ring-brand" : "ring-foreground/8")}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={fileUrl(fileApi(job, st.file))} alt={st.file} className="aspect-9-16 w-full rounded-md object-cover" />
                  <Verdict take={st} />
                  <div className="flex flex-wrap gap-1">
                    <Button size="sm" variant={st.file === firstFrame ? "default" : "outline"} className="h-7 rounded-full text-xs" disabled={readOnly}
                      onClick={() => { void accept(st.file); onLoadDraft({ file: st.file, first_frame: st.file }); }}>
                      {st.file === firstFrame ? <Check className="size-3" /> : null}{s.studio.useStill}
                    </Button>
                    <DownloadButton url={fileApi(job, st.file)} name={st.file} label="" />
                  </div>
                </figure>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {/* new take (Seedance) */}
      <section className="space-y-2">
        <h4 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase"><Clapperboard className="size-3.5" aria-hidden />{s.studio.take}</h4>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label className="inline-flex items-center gap-1">{s.studio.videoModel}
            <select className={select} value={videoModel} onChange={(e) => setVideoModel(e.target.value)} disabled={readOnly}>
              {Object.entries(gen?.models.video ?? { "seedance-2.5": "Seedance 2.5" }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="inline-flex items-center gap-1">{s.studio.duration}
            <input type="number" min={4} max={30} value={duration} onChange={(e) => setDuration(Number(e.target.value))} className="w-14 rounded-md border border-input bg-background px-1.5 py-1" disabled={readOnly} />
          </label>
          <label className="inline-flex items-center gap-1">{s.studio.resolution}
            <select className={select} value={resolution} onChange={(e) => setResolution(e.target.value)} disabled={readOnly}><option>480p</option><option>720p</option></select>
          </label>
          <label className="inline-flex items-center gap-1"><input type="checkbox" checked={audio} onChange={(e) => setAudio(e.target.checked)} disabled={readOnly} />{s.studio.sound}</label>
          <input value={payoff} onChange={(e) => setPayoff(e.target.value)} placeholder={s.studio.payoffPlaceholder} disabled={readOnly}
            className="min-w-48 flex-1 rounded-md border border-input bg-background px-2 py-1" aria-label={s.studio.payoffPlaceholder} />
        </div>
        <p className="text-xs text-muted-foreground">{s.studio.inputsUsed(firstFrame, images.length)}</p>
        <Button size="sm" className="rounded-full bg-brand text-brand-foreground hover:bg-brand/90" onClick={() => go("clip")} disabled={readOnly || busy || running || prompt.trim().length < 20}>
          {mine && run?.kind === "clip" ? <Loader2 className="size-3.5 animate-spin" /> : <Clapperboard className="size-3.5" />}{mine && run?.kind === "clip" ? s.studio.working(run?.step) : s.studio.genTake}
        </Button>
        {running && !mine ? <p className="text-xs text-muted-foreground">{s.studio.busyElsewhere(run?.clip ?? "")}</p> : null}
        {clipTakes.length ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {clipTakes.map((tk) => (
              <figure key={tk.file} className={cn("space-y-1 rounded-lg p-1.5 ring-1", tk.accepted ? "ring-brand" : "ring-foreground/8")}>
                <video src={fileUrl(fileApi(job, tk.file))} controls playsInline preload="metadata" className="aspect-9-16 w-full rounded-md bg-black object-contain" />
                <p className="text-[11px] text-muted-foreground">{gen?.models.video[tk.model] ?? tk.model}</p>
                <Verdict take={tk} />
                <div className="flex flex-wrap gap-1">
                  <Button size="sm" variant={tk.accepted ? "default" : "outline"} className="h-7 rounded-full text-xs" disabled={readOnly} onClick={() => accept(tk.file)}>
                    {tk.accepted ? <Check className="size-3" /> : null}{tk.accepted ? s.studio.used : s.studio.useTake}
                  </Button>
                  <DownloadButton url={fileApi(job, tk.file)} name={tk.file} label="" />
                </div>
              </figure>
            ))}
          </div>
        ) : null}
      </section>
      {run?.state === "failed" && run.clip === clip.id ? <p className="text-sm text-destructive">{run.error}</p> : null}
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
    </div>
  );
}
