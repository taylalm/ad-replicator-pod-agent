"use client";

import { Download } from "lucide-react";
import { fileUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

/** A small download link for one file of the job (served by this site, so the browser saves it). */
export function DownloadButton({ url, name, label, className }: { url: string | null | undefined; name?: string; label?: string; className?: string }) {
  if (!url) return null;
  const file = name ?? url.split("/").pop() ?? "file";
  return (
    <a href={fileUrl(url)} download={file} title={file}
      className={cn("inline-flex h-7 max-w-full items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold text-muted-foreground ring-1 ring-foreground/12 outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50", className)}>
      <Download className="size-3.5 shrink-0" aria-hidden />
      <span className="truncate">{label ?? file}</span>
    </a>
  );
}
