"use client";

import { Check, ChevronDown, ImagePlus, Loader2, Plus, RotateCcw, X } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, fileUrl, type Clip, type ClipRef, type Job } from "@/lib/api";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";

type Upload = { key: string; name: string; preview: string | null; role: string; note: string; path?: string; error?: string; busy: boolean };

const ROLES = ["product truth", "person look", "scene staging", "style", "first frame"] as const;

function RefThumb({ r, on, onToggle }: { r: ClipRef; on: boolean; onToggle?: () => void }) {
  const s = t();
  const label = r.kind === "first_frame" ? s.clips.firstFrame : r.kind ? r.kind.replace(/_/g, " ") : s.clips.reference;
  return (
    <figure className={cn("min-w-0 transition-opacity", !on && "opacity-40")}>
      <div className="relative aspect-square overflow-hidden rounded-lg bg-surface ring-1 ring-foreground/8">
        {r.url ? (
          <a href={fileUrl(r.url)} target="_blank" rel="noopener" title={r.describe ?? r.file ?? r.id}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={fileUrl(r.url)} alt={r.describe ?? r.id} className="size-full object-cover" loading="lazy" />
          </a>
        ) : (
          <span className="grid size-full place-items-center p-1 text-center text-[10px] leading-tight text-muted-foreground">{r.id}</span>
        )}
        {onToggle && (
          <button type="button" onClick={onToggle} aria-pressed={on} aria-label={on ? s.clips.dropRef(r.file ?? r.id) : s.clips.keepRef(r.file ?? r.id)}
            className="absolute top-1 right-1 grid size-5 place-items-center rounded-full bg-card/90 shadow-soft ring-1 ring-foreground/10">
            {on ? <X className="size-3" /> : <RotateCcw className="size-3" />}
          </button>
        )}
      </div>
      <figcaption className="mt-1 truncate text-[11px] leading-tight"><span className="font-semibold">{label}</span> <span className="text-muted-foreground">{r.file ?? r.id}</span></figcaption>
    </figure>
  );
}

function Uploader({ jobId, uploads, setUploads, disabled }: { jobId: string; uploads: Upload[]; setUploads: (f: (u: Upload[]) => Upload[]) => void; disabled: boolean }) {
  const s = t();
  const input = useRef<HTMLInputElement>(null);
  const add = async (files: FileList | null) => {
    if (!files) return;
    for (const file of Array.from(files)) {
      const key = `${file.name}-${file.size}-${Date.now()}`;
      const preview = file.type.startsWith("image/") ? URL.createObjectURL(file) : null;
      setUploads((u) => [...u, { key, name: file.name, preview, role: ROLES[0], note: "", busy: true }]);
      try {
        const res = await api.uploadToJob(jobId, file, "");
        setUploads((u) => u.map((x) => (x.key === key ? { ...x, busy: false, path: res.path } : x)));
      } catch (e) {
        setUploads((u) => u.map((x) => (x.key === key ? { ...x, busy: false, error: e instanceof Error ? e.message : String(e) } : x)));
      }
    }
  };
  return (
    <div className="space-y-2">
      {uploads.map((u) => (
        <div key={u.key} className="flex items-start gap-2 rounded-xl bg-surface p-2 ring-1 ring-foreground/8">
          <div className="size-14 shrink-0 overflow-hidden rounded-lg bg-muted">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {u.preview ? <img src={u.preview} alt="" className="size-full object-cover" /> : <span className="grid size-full place-items-center text-[10px] text-muted-foreground">{u.name.split(".").pop()}</span>}
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            <p className="flex items-center gap-1.5 truncate text-xs font-semibold">
              {u.busy ? <Loader2 className="size-3 animate-spin" /> : u.error ? <X className="size-3 text-danger" /> : <Check className="size-3 text-success" />}
              {u.name}
            </p>
            {u.error ? <p className="text-xs text-danger">{u.error}</p> : null}
            <div className="flex flex-wrap gap-1">
              {ROLES.map((r) => (
                <button key={r} type="button" onClick={() => setUploads((x) => x.map((y) => (y.key === u.key ? { ...y, role: r } : y)))}
                  className={cn("rounded-full px-2 py-0.5 text-[11px] ring-1", u.role === r ? "bg-brand text-brand-foreground ring-brand" : "bg-card ring-foreground/10 hover:bg-muted")}>
                  {s.clips.roles[r]}
                </button>
              ))}
            </div>
            <Input value={u.note} onChange={(e) => setUploads((x) => x.map((y) => (y.key === u.key ? { ...y, note: e.target.value } : y)))}
              placeholder={s.clips.notePlaceholder} className="h-8 rounded-lg text-xs" aria-label={s.clips.notePlaceholder} />
          </div>
          <button type="button" aria-label={s.clips.removeUpload} onClick={() => setUploads((x) => x.filter((y) => y.key !== u.key))} className="p-1 text-muted-foreground hover:text-foreground"><X className="size-4" /></button>
        </div>
      ))}
      <input ref={input} type="file" multiple accept="image/*,video/*" className="hidden" onChange={(e) => { void add(e.target.files); e.target.value = ""; }} />
      <Button type="button" variant="outline" size="sm" className="rounded-full" disabled={disabled} onClick={() => input.current?.click()}>
        <ImagePlus className="size-4" />{s.clips.upload}
      </Button>
    </div>
  );
}

function refLines(uploads: Upload[]): string[] {
  return uploads.filter((u) => u.path && !u.error).map((u) => `- ${u.path} | ${u.role}${u.note.trim() ? ` | ${u.note.trim()}` : ""}`);
}

function ClipCard({ job, clip, onSend, index }: { job: Job; clip: Clip; onSend: (text: string) => Promise<unknown>; index: number }) {
  const s = t();
  const refs = clip.references ?? [];
  const stillRefs = clip.still_references ?? [];
  const [prompt, setPrompt] = useState(clip.prompt ?? "");
  const [stillPrompt, setStillPrompt] = useState(clip.still_prompt ?? "");
  const [dropped, setDropped] = useState<Record<string, boolean>>({});
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [open, setOpen] = useState(index === 0);
  const pending = uploads.some((u) => u.busy);
  const toggle = (r: ClipRef) => setDropped((d) => ({ ...d, [r.file ?? r.id]: !d[r.file ?? r.id] }));

  const regenerate = async () => {
    const lines = [`REGENERATE: clip ${clip.id} | PROMPT: ${prompt.trim()}`];
    if (clip.still_prompt != null && stillPrompt.trim() && stillPrompt.trim() !== (clip.still_prompt ?? "").trim()) lines.push(`STILL PROMPT (rebuild the opening still first): ${stillPrompt.trim()}`);
    const drop = [...refs, ...stillRefs].filter((r) => dropped[r.file ?? r.id]).map((r) => r.file ?? r.id);
    if (drop.length) lines.push(`DROP REFERENCES: ${drop.join(", ")}`);
    const add = refLines(uploads);
    if (add.length) lines.push("REFERENCES:", ...add);
    setBusy(true);
    try { await onSend(lines.join("\n")); setSent(true); } finally { setBusy(false); }
  };

  return (
    <details open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)} className="group rounded-2xl bg-card ring-1 ring-foreground/8 open:shadow-soft">
      <summary className="flex cursor-pointer list-none items-center gap-3 p-3">
        <div className="aspect-9-16 w-10 shrink-0 overflow-hidden rounded-md bg-surface">
          <video src={`${fileUrl(clip.url)}#t=0.5`} muted playsInline preload="metadata" className="size-full object-cover" aria-hidden />
        </div>
        <span className="flex-1 text-sm">
          <span className="font-semibold">{clip.id.replace("_", " ")}</span>
          <span className="text-muted-foreground">{clip.duration_s ? ` · ${clip.duration_s}s` : ""}{clip.mode ? ` · ${s.clips.mode(clip.mode)}` : ""}{clip.takes?.length ? ` · ${s.clips.takes(clip.takes.length + 1)}` : ""}</span>
          {clip.summary ? <span className="block truncate text-xs text-muted-foreground">{clip.summary}</span> : null}
        </span>
        <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="grid gap-4 px-3 pb-4 sm:grid-cols-[180px_minmax(0,1fr)]">
        <div className="space-y-2">
          <video src={fileUrl(clip.url)} controls playsInline preload="metadata" className="aspect-9-16 w-full rounded-xl bg-black object-contain" aria-label={clip.id} />
          <p className="truncate text-[11px] text-muted-foreground">{s.clips.current}: {clip.file}</p>
          {clip.takes?.length ? (
            <details className="text-xs">
              <summary className="cursor-pointer text-muted-foreground hover:text-foreground">{s.clips.earlierTakes(clip.takes.length)}</summary>
              <ul className="mt-1 space-y-0.5">
                {[...clip.takes].reverse().map((tk) => <li key={tk.file}><a className="text-brand hover:underline" href={fileUrl(tk.url)} target="_blank" rel="noopener">{tk.file}</a></li>)}
              </ul>
            </details>
          ) : null}
        </div>
        <div className="min-w-0 space-y-4">
          <section>
            <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{s.clips.inputs}</h4>
            {refs.length ? (
              <div className="grid grid-cols-4 gap-2 sm:grid-cols-5">{refs.map((r) => <RefThumb key={`${r.id}-${r.file}`} r={r} on={!dropped[r.file ?? r.id]} onToggle={() => toggle(r)} />)}</div>
            ) : <p className="text-xs text-muted-foreground">{s.clips.noRefs}</p>}
            {stillRefs.length ? (
              <>
                <h4 className="mt-3 mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{s.clips.stillInputs}</h4>
                <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">{stillRefs.map((r) => <RefThumb key={`s-${r.id}-${r.file}`} r={r} on={!dropped[r.file ?? r.id]} onToggle={() => toggle(r)} />)}</div>
              </>
            ) : null}
          </section>
          {clip.still_prompt != null ? (
            <section>
              <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{s.clips.stillPrompt}</h4>
              <Textarea value={stillPrompt} onChange={(e) => setStillPrompt(e.target.value)} rows={5} className="rounded-xl font-mono text-xs leading-relaxed" aria-label={s.clips.stillPrompt} />
            </section>
          ) : null}
          <section>
            <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{s.clips.prompt}{clip.prompt_file ? <span className="font-normal normal-case"> · {clip.prompt_file}</span> : null}</h4>
            <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={7} className="rounded-xl font-mono text-xs leading-relaxed" aria-label={s.clips.prompt} placeholder={s.clips.noPrompt} />
          </section>
          <section>
            <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{s.clips.addRefs}</h4>
            <Uploader jobId={job.id} uploads={uploads} setUploads={setUploads} disabled={!!job.demo} />
          </section>
          <div className="flex flex-wrap items-center gap-2">
            <Button className="rounded-full bg-brand text-brand-foreground hover:bg-brand/90" disabled={busy || sent || pending || !prompt.trim() || !!job.demo} onClick={regenerate}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : sent ? <Check className="size-4" /> : <RotateCcw className="size-4" />}
              {sent ? s.clips.sent : s.clips.regenerate}
            </Button>
            {sent ? <button type="button" className="text-xs text-muted-foreground hover:underline" onClick={() => setSent(false)}>{s.clips.again}</button> : null}
            {pending ? <span className="text-xs text-muted-foreground">{s.clips.waitUploads}</span> : null}
          </div>
        </div>
      </div>
    </details>
  );
}

function NewClip({ job, onSend }: { job: Job; onSend: (text: string) => Promise<unknown> }) {
  const s = t();
  const [text, setText] = useState("");
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const scenes = job.analysis?.scenes ?? [];
  const send = async () => {
    const lines = [`ADD CLIP: ${text.trim()}`];
    const add = refLines(uploads);
    if (add.length) lines.push("REFERENCES:", ...add);
    setBusy(true);
    try { await onSend(lines.join("\n")); setSent(true); setText(""); setUploads([]); } finally { setBusy(false); }
  };
  return (
    <details className="group rounded-2xl bg-card ring-1 ring-dashed ring-foreground/15">
      <summary className="flex cursor-pointer list-none items-center gap-3 p-3 text-sm font-semibold">
        <span className="grid size-8 place-items-center rounded-full bg-muted"><Plus className="size-4" /></span>
        <span className="flex-1">{s.clips.newClip}<span className="block text-xs font-normal text-muted-foreground">{s.clips.newClipHint}</span></span>
        <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="space-y-3 px-3 pb-4">
        {scenes.length ? (
          <div className="flex flex-wrap gap-1">
            {scenes.map((sc, i) => (
              <button key={i} type="button" className="rounded-full bg-muted px-2 py-0.5 text-[11px] hover:bg-muted/70" title={sc.description}
                onClick={() => setText((v) => `${v ? `${v} ` : ""}Recreate sample scene ${sc.index ?? i + 1}${sc.description ? ` (${sc.description})` : ""}.`)}>
                {s.clips.scene(sc.index ?? i + 1)}{typeof sc.start === "number" ? ` · ${sc.start.toFixed(1)}s` : ""}
              </button>
            ))}
          </div>
        ) : null}
        <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} className="rounded-xl text-sm" placeholder={s.clips.newClipPlaceholder} aria-label={s.clips.newClip} />
        <Uploader jobId={job.id} uploads={uploads} setUploads={setUploads} disabled={!!job.demo} />
        <Button className="rounded-full bg-brand text-brand-foreground hover:bg-brand/90" disabled={busy || !text.trim() || uploads.some((u) => u.busy) || !!job.demo} onClick={send}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : sent ? <Check className="size-4" /> : <Plus className="size-4" />}{sent ? s.clips.sent : s.clips.addClip}
        </Button>
      </div>
    </details>
  );
}

/** Every clip with the inputs and prompts that made it; edit, add reference uploads and regenerate one clip at a time. */
export function ClipWorkbench({ job, onSend }: { job: Job; onSend: (text: string) => Promise<unknown> }) {
  const s = t();
  if (!job.clips.length) return null;
  return (
    <section aria-labelledby="clip-workbench">
      <h2 id="clip-workbench" className="mb-1 font-display text-xl font-medium">{s.clips.title} <span className="text-base font-normal text-muted-foreground">· {job.clips.length}</span></h2>
      <p className="mb-3 text-sm text-muted-foreground">{s.clips.hint}</p>
      <div className="space-y-3">
        {job.clips.map((c, i) => <ClipCard key={`${c.id}-${c.file}-${c.takes?.length ?? 0}`} job={job} clip={c} onSend={onSend} index={i} />)}
        <NewClip job={job} onSend={onSend} />
      </div>
    </section>
  );
}
