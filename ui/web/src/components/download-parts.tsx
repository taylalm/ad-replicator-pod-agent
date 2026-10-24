"use client";

import { Download, FileArchive } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, fileUrl } from "@/lib/api";
import { t } from "@/i18n";

type Part = { group: string; name: string; url: string };

/** Every piece of a finished ad, downloadable one by one or all together as a ZIP (for re-editing). */
export function DownloadParts({ jobId }: { jobId: string }) {
  const s = t();
  const [parts, setParts] = useState<Part[] | null>(null);
  useEffect(() => {
    let alive = true;
    api.parts(jobId).then((r) => { if (alive) setParts(r.parts); }).catch(() => { if (alive) setParts([]); });
    return () => { alive = false; };
  }, [jobId]);
  if (!parts || parts.length === 0) return null;
  const groups = Array.from(new Set(parts.map((p) => p.group)));
  return (
    <section aria-labelledby="parts" className="rounded-3xl bg-card p-5 ring-1 ring-foreground/8 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="parts" className="font-display text-2xl font-medium">{s.results.parts}</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{s.results.partsHint}</p>
        </div>
        <Button size="lg" className="rounded-full" nativeButton={false} render={<a href={fileUrl(`/api/jobs/${encodeURIComponent(jobId)}/bundle.zip`)} download />}>
          <FileArchive className="size-4" />
          {s.results.partsAll}
        </Button>
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {groups.map((g) => (
          <div key={g}>
            <h3 className="mb-1.5 text-sm font-semibold">{s.results.partGroups[g] ?? g}</h3>
            <ul className="space-y-1">
              {parts.filter((p) => p.group === g).map((p) => (
                <li key={p.name}>
                  <a href={fileUrl(p.url)} download={p.name} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
                    <Download className="size-3.5" aria-hidden />
                    {p.name}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
