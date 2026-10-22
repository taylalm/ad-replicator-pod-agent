"use client";

import { motion } from "framer-motion";
import { FileJson, FileText, Play } from "lucide-react";
import { useState } from "react";
import { fileUrl, type JobFile } from "@/lib/api";
import { fileLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A 9:16 (video) or square (image) thumbnail card for a job output file. */
export function FileThumb({
  file, caption, aspect = "auto", className, onClick, index = 0,
}: { file: JobFile | { name: string; kind: JobFile["kind"]; local_url: string }; caption?: string; aspect?: "auto" | "portrait" | "square"; className?: string; onClick?: () => void; index?: number }) {
  const url = fileUrl(file.local_url);
  const portrait = aspect === "portrait" || (aspect === "auto" && file.kind === "video");
  const [hover, setHover] = useState(false);
  const Wrapper = onClick ? "button" : "div";
  return (
    <motion.div
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35, delay: Math.min(index, 8) * 0.04, ease: [0.22, 1, 0.36, 1] }}
      className={cn("group flex min-w-0 flex-col gap-1.5", className)}
    >
      <Wrapper
        onClick={onClick}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        onFocus={() => setHover(true)}
        onBlur={() => setHover(false)}
        className={cn(
          "relative block w-full overflow-hidden rounded-xl bg-surface ring-1 ring-foreground/8 shadow-soft outline-none",
          onClick && "cursor-pointer focus-visible:ring-3 focus-visible:ring-ring/50",
          portrait ? "aspect-9-16" : "aspect-square",
        )}
        {...(onClick ? { type: "button", "aria-label": caption ?? fileLabel(file.name) } : {})}
      >
        {file.kind === "image" && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt={caption ?? fileLabel(file.name)} className="size-full object-cover transition-transform duration-500 group-hover:scale-[1.02]" loading="lazy" />
        )}
        {file.kind === "video" && (
          <>
            <video
              src={`${url}#t=0.5`}
              muted
              playsInline
              preload="metadata"
              className="size-full object-cover"
              ref={(el) => {
                if (!el) return;
                if (hover) void el.play().catch(() => {});
                else { el.pause(); }
              }}
              loop
              aria-label={caption ?? fileLabel(file.name)}
            />
            <span className="pointer-events-none absolute inset-0 grid place-items-center bg-black/0 transition-colors group-hover:bg-black/10">
              <span className="grid size-10 place-items-center rounded-full bg-white/90 text-foreground shadow-soft">
                <Play className="ml-0.5 size-4" fill="currentColor" aria-hidden />
              </span>
            </span>
          </>
        )}
        {(file.kind === "json" || file.kind === "md" || file.kind === "other") && (
          <span className="grid size-full place-items-center text-muted-foreground">
            {file.kind === "json" ? <FileJson className="size-8" aria-hidden /> : <FileText className="size-8" aria-hidden />}
          </span>
        )}
      </Wrapper>
      {caption !== "" && (
        <span className="truncate text-xs text-muted-foreground" title={file.name}>{caption ?? fileLabel(file.name)}</span>
      )}
    </motion.div>
  );
}
