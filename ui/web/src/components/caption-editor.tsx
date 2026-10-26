"use client";

import { Eye, EyeOff, Loader2, Save, Type, Wand2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DownloadButton } from "@/components/download-button";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { captionsApi, fileUrl, type CaptionDoc, type CaptionItem, type ExportState, type InsetItem } from "@/lib/api";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";

type Preview = { url: string; box: number[] };
type Drag = { kind: "caption" | "inset" | "arrow"; id: string; x0: number; y0: number; dx: number; dy: number; w: number; h: number };

const capKey = (c: CaptionItem) => JSON.stringify(["c", c.text, c.style, c.position, c.x]);
const insKey = (i: InsetItem) => JSON.stringify(["i", i.image, i.position, i.top, i.left ?? null, i.width, i.arrow_to ?? null]);
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const round = (v: number) => Math.round(v * 1000) / 1000;

/** Edit the captions and photo insets of a delivered ad over its clean master, then export a new MP4. */
export function CaptionEditor({ jobId }: { jobId: string }) {
  const s = t();
  const [doc, setDoc] = useState<CaptionDoc | null>(null);
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [edits, setEdits] = useState<{ name: string; url: string }[]>([]);
  const [readOnly, setReadOnly] = useState(false);
  const [exp, setExp] = useState<ExportState | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const [previews, setPreviews] = useState<Record<string, Preview>>({});
  const [drag, setDrag] = useState<Drag | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const stage = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    captionsApi.get(jobId).then((r) => {
      if (!alive) return;
      setDoc(r.doc); setBaseUrl(r.base_url); setEdits(r.edits); setReadOnly(r.read_only); setExp(r.export);
    }).catch((e) => alive && setError(String(e.message ?? e)));
    return () => { alive = false; };
  }, [jobId]);

  // previews of every caption and inset, fetched once per look (text, style, place)
  useEffect(() => {
    if (!doc) return;
    const want: [string, "caption" | "inset", object][] = [
      ...doc.captions.filter((c) => c.text.trim()).map((c) => [capKey(c), "caption", c] as [string, "caption", object]),
      ...doc.insets.map((i) => [insKey(i), "inset", i] as [string, "inset", object]),
    ];
    const missing = want.filter(([k]) => !previews[k]);
    if (!missing.length) return;
    const timer = setTimeout(() => {
      missing.forEach(([k, kind, item]) => {
        captionsApi.preview(jobId, kind, item).then((p) => setPreviews((m) => ({ ...m, [k]: p }))).catch((e) => setError(String(e.message ?? e)));
      });
    }, 350);
    return () => clearTimeout(timer);
  }, [doc, jobId, previews]);

  useEffect(() => {
    if (exp?.state !== "running") return;
    const id = setInterval(() => {
      captionsApi.status(jobId).then((st) => {
        setExp(st);
        if (st.state === "done") captionsApi.get(jobId).then((r) => setEdits(r.edits));
      }).catch(() => undefined);
    }, 2000);
    return () => clearInterval(id);
  }, [exp?.state, jobId]);

  const update = useCallback((fn: (d: CaptionDoc) => CaptionDoc) => { setDoc((d) => (d ? fn(d) : d)); setDirty(true); }, []);
  const setCap = (id: string, patch: Partial<CaptionItem>) => update((d) => ({ ...d, captions: d.captions.map((c) => (c.id === id ? { ...c, ...patch } : c)) }));
  const setIns = (id: string, patch: Partial<InsetItem>) => update((d) => ({ ...d, insets: d.insets.map((i) => (i.id === id ? { ...i, ...patch } : i)) }));

  const allOff = doc ? doc.captions.every((c) => !c.enabled) && doc.insets.every((i) => !i.enabled) : false;
  const active = useMemo(() => {
    if (!doc) return { caps: [] as CaptionItem[], ins: [] as InsetItem[] };
    return {
      caps: doc.captions.filter((c) => c.enabled && c.text.trim() && time >= c.start && time < c.end),
      ins: doc.insets.filter((i) => i.enabled && time >= i.start && time < i.end),
    };
  }, [doc, time]);

  const fraction = (e: React.PointerEvent) => {
    const r = stage.current!.getBoundingClientRect();
    return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height];
  };
  const startDrag = (kind: Drag["kind"], id: string) => (e: React.PointerEvent) => {
    if (readOnly) return;
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    const [x, y] = fraction(e);
    const r = stage.current!.getBoundingClientRect();
    setDrag({ kind, id, x0: x, y0: y, dx: 0, dy: 0, w: r.width, h: r.height });
  };
  const moveDrag = (e: React.PointerEvent) => {
    if (!drag) return;
    const [x, y] = fraction(e);
    setDrag({ ...drag, dx: x - drag.x0, dy: y - drag.y0 });
  };
  const endDrag = () => {
    if (!drag || !doc) return setDrag(null);
    const { kind, id, dx, dy } = drag;
    if (kind === "caption") {
      const c = doc.captions.find((x) => x.id === id)!;
      setCap(id, { x: round(clamp(c.x + dx, 0.15, 0.85)), position: round(clamp(c.position + dy, 0.04, 0.92)) });
    } else if (kind === "inset") {
      const i = doc.insets.find((x) => x.id === id)!;
      const box = previews[insKey(i)]?.box ?? [0, i.top, 0.3, i.top + 0.2];
      setIns(id, { left: round(clamp(box[0] + dx, 0, 0.8)), top: round(clamp(i.top + dy, 0.02, 0.9)) });
    } else {
      const i = doc.insets.find((x) => x.id === id)!;
      const [ax, ay] = i.arrow_to ?? [0.5, 0.5];
      setIns(id, { arrow_to: [round(clamp(ax + dx, 0, 1)), round(clamp(ay + dy, 0, 1))] });
    }
    setDrag(null);
  };

  async function save(): Promise<CaptionDoc | null> {
    if (!doc) return null;
    setBusy(true); setError(null);
    try { const r = await captionsApi.save(jobId, doc); setDoc((d) => (d ? { ...d, ...r.doc } : d)); setDirty(false); return r.doc; }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); return null; }
    finally { setBusy(false); }
  }
  async function exportMp4() {
    if (!doc) return;
    setBusy(true); setError(null);
    try { setExp(await captionsApi.export(jobId, doc)); setDirty(false); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  if (error && !doc) return null;
  if (!doc || !doc.base || !baseUrl) return null;
  const [W, H] = doc.size;
  const shift = (kind: Drag["kind"], id: string) => (drag && drag.kind === kind && drag.id === id ? { transform: `translate(${drag.dx * drag.w}px, ${drag.dy * drag.h}px)` } : undefined);

  return (
    <section aria-labelledby="caption-editor" className="rounded-3xl bg-card p-5 ring-1 ring-foreground/8 sm:p-6">
      <h2 id="caption-editor" className="flex items-center gap-2 font-display text-2xl font-medium"><Type className="size-5 text-brand" aria-hidden />{s.editor.title}</h2>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{s.editor.hint}</p>
      <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        <div className="min-w-0">
          <div ref={stage} className="relative mx-auto w-full max-w-[320px] touch-none overflow-hidden rounded-xl bg-black select-none" style={{ aspectRatio: `${W} / ${H}` }}
            onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={() => setDrag(null)}>
            <video ref={video} src={fileUrl(baseUrl)} className="absolute inset-0 size-full object-contain" playsInline controls
              onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)} onSeeked={(e) => setTime(e.currentTarget.currentTime)} />
            {active.ins.map((i) => {
              const p = previews[insKey(i)];
              if (!p) return null;
              const [x0, y0, x1, y1] = p.box;
              const [ax, ay] = i.arrow_to ?? [0, 0];
              return (
                <div key={i.id}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={p.url} alt="" className="pointer-events-none absolute inset-0 size-full" style={shift("inset", i.id)} />
                  <button type="button" aria-label={s.editor.moveInset} onPointerDown={startDrag("inset", i.id)}
                    className="absolute cursor-move rounded-md ring-2 ring-brand/0 hover:ring-brand/70"
                    style={{ left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%`, ...shift("inset", i.id) }} />
                  {i.arrow_to ? (
                    <button type="button" aria-label={s.editor.moveArrow} onPointerDown={startDrag("arrow", i.id)}
                      className="absolute size-4 -translate-x-1/2 -translate-y-1/2 cursor-crosshair rounded-full bg-brand ring-2 ring-white"
                      style={{ left: `${ax * 100}%`, top: `${ay * 100}%`, ...(drag && drag.kind === "arrow" && drag.id === i.id ? { transform: `translate(calc(-50% + ${drag.dx * drag.w}px), calc(-50% + ${drag.dy * drag.h}px))` } : {}) }} />
                  ) : null}
                </div>
              );
            })}
            {active.caps.map((c) => {
              const p = previews[capKey(c)];
              if (!p) return null;
              const [x0, y0, x1, y1] = p.box;
              return (
                <div key={c.id}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={p.url} alt={c.text} className="pointer-events-none absolute inset-0 size-full" style={shift("caption", c.id)} />
                  <button type="button" aria-label={s.editor.moveCaption(c.text)} onPointerDown={startDrag("caption", c.id)}
                    className="absolute cursor-move rounded-md ring-2 ring-brand/0 hover:ring-brand/70"
                    style={{ left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%`, ...shift("caption", c.id) }} />
                </div>
              );
            })}
          </div>
          <p className="mt-2 text-center text-xs text-muted-foreground">{s.editor.dragHint}</p>
        </div>

        <div className="min-w-0 space-y-3">
          <label className="flex items-center justify-between gap-3 rounded-xl bg-surface px-3 py-2 text-sm font-semibold">
            {s.editor.allOff}
            <input type="checkbox" className="size-4 accent-[var(--brand)]" checked={allOff} disabled={readOnly}
              onChange={(e) => update((d) => ({ ...d, captions: d.captions.map((c) => ({ ...c, enabled: !e.target.checked })), insets: d.insets.map((i) => ({ ...i, enabled: !e.target.checked })) }))} />
          </label>
          {doc.captions.map((c, n) => (
            <div key={c.id} className={cn("space-y-2 rounded-xl p-3 ring-1 ring-foreground/8", !c.enabled && "opacity-60")}>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setCap(c.id, { enabled: !c.enabled })} disabled={readOnly} aria-pressed={c.enabled}
                  aria-label={c.enabled ? s.editor.hide : s.editor.show} className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
                  {c.enabled ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
                </button>
                <button type="button" className="text-sm font-semibold hover:underline" onClick={() => { if (video.current) video.current.currentTime = c.start + 0.05; }}>
                  {s.editor.caption(n + 1)}
                </button>
                <span className="ml-auto text-xs text-muted-foreground">{c.style}</span>
              </div>
              <Textarea value={c.text} rows={2} disabled={readOnly} maxLength={110} aria-label={s.editor.caption(n + 1)}
                onChange={(e) => setCap(c.id, { text: e.target.value })} className="rounded-lg text-sm" />
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <TimeField label={s.editor.start} value={c.start} disabled={readOnly} onChange={(v) => setCap(c.id, { start: v })} onNow={() => setCap(c.id, { start: round(time) })} />
                <TimeField label={s.editor.end} value={c.end} disabled={readOnly} onChange={(v) => setCap(c.id, { end: v })} onNow={() => setCap(c.id, { end: round(time) })} />
                <label className="inline-flex items-center gap-1">{s.editor.effect}
                  <select className="rounded-md border border-input bg-background px-1.5 py-1" disabled={readOnly} value={c.animation?.in ?? "none"}
                    onChange={(e) => setCap(c.id, { animation: { ...(c.animation ?? {}), in: e.target.value } })}>
                    {(doc.animations_in ?? ["none"]).map((a) => <option key={a} value={a}>{s.editor.effects[a] ?? a}</option>)}
                  </select>
                </label>
                <label className="inline-flex items-center gap-1">{s.editor.exit}
                  <select className="rounded-md border border-input bg-background px-1.5 py-1" disabled={readOnly} value={c.animation?.out ?? "cut"}
                    onChange={(e) => setCap(c.id, { animation: { ...(c.animation ?? {}), out: e.target.value } })}>
                    {(doc.animations_out ?? ["cut"]).map((a) => <option key={a} value={a}>{s.editor.effects[a] ?? a}</option>)}
                  </select>
                </label>
                <button type="button" className="inline-flex items-center gap-1 text-brand hover:underline disabled:opacity-50" disabled={readOnly}
                  onClick={() => update((d) => ({ ...d, captions: d.captions.map((x) => ({ ...x, animation: { ...(c.animation ?? {}) } })) }))}>
                  <Wand2 className="size-3" aria-hidden />{s.editor.applyAll}
                </button>
              </div>
            </div>
          ))}
          {doc.insets.map((i, n) => (
            <div key={i.id} className={cn("flex flex-wrap items-center gap-2 rounded-xl p-3 text-sm ring-1 ring-foreground/8", !i.enabled && "opacity-60")}>
              <button type="button" onClick={() => setIns(i.id, { enabled: !i.enabled })} disabled={readOnly} aria-pressed={i.enabled}
                aria-label={i.enabled ? s.editor.hide : s.editor.show} className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
                {i.enabled ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
              </button>
              <span className="font-semibold">{s.editor.inset(n + 1)}</span>
              <TimeField label={s.editor.start} value={i.start} disabled={readOnly} onChange={(v) => setIns(i.id, { start: v })} onNow={() => setIns(i.id, { start: round(time) })} />
              <TimeField label={s.editor.end} value={i.end} disabled={readOnly} onChange={(v) => setIns(i.id, { end: v })} onNow={() => setIns(i.id, { end: round(time) })} />
            </div>
          ))}

          {!readOnly && (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button variant="outline" className="rounded-full" onClick={save} disabled={busy || !dirty}><Save className="size-4" />{s.editor.save}</Button>
              <Button className="rounded-full bg-brand text-brand-foreground hover:bg-brand/90" onClick={exportMp4} disabled={busy || exp?.state === "running"}>
                {exp?.state === "running" ? <Loader2 className="size-4 animate-spin" /> : null}{exp?.state === "running" ? s.editor.exporting : s.editor.export}
              </Button>
              {dirty && <span className="text-xs text-muted-foreground">{s.editor.unsaved}</span>}
            </div>
          )}
          {exp?.state === "failed" && <p className="text-sm text-destructive">{exp.error}</p>}
          {exp?.warnings?.length ? <ul className="list-disc pl-5 text-xs text-muted-foreground">{exp.warnings.map((w) => <li key={w}>{w}</li>)}</ul> : null}
          {error && <p className="text-sm text-destructive">{error}</p>}
          {edits.length ? (
            <div className="space-y-1.5 pt-2">
              <h3 className="text-sm font-semibold">{s.editor.versions}</h3>
              <div className="flex flex-wrap gap-2">{edits.map((e) => <DownloadButton key={e.name} url={e.url} name={e.name} label={e.name} />)}</div>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function TimeField({ label, value, onChange, onNow, disabled }: { label: string; value: number; onChange: (v: number) => void; onNow: () => void; disabled?: boolean }) {
  const s = t();
  return (
    <span className="inline-flex items-center gap-1">
      <label className="inline-flex items-center gap-1">{label}
        <input type="number" step={0.1} min={0} value={Number(value.toFixed(2))} disabled={disabled}
          onChange={(e) => onChange(Math.max(0, Number(e.target.value)))} className="w-16 rounded-md border border-input bg-background px-1.5 py-1" />
      </label>
      <button type="button" onClick={onNow} disabled={disabled} className="text-brand hover:underline disabled:opacity-50">{s.editor.now}</button>
    </span>
  );
}
