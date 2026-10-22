import { CheckCircle2, ChevronDown, CircleAlert } from "lucide-react";
import type { JobError } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { t } from "@/i18n";

/** Open problems in a red panel; problems the run already recovered from in a small collapsed note. */
export function ErrorList({ errors }: { errors: JobError[] }) {
  const s = t();
  const open = errors.filter((e) => !e.resolved);
  const resolved = errors.filter((e) => e.resolved);
  if (!errors.length) return null;
  return (
    <div className="space-y-3">
      {open.length > 0 && (
        <section aria-labelledby="errors-heading" className="rounded-2xl bg-danger-soft p-5 ring-1 ring-danger/25">
          <h3 id="errors-heading" className="flex items-center gap-2 text-sm font-semibold">
            <CircleAlert className="size-4 text-danger" aria-hidden />
            {s.live.errorsTitle}
          </h3>
          <ul className="mt-3 space-y-3">
            {open.map((e, i) => (
              <li key={i} className="rounded-xl bg-card/70 p-3 text-sm">
                <p className="font-semibold">{e.title}{e.at ? <span className="ml-2 font-normal text-muted-foreground">{fmtTime(e.at)}</span> : null}</p>
                <p className="mt-1">{e.text}</p>
                <p className="mt-2 text-muted-foreground"><span className="font-medium text-foreground">{s.live.whatNext}:</span> {e.next}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
      {resolved.length > 0 && (
        <details className="group rounded-2xl bg-card px-4 py-3 text-sm ring-1 ring-foreground/8">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-muted-foreground">
            <CheckCircle2 className="size-4 text-success" aria-hidden />
            <span className="flex-1">{s.live.resolvedIssues(resolved.length)}</span>
            <ChevronDown className="size-4 transition-transform group-open:rotate-180" aria-hidden />
          </summary>
          <ul className="mt-3 space-y-2">
            {resolved.map((e, i) => (
              <li key={i} className="text-muted-foreground">
                <span className="font-medium text-foreground">{e.at ? fmtTime(e.at) : ""}</span> {e.text}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
