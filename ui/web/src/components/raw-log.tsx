"use client";

import { ChevronDown, Terminal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { RawEvent } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";

const KEY_TYPES = new Set(["user.message", "agent.message", "agent.tool_use", "agent.tool_result", "session.error", "session.status_idle", "session.status_running"]);

export function RawLog({ events, defaultOpen = false }: { events: RawEvent[]; defaultOpen?: boolean }) {
  const s = t();
  const [open, setOpen] = useState(defaultOpen);
  const [all, setAll] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const shown = all ? events : events.filter((e) => KEY_TYPES.has(e.type));

  useEffect(() => {
    if (open) bottom.current?.scrollIntoView({ block: "nearest" });
  }, [shown.length, open]);

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-2xl bg-card ring-1 ring-foreground/8">
      <CollapsibleTrigger className="flex w-full items-center gap-3 rounded-2xl px-5 py-4 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
        <Terminal className="size-4 text-muted-foreground" aria-hidden />
        <span className="flex-1">
          <span className="block text-sm font-semibold">{s.live.rawLog}</span>
          <span className="block text-xs text-muted-foreground">{s.live.rawLogHint} · {events.length}</span>
        </span>
        <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="border-t border-border px-5 py-3">
          <div className="mb-2 flex gap-1 text-xs" role="group" aria-label="Filter">
            {[{ v: false, l: s.events.filterKey }, { v: true, l: s.events.filterAll }].map((o) => (
              <button
                key={String(o.v)}
                type="button"
                onClick={() => setAll(o.v)}
                aria-pressed={all === o.v}
                className={cn("rounded-full px-2.5 py-1 font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50", all === o.v ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:text-foreground")}
              >
                {o.l}
              </button>
            ))}
          </div>
          <ol className="max-h-[28rem] space-y-1 overflow-y-auto scrollbar-thin font-mono text-[12px] leading-relaxed">
            {shown.length === 0 && <li className="text-muted-foreground">{s.events.empty}</li>}
            {shown.map((e) => (
              <li key={e.id} className="grid grid-cols-[64px_96px_1fr] gap-2 rounded-md px-1 py-0.5 hover:bg-muted/60">
                <span className="text-muted-foreground tabular-nums">{fmtTime(e.processed_at)}</span>
                <span className={cn("truncate font-semibold", e.type === "session.error" || e.is_error ? "text-danger" : e.type === "agent.message" ? "text-brand" : e.type === "user.message" ? "text-success" : "text-muted-foreground")}>
                  {s.events.types[e.type] ?? e.type}
                </span>
                <span className="min-w-0 whitespace-pre-wrap break-words">
                  {e.type === "agent.tool_use" ? `${e.name}: ${e.input_brief ?? ""}` : e.text ?? (e.stop_reason ? e.stop_reason.type : e.model_usage ? `in ${e.model_usage.input_tokens} · out ${e.model_usage.output_tokens}` : e.error ? JSON.stringify(e.error) : "")}
                </span>
              </li>
            ))}
            <div ref={bottom} />
          </ol>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
