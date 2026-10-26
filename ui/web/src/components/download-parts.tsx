"use client";

import { FileArchive } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, fileUrl } from "@/lib/api";
import { t } from "@/i18n";

type Part = { group: string; name: string; url: string };

/** Bottom of the results page: one ZIP with every piece, and the list of exactly what is inside it. */
export function DownloadAll({ jobId }: { jobId: string }) {
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
    <section aria-labelledby="download-all" className="rounded-3xl bg-card p-5 ring-1 ring-foreground/8 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="download-all" className="font-display text-2xl font-medium">{s.results.partsAll}</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{s.results.zipContains(parts.length)}</p>
        </div>
        <Button size="lg" className="rounded-full" nativeButton={false} render={<a href={fileUrl(`/api/jobs/${encodeURIComponent(jobId)}/bundle.zip`)} download />}>
          <FileArchive className="size-4" />
          {s.results.partsAllButton}
        </Button>
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {groups.map((g) => (
          <div key={g} className="min-w-0">
            <h3 className="mb-1 text-sm font-semibold">{s.results.partGroups[g] ?? g} <span className="font-normal text-muted-foreground">· {g}/</span></h3>
            <ul className="space-y-0.5 text-sm text-muted-foreground">
              {parts.filter((p) => p.group === g).map((p) => <li key={p.name} className="truncate" title={p.name}>{p.name}</li>)}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
