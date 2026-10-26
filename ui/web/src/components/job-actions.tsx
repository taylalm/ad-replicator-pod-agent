"use client";

import { useState } from "react";
import { Check, Pencil, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { t } from "@/i18n";

/** Delete a job everywhere (agent session + this site), with a confirm step on the page. */
export function DeleteJob({ id, onDeleted, compact = false }: { id: string; onDeleted: () => void; compact?: boolean }) {
  const s = t();
  const [stage, setStage] = useState<"idle" | "confirm" | "busy">("idle");
  const [error, setError] = useState<string | null>(null);
  async function remove() {
    setStage("busy");
    setError(null);
    try {
      await api.deleteJob(id);
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStage("confirm");
    }
  }
  if (stage === "idle") {
    return (
      <Button variant="ghost" size="sm" className="text-muted-foreground hover:text-destructive" onClick={() => setStage("confirm")}
        aria-label={s.common.delete}>
        <Trash2 className="size-3.5" aria-hidden />{!compact && s.common.delete}
      </Button>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2 text-sm" role="group" aria-label={s.common.deleteConfirm}>
      <span className="text-foreground">{s.common.deleteConfirm}</span>
      <Button variant="destructive" size="sm" disabled={stage === "busy"} onClick={remove}>
        {stage === "busy" ? s.common.deleting : s.common.deleteYes}
      </Button>
      <Button variant="outline" size="sm" disabled={stage === "busy"} onClick={() => setStage("idle")}>{s.common.cancel}</Button>
      {error && <span className="w-full text-destructive">{error}</span>}
    </span>
  );
}

/** A title with a pencil button that turns into an input; Enter or the tick saves, Escape cancels. */
export function EditableTitle({ id, title, onRenamed, className, as: Tag = "span" }: {
  id: string; title: string; onRenamed: (title: string) => void; className?: string; as?: "span" | "h1" | "h3";
}) {
  const s = t();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(title);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save() {
    const next = value.split(/\s+/).join(" ").trim();
    if (!next || next === title) {
      setEditing(false);
      setValue(title);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.renameJob(id, next);
      onRenamed(r.title);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  if (!editing) {
    return (
      <span className="relative z-10 inline-flex items-center gap-1.5">
        <Tag className={className}>{title}</Tag>
        <button type="button" onClick={() => { setValue(title); setEditing(true); }} aria-label={s.common.rename}
          className="rounded-md p-1 text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
          <Pencil className="size-3.5" aria-hidden />
        </button>
      </span>
    );
  }
  return (
    <span className="relative z-10 inline-flex w-full max-w-xl flex-wrap items-center gap-1.5">
      <input autoFocus onFocus={e => e.currentTarget.select()} value={value} maxLength={120} disabled={busy} aria-label={s.common.rename}
        onChange={e => setValue(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter") save(); if (e.key === "Escape") { setEditing(false); setValue(title); } }}
        className="min-w-0 flex-1 rounded-lg border border-input bg-background px-2.5 py-1.5 text-base outline-none focus-visible:ring-3 focus-visible:ring-ring/50" />
      <Button size="sm" variant="outline" onClick={save} disabled={busy} aria-label={s.common.save}><Check className="size-3.5" aria-hidden /></Button>
      <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setValue(title); }} disabled={busy} aria-label={s.common.cancel}><X className="size-3.5" aria-hidden /></Button>
      {error && <span className="w-full text-sm text-destructive">{error}</span>}
    </span>
  );
}
