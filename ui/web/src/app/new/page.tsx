"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, CircleAlert, FileVideo, Loader2, Paperclip, Sparkles, Upload, X } from "lucide-react";
import { Suspense, useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError, type Reference, type ValidateResult } from "@/lib/api";
import { fmtBytes } from "@/lib/format";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";

const LENGTHS = [15, 20, 30];
const RESOLUTIONS = ["480p", "720p"] as const;
const CAPTION_MODES = ["full", "cta_only", "none"] as const;
const VIDEO_MODELS = ["seedance-2.5", "seedance-2.0", "seedance-2.0-fast", "seedance-2.0-mini"] as const;
const IMAGE_MODELS = ["seedream-5.0-pro", "seedream-5.0-flash"] as const;
const SLIDER_MAX = { seedream: 12, seedance: 12, evaluator: 6 };
const NO_CAP = 0;
const DEMO_JOB_ID = process.env.NEXT_PUBLIC_DEMO_JOB_ID || "caseB";
const DEMO_DEFAULTS = {
  title: "Case B: Reading socks for Lily",
  sample: "https://seedance-booth-guests.tos-ap-southeast-1.bytepluses.com/sample-vid-blanket-input.mp4",
  product: "https://macorner.co/products/fck-off-im-reading-funny-sock-for-book-blub-reading-lovers-personalized-socks-maeuhpmto",
};

export default function NewJobPage() {
  return (
    <Suspense fallback={null}>
      <NewJobForm />
    </Suspense>
  );
}

function NewJobForm() {
  const s = t();
  const router = useRouter();
  const params = useSearchParams();
  const demo = params.get("demo") === "1";

  const [title, setTitle] = useState(() => (demo ? DEMO_DEFAULTS.title : ""));
  const [sample, setSample] = useState(() => (demo ? DEMO_DEFAULTS.sample : ""));
  const [product, setProduct] = useState(() => (demo ? DEMO_DEFAULTS.product : ""));
  const [req, setReq] = useState("");
  const [length, setLength] = useState(20);
  const [res, setRes] = useState<(typeof RESOLUTIONS)[number]>("480p");
  const [captions, setCaptions] = useState<(typeof CAPTION_MODES)[number]>("full");
  const [videoModel, setVideoModel] = useState<(typeof VIDEO_MODELS)[number]>("seedance-2.5");
  const [imageModel, setImageModel] = useState<(typeof IMAGE_MODELS)[number]>("seedream-5.0-pro");
  const [budget, setBudget] = useState({ seedream: NO_CAP, seedance: NO_CAP, evaluator: 3 });
  const [refs, setRefs] = useState<Array<Reference & { pending?: boolean; error?: string; localName: string }>>([]);
  const [autoApprove, setAutoApprove] = useState(false);
  const [stepApprove, setStepApprove] = useState(false);
  const [sampleCheck, setSampleCheck] = useState<{ state: "idle" | "checking" | "done"; result?: ValidateResult }>({ state: "idle" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [sampleMode, setSampleMode] = useState<"upload" | "link">(demo ? "link" : "upload");
  const [sampleFile, setSampleFile] = useState<{ state: "idle" | "uploading" | "done" | "error"; name?: string; size?: number; ref?: Reference; error?: string }>({ state: "idle" });
  const uploadSample = async (f: File) => {
    setSampleFile({ state: "uploading", name: f.name, size: f.size });
    try {
      const up = await api.uploadReference(f, "sample video");
      setSampleFile({ state: "done", name: f.name, size: f.size, ref: up });
    } catch (err) {
      setSampleFile({ state: "error", name: f.name, size: f.size, error: err instanceof Error ? err.message : String(err) });
    }
  };

  const validateSample = useCallback(async (url: string) => {
    if (!url.trim()) { setSampleCheck({ state: "idle" }); return; }
    setSampleCheck({ state: "checking" });
    try {
      const r = await api.validateSample(url.trim());
      setSampleCheck({ state: "done", result: r });
    } catch (e) {
      setSampleCheck({ state: "done", result: { ok: false, reason: e instanceof ApiError && e.status === 0 ? s.app.backendDown : String(e), content_type: null, size_bytes: null } });
    }
  }, [s.app.backendDown]);

  const addChip = (text: string) => setReq((r) => (r.trim() ? `${r.replace(/\s+$/, "")}\n${text}` : text));

  const validate = () => {
    const e: Record<string, string> = {};
    if (sampleMode === "upload") {
      if (sampleFile.state !== "done") e.sample = sampleFile.state === "uploading" ? s.newJob.sample.uploading : s.newJob.errors.sampleRequired;
    } else if (!sample.trim()) e.sample = s.newJob.errors.sampleRequired;
    else if (sampleCheck.state === "done" && sampleCheck.result && !sampleCheck.result.ok && !demo) e.sample = sampleCheck.result.reason ?? "";
    if (!product.trim()) e.product = s.newJob.errors.productRequired;
    else if (!/^https:\/\//i.test(product.trim())) e.product = s.newJob.errors.productHttps;
    if (req.trim().length < 12 && !demo) e.req = s.newJob.errors.requirementsShort;
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const onReview = (ev: React.FormEvent) => {
    ev.preventDefault();
    if (validate()) setConfirm(true);
  };

  const start = async () => {
    setSubmitting(true);
    setSubmitError(null);
    if (demo) {
      router.push(`/job?id=${DEMO_JOB_ID}&replay=1&speed=24`);
      return;
    }
    try {
      const job = await api.createJob({
        title: title.trim() || undefined, product_url: product.trim(), requirements: req.trim(),
        sample_url: sampleMode === "link" ? sample.trim() : "",
        sample_upload: sampleMode === "upload" && sampleFile.ref ? { file_id: sampleFile.ref.file_id, filename: sampleFile.ref.filename, local_name: sampleFile.ref.local_name } : null,
        budget, options: { length_s: length, resolution: res, captions, video_model: videoModel, image_model: imageModel }, auto_approve: autoApprove, step_approve: stepApprove,
        references: refs.filter((r) => !r.pending && !r.error).map(({ file_id, filename, mount_name, note }) => ({ file_id, filename, mount_name, note })),
      });
      router.push(`/job?id=${job.id}`);
    } catch (e) {
      setSubmitError(e instanceof ApiError && e.status !== 0 ? e.message : s.newJob.errors.generic);
      setSubmitting(false);
      setConfirm(false);
    }
  };

  const sampleState = sampleCheck.state === "done" ? sampleCheck.result : undefined;

  return (
    <form onSubmit={onReview} className="mx-auto max-w-3xl space-y-8" noValidate>
      <header>
        <h1 className="font-display text-4xl font-medium tracking-tight sm:text-5xl">{s.newJob.title}</h1>
        <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-muted-foreground">{s.newJob.subtitle}</p>
        {demo && (
          <p className="mt-4 flex items-start gap-2 rounded-2xl bg-brand-soft px-4 py-3 text-sm" role="status">
            <Sparkles className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />{s.newJob.demoBanner}
          </p>
        )}
      </header>

      <Section title={s.newJob.sections.inputs}>
        <Field label={s.newJob.sample.label} help={s.newJob.sample.help} error={errors.sample} id="sample">
          <div role="tablist" aria-label={s.newJob.sample.label} className="mb-2 inline-flex rounded-full bg-muted p-1 text-sm">
            {(["upload", "link"] as const).map((m) => (
              <button key={m} type="button" role="tab" aria-selected={sampleMode === m} onClick={() => setSampleMode(m)}
                className={cn("rounded-full px-3 py-1 font-semibold transition-colors", sampleMode === m ? "bg-card shadow-soft" : "text-muted-foreground hover:text-foreground")}>
                {m === "upload" ? s.newJob.sample.modeUpload : s.newJob.sample.modeLink}
              </button>
            ))}
          </div>
          {sampleMode === "upload" ? (
            <label className={cn("flex cursor-pointer items-center gap-3 rounded-xl border border-dashed px-4 py-4 transition-colors hover:bg-foreground/5",
              sampleFile.state === "error" ? "border-danger" : "border-foreground/20")}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) void uploadSample(f); }}>
              {sampleFile.state === "uploading" ? <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden />
                : sampleFile.state === "done" ? <CheckCircle2 className="size-5 text-success" aria-hidden />
                : sampleFile.state === "error" ? <CircleAlert className="size-5 text-danger" aria-hidden />
                : <Upload className="size-5 text-muted-foreground" aria-hidden />}
              <span className="min-w-0 flex-1 text-sm">
                {sampleFile.state === "idle" && (<><span className="block font-semibold">{s.newJob.sample.drop}</span><span className="block text-xs text-muted-foreground">{s.newJob.sample.dropHint}</span></>)}
                {sampleFile.state === "uploading" && <span className="block">{s.newJob.sample.uploading} {sampleFile.name}…</span>}
                {sampleFile.state === "done" && (<><span className="flex items-center gap-1.5 font-semibold"><FileVideo className="size-4" aria-hidden />{s.newJob.sample.uploaded(sampleFile.name ?? "", fmtBytes(sampleFile.size ?? null))}</span><span className="block text-xs text-muted-foreground">{s.newJob.sample.replace}</span></>)}
                {sampleFile.state === "error" && <span className="block text-danger">{sampleFile.error}</span>}
              </span>
              <input id="sample" type="file" accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.m4v,.webm" className="sr-only"
                onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void uploadSample(f); }} />
            </label>
          ) : (
            <>
          <div className="relative">
              <Input
                id="sample"
                type="url"
                inputMode="url"
                autoComplete="off"
                placeholder={s.newJob.sample.placeholder}
                value={sample}
                onChange={(e) => { setSample(e.target.value); setSampleCheck({ state: "idle" }); }}
                onBlur={() => void validateSample(sample)}
                aria-invalid={!!errors.sample || (sampleState ? !sampleState.ok : undefined)}
                aria-describedby="sample-help sample-status"
                className="h-11 rounded-xl pr-10 text-base"
              />
              <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
                {sampleCheck.state === "checking" && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-hidden />}
                {sampleState?.ok && <CheckCircle2 className="size-4 text-success" aria-hidden />}
                {sampleState && !sampleState.ok && <CircleAlert className="size-4 text-danger" aria-hidden />}
              </span>
            </div>
            <p id="sample-status" className={cn("mt-1.5 text-sm empty:hidden", sampleState?.ok ? "text-success" : "text-danger")} aria-live="polite">
              {sampleCheck.state === "checking" && <span className="text-muted-foreground">{s.newJob.sample.checking}</span>}
              {sampleState?.ok && s.newJob.sample.ok(fmtBytes(sampleState.size_bytes))}
              {sampleState && !sampleState.ok && !errors.sample && sampleState.reason}
            </p>
            </>
          )}
        </Field>
        <Field label={s.newJob.product.label} help={s.newJob.product.help} error={errors.product} id="product">
          <Input id="product" type="url" inputMode="url" autoComplete="off" placeholder={s.newJob.product.placeholder} value={product} onChange={(e) => setProduct(e.target.value)} aria-invalid={!!errors.product} className="h-11 rounded-xl text-base" />
        </Field>
        <Field label={s.newJob.titleField.label} id="title">
          <Input id="title" placeholder={s.newJob.titleField.placeholder} value={title} onChange={(e) => setTitle(e.target.value)} className="h-11 rounded-xl text-base" maxLength={80} />
        </Field>
      </Section>

      <Section title={s.newJob.sections.brief}>
        <Field label={s.newJob.requirements.label} help={s.newJob.requirements.help} error={errors.req} id="req">
          <div className="mb-2 flex flex-wrap gap-1.5" role="group" aria-label={s.newJob.requirements.help}>
            {Object.values(s.newJob.requirements.chips).map((c) => (
              <button key={c.label} type="button" onClick={() => addChip(c.text)} className="rounded-full bg-muted px-3 py-1 text-xs font-semibold text-foreground outline-none transition-colors hover:bg-brand-soft focus-visible:ring-3 focus-visible:ring-ring/50">
                {c.label}
              </button>
            ))}
          </div>
          <Textarea id="req" rows={6} placeholder={s.newJob.requirements.placeholder} value={req} onChange={(e) => setReq(e.target.value)} aria-invalid={!!errors.req} className="min-h-36 rounded-xl text-base leading-relaxed" />
        </Field>
      </Section>

      <Section title={s.newJob.sections.output}>
        <div className="grid gap-6 sm:grid-cols-2">
          <Segmented label={s.newJob.length.label} options={LENGTHS.map((l) => ({ v: String(l), l: `${l} ${s.newJob.length.unit}` }))} value={String(length)} onChange={(v) => setLength(Number(v))} />
          <Segmented label={s.newJob.resolution.label} options={RESOLUTIONS.map((r) => ({ v: r, l: r }))} value={res} onChange={(v) => setRes(v as (typeof RESOLUTIONS)[number])} />
        </div>
        <div className="mt-6">
          <Segmented label={s.newJob.captions.label} options={CAPTION_MODES.map((m) => ({ v: m, l: s.newJob.captions[m] }))} value={captions} onChange={(v) => setCaptions(v as (typeof CAPTION_MODES)[number])} />
          <p className="mt-2 text-xs text-muted-foreground">{s.newJob.captions.help}</p>
        </div>
        <div className="mt-6 grid gap-6 sm:grid-cols-2">
          <Segmented label={s.newJob.models.video} options={VIDEO_MODELS.map((m) => ({ v: m, l: s.newJob.models.names[m] }))} value={videoModel} onChange={(v) => setVideoModel(v as (typeof VIDEO_MODELS)[number])} />
          <Segmented label={s.newJob.models.image} options={IMAGE_MODELS.map((m) => ({ v: m, l: s.newJob.models.names[m] }))} value={imageModel} onChange={(v) => setImageModel(v as (typeof IMAGE_MODELS)[number])} />
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{s.newJob.models.help}</p>
      </Section>

      <Section title={s.newJob.references.label}>
        <p className="text-sm text-muted-foreground">{s.newJob.references.help}</p>
        <div className="mt-3 space-y-2">
          {refs.map((r, i) => (
            <div key={r.localName + i} className="flex flex-wrap items-center gap-2 rounded-xl bg-muted px-3 py-2 text-sm">
              <Paperclip className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1 truncate font-medium">{r.localName}</span>
              {r.pending ? <span className="text-xs text-muted-foreground"><Loader2 className="inline size-3 animate-spin" /> {s.newJob.references.uploading}</span> : r.error ? <span className="text-xs text-danger">{s.newJob.references.failed}: {r.error}</span> : null}
              <Input value={r.note ?? ""} onChange={(e) => setRefs((xs) => xs.map((x, j) => (j === i ? { ...x, note: e.target.value } : x)))} placeholder={s.newJob.references.notePlaceholder} className="h-9 w-full rounded-lg text-sm sm:w-64" aria-label={s.newJob.references.notePlaceholder} />
              <button type="button" className="rounded-full p-1 text-muted-foreground hover:bg-foreground/10" aria-label={s.newJob.references.remove} onClick={() => setRefs((xs) => xs.filter((_, j) => j !== i))}><X className="size-4" /></button>
            </div>
          ))}
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-foreground/15 px-4 py-2 text-sm font-semibold hover:bg-foreground/5">
            <Paperclip className="size-4" aria-hidden />{s.newJob.references.add}
            <input type="file" accept="image/*,video/*,audio/*" multiple className="sr-only" onChange={async (e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = "";
              for (const f of files) {
                const localName = f.name;
                setRefs((xs) => [...xs, { file_id: "", filename: f.name, localName, pending: true, note: "" }]);
                try {
                  const up = await api.uploadReference(f, "");
                  setRefs((xs) => xs.map((x) => (x.localName === localName && x.pending ? { ...up, localName, note: x.note } : x)));
                } catch (err) {
                  setRefs((xs) => xs.map((x) => (x.localName === localName && x.pending ? { ...x, pending: false, error: err instanceof Error ? err.message : "error" } : x)));
                }
              }
            }} />
          </label>
        </div>
      </Section>

      <Section title={s.newJob.sections.budget}>
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2">
            {(["seedream", "seedance"] as const).map((k) => (
              <div key={k} className="rounded-xl bg-muted px-4 py-3">
                <span className="block text-sm font-semibold">{s.newJob.budget[k]}</span>
                <span className="block font-display text-xl">{s.newJob.budget.noCap}</span>
                <span className="block text-xs text-muted-foreground">{s.newJob.budget.noCapHint}</span>
              </div>
            ))}
          </div>
          <div>
            <div className="mb-2 flex items-center justify-between">
              <Label htmlFor="budget-evaluator" className="text-sm font-semibold">{s.newJob.budget.evaluator}</Label>
              <span className="w-8 text-right text-sm font-semibold tabular-nums">{budget.evaluator}</span>
            </div>
            <Slider
              id="budget-evaluator"
              aria-label={s.newJob.budget.evaluator}
              min={1}
              max={SLIDER_MAX.evaluator}
              step={1}
              value={[budget.evaluator]}
              onValueChange={(v) => setBudget((b) => ({ ...b, evaluator: Array.isArray(v) ? v[0] : (v as number) }))}
              className="[&_[data-slot=slider-range]]:bg-brand [&_[data-slot=slider-thumb]]:size-4 [&_[data-slot=slider-thumb]]:border-brand [&_[data-slot=slider-track]]:h-1.5"
            />
          </div>
          <label className="flex items-center gap-3">
            <Switch checked={stepApprove} onCheckedChange={(v) => setStepApprove(!!v)} aria-label={s.newJob.budget.stepApprove} />
            <span>
              <span className="block text-sm font-semibold">{s.newJob.budget.stepApprove}</span>
              <span className="block text-xs text-muted-foreground">{s.newJob.budget.stepApproveHint}</span>
            </span>
          </label>
          <label className="flex items-center gap-3">
            <Switch checked={autoApprove} onCheckedChange={(v) => setAutoApprove(!!v)} aria-label={s.newJob.budget.autoApprove} />
            <span>
              <span className="block text-sm font-semibold">{s.newJob.budget.autoApprove}</span>
              <span className="block text-xs text-muted-foreground">{s.newJob.budget.autoApproveHint}</span>
            </span>
          </label>
        </div>
      </Section>

      {submitError && <p role="alert" className="rounded-2xl bg-danger-soft p-4 text-sm">{submitError}</p>}

      <div className="flex flex-col-reverse items-stretch gap-3 sm:flex-row sm:items-center sm:justify-end">
        <Button variant="ghost" className="h-12 rounded-full px-5 text-base" nativeButton={false} render={<Link href="/" />}>{s.newJob.confirm.cancel}</Button>
        <Button type="submit" size="lg" className="h-12 rounded-full bg-brand px-6 text-base text-brand-foreground shadow-soft hover:bg-brand/90" disabled={submitting}>
          {submitting ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
          {submitting ? s.newJob.submitting : s.newJob.submit}
        </Button>
      </div>

      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent className="rounded-2xl p-6 sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl">{s.newJob.confirm.title}</DialogTitle>
            <DialogDescription className="text-sm leading-relaxed">{autoApprove ? s.newJob.confirm.bodyAuto : s.newJob.confirm.body}</DialogDescription>
          </DialogHeader>
          <dl className="grid grid-cols-3 gap-3 text-center">
            {(["seedream", "seedance", "evaluator"] as const).map((k) => (
              <div key={k} className="rounded-xl bg-muted p-3">
                <dt className="text-xs text-muted-foreground">{s.newJob.budget[k]}</dt>
                <dd className="font-display text-2xl font-medium">{budget[k]}</dd>
              </div>
            ))}
          </dl>
          <p className="text-sm text-muted-foreground">{length} {s.newJob.length.unit} · {res}</p>
          <DialogFooter className="mt-2 px-6 pb-6">
            <Button variant="outline" className="rounded-full" onClick={() => setConfirm(false)} disabled={submitting}>{s.newJob.confirm.cancel}</Button>
            <Button className="rounded-full bg-brand text-brand-foreground hover:bg-brand/90" onClick={start} disabled={submitting} autoFocus>
              {submitting && <Loader2 className="size-4 animate-spin" />}
              {demo ? s.newJob.confirm.demoStart : s.newJob.confirm.start}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </form>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-3xl bg-card p-5 shadow-soft ring-1 ring-foreground/8 sm:p-7">
      <h2 className="mb-5 font-display text-xl font-medium">{title}</h2>
      <div className="space-y-5">{children}</div>
    </section>
  );
}

function Field({ label, help, error, id, children }: { label: string; help?: string; error?: string; id: string; children: React.ReactNode }) {
  return (
    <div>
      <Label htmlFor={id} className="mb-1.5 text-sm font-semibold">{label}</Label>
      {children}
      {help && !error && <p id={`${id}-help`} className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{help}</p>}
      {error && <p className="mt-1.5 text-sm text-danger" role="alert">{error}</p>}
    </div>
  );
}

function Segmented({ label, options, value, onChange }: { label: string; options: { v: string; l: string }[]; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <span className="mb-1.5 block text-sm font-semibold">{label}</span>
      <div role="radiogroup" aria-label={label} className="inline-flex rounded-xl bg-muted p-1">
        {options.map((o) => (
          <button
            key={o.v}
            type="button"
            role="radio"
            aria-checked={value === o.v}
            onClick={() => onChange(o.v)}
            className={cn("h-9 rounded-lg px-4 text-sm font-semibold outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50", value === o.v ? "bg-card text-foreground shadow-soft" : "text-muted-foreground hover:text-foreground")}
          >
            {o.l}
          </button>
        ))}
      </div>
    </div>
  );
}
