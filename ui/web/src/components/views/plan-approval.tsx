"use client";

import { motion } from "framer-motion";
import { Check, Loader2, MessageSquareText, Users } from "lucide-react";
import { useState } from "react";
import { Markdown } from "@/components/markdown";
import { StepTimeline } from "@/components/step-timeline";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { fileUrl, type Job } from "@/lib/api";
import { t } from "@/i18n";

export function PlanApproval({ job, onSend, replay }: { job: Job; onSend: (text: string) => Promise<unknown>; replay: boolean }) {
  const s = t();
  const [mode, setMode] = useState<"idle" | "changes">("idle");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"approve" | "changes" | null>(null);
  const [sent, setSent] = useState(false);
  const plan = job.plan;
  const stepWait = job.awaiting_step && job.awaiting_step !== 3 ? job.steps.find((st) => st.n === job.awaiting_step) : null;
  const est = plan?.paid_call_estimate;
  const budget = job.paid_calls.budget;

  const send = async (msg: string, kind: "approve" | "changes") => {
    setBusy(kind);
    try {
      await onSend(msg);
      setSent(true);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-6">
        <section className="rounded-3xl bg-card p-5 shadow-soft ring-1 ring-foreground/8 sm:p-8">
          {job.plan_text ? <Markdown text={job.plan_text} /> : <p className="text-sm text-muted-foreground">{s.plan.noPlan}</p>}
        </section>

        {(job.keyframes.length > 0 || job.scene_frames.length > 0) && (
          <section aria-labelledby="keyframes">
            <h2 id="keyframes" className="mb-3 font-display text-xl font-medium">{s.plan.keyframes}</h2>
            <div className="grid grid-cols-3 gap-3 sm:grid-cols-6">
              {(job.scene_frames.length ? job.scene_frames.filter((u) => /_start\./.test(u)) : job.keyframes).slice(0, 6).map((u, i) => (
                <motion.div key={u} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} className="overflow-hidden rounded-xl bg-surface ring-1 ring-foreground/8 aspect-9-16">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={fileUrl(u)} alt={`Sample scene ${i + 1}`} className="size-full object-cover" loading="lazy" />
                </motion.div>
              ))}
            </div>
          </section>
        )}

        {plan && !job.plan_text && (
          <section className="grid gap-4 sm:grid-cols-2" aria-label="Plan details">
            {plan.cast && plan.cast.length > 0 && (
              <Card title={s.plan.people} icon={<Users className="size-4" aria-hidden />}>
                <ul className="space-y-2">
                  {plan.cast.map((c) => (
                    <li key={c.name} className="text-sm"><span className="font-semibold">{c.name}</span>{c.role ? ` · ${c.role}` : ""}{c.look ? <span className="block text-muted-foreground">{c.look}</span> : null}</li>
                  ))}
                </ul>
              </Card>
            )}
            {plan.product_options && (
              <Card title={s.plan.productOptions}>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                  {Object.entries(plan.product_options).map(([k, v]) => (
                    <div key={k} className="contents"><dt className="text-muted-foreground">{k}</dt><dd className="font-medium">{v}</dd></div>
                  ))}
                </dl>
              </Card>
            )}
            {plan.scenes && plan.scenes.length > 0 && (
              <Card title={s.plan.scenes} className="sm:col-span-2">
                <ol className="divide-y divide-border">
                  {plan.scenes.map((sc) => (
                    <li key={sc.index} className="grid grid-cols-[2rem_1fr_auto] gap-3 py-2 text-sm">
                      <span className="font-display text-lg text-muted-foreground">{sc.index}</span>
                      <span>
                        <span className="block">{sc.description}</span>
                        {sc.caption && <span className="mt-0.5 block text-muted-foreground">“{sc.caption}”</span>}
                      </span>
                      <span className="text-right tabular-nums text-muted-foreground">{sc.length_s != null ? `${sc.length_s} s` : ""}</span>
                    </li>
                  ))}
                </ol>
              </Card>
            )}
            {plan.captions && plan.captions.length > 0 && (
              <Card title={s.plan.captions}>
                <ul className="space-y-1.5 text-sm">{plan.captions.map((c) => <li key={c} className="rounded-lg bg-muted px-3 py-1.5">{c}</li>)}</ul>
              </Card>
            )}
            {plan.end_card && (
              <Card title={s.plan.endCard}>
                <p className="text-sm"><span className="font-semibold">{plan.end_card.product_name}</span></p>
                <p className="mt-1 text-sm text-brand">{plan.end_card.cta}</p>
                {plan.disclaimer && <p className="mt-2 text-xs text-muted-foreground">{plan.disclaimer}</p>}
              </Card>
            )}
          </section>
        )}
      </div>

      <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
        <div className="rounded-3xl bg-card p-5 shadow-soft ring-1 ring-foreground/8">
          <h2 className="font-display text-xl font-medium">{stepWait ? s.plan.stepDecision : s.plan.decision}</h2>
          {stepWait?.latest_message ? <p className="text-sm text-muted-foreground">{stepWait.latest_message}</p> : null}
          <p className="mt-1 text-sm text-muted-foreground">{s.plan.subtitle}</p>
          <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
            {(["seedream", "seedance", "evaluator"] as const).map((k) => (
              <div key={k} className="rounded-xl bg-muted p-2">
                <dt className="text-[11px] leading-tight text-muted-foreground">{s.newJob.budget[k]}</dt>
                <dd className="font-display text-xl font-medium tabular-nums">{est?.[k] ?? "–"}<span className="text-xs text-muted-foreground"> / {budget[k]}</span></dd>
              </div>
            ))}
          </dl>
          <p className="mt-1 text-center text-[11px] text-muted-foreground">{s.plan.estimate}</p>
          {sent ? (
            <p role="status" className="mt-4 flex items-center gap-2 rounded-xl bg-success-soft px-3 py-2 text-sm"><Check className="size-4 text-success" aria-hidden />{s.plan.sent}</p>
          ) : mode === "idle" ? (
            <div className="mt-4 flex flex-col gap-2">
              <Button size="lg" className="h-11 rounded-full bg-brand text-base text-brand-foreground hover:bg-brand/90" onClick={() => send("APPROVE", "approve")} disabled={busy != null} data-testid="approve">
                {busy === "approve" ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
                {stepWait ? s.plan.approveStep : s.plan.approve}
              </Button>
              <Button variant="outline" size="lg" className="h-11 rounded-full" onClick={() => setMode("changes")} disabled={busy != null}>
                <MessageSquareText className="size-4" />{s.plan.requestChanges}
              </Button>
              {replay && <p className="text-center text-xs text-muted-foreground">{s.plan.replayApproveHint}</p>}
            </div>
          ) : (
            <div className="mt-4 space-y-2">
              <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={s.plan.changesPlaceholder} rows={4} className="rounded-xl" aria-label={s.plan.requestChanges} autoFocus />
              <div className="flex gap-2">
                <Button className="rounded-full bg-brand text-brand-foreground hover:bg-brand/90" onClick={() => send(`CHANGES: ${text.trim()}`, "changes")} disabled={!text.trim() || busy != null}>
                  {busy === "changes" ? <Loader2 className="size-4 animate-spin" /> : null}{s.plan.sendChanges}
                </Button>
                <Button variant="ghost" className="rounded-full" onClick={() => setMode("idle")}>{s.plan.cancel}</Button>
              </div>
            </div>
          )}
        </div>
        <div className="rounded-3xl bg-card p-5 ring-1 ring-foreground/8">
          <StepTimeline steps={job.steps} currentStep={job.current_step} compact />
        </div>
      </aside>
    </div>
  );
}

function Card({ title, icon, children, className }: { title: string; icon?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-2xl bg-card p-5 ring-1 ring-foreground/8 ${className ?? ""}`}>
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-muted-foreground">{icon}{title}</h3>
      {children}
    </div>
  );
}
