export function fmtDuration(s: number | null | undefined): string {
  if (s == null || !isFinite(s)) return "";
  const n = Math.max(0, Math.round(s));
  if (n < 60) return `${n}s`;
  const m = Math.floor(n / 60);
  const r = n % 60;
  if (m < 60) return r ? `${m}m ${r}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export function fmtClock(s: number): string {
  if (!isFinite(s)) return "0:00";
  const n = Math.floor(s);
  return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;
}

export function fmtBytes(b: number | null | undefined): string {
  if (b == null) return "";
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MB`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(0)}k`;
  return String(n);
}

export function hostOf(url: string | null | undefined): string {
  if (!url) return "";
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}

/** Plain label for an output file name (file names stay in the raw log). */
export function fileLabel(name: string): string {
  const stem = name.replace(/\.[a-z0-9]+$/i, "");
  let m: RegExpMatchArray | null;
  if ((m = stem.match(/^contact_sheet_(\d+)$/))) return `Contact sheet ${Number(m[1])}`;
  if ((m = stem.match(/^scene_(\d+)_start$/))) return `Scene ${Number(m[1])}`;
  if ((m = stem.match(/^scene_(\d+)_(.+)$/))) return `Scene ${Number(m[1])} · ${m[2]}`;
  if (stem === "watermark_check") return "Watermark check";
  if ((m = stem.match(/^person_(.+)$/))) return cap(m[1]);
  if ((m = stem.match(/^product_(.+)$/))) return `${cap(m[1])}'s product`;
  if ((m = stem.match(/^artwork_(.+)$/))) return `${cap(m[1])}'s artwork`;
  if ((m = stem.match(/^clip_(\d+)$/))) return `Clip ${Number(m[1])}`;
  if ((m = stem.match(/^final_v(\d+)_frame_(\d+)$/))) return `Final v${m[1]} · frame ${Number(m[2])}`;
  if ((m = stem.match(/^final_v(\d+)$/))) return `Final cut v${m[1]}`;
  if (stem === "final") return "Final cut";
  if ((m = stem.match(/^quality_round_(\d+)_sheet_(\d+)$/))) return `Quality round ${m[1]} · sheet ${Number(m[2])}`;
  return name;
}

function cap(slug: string): string {
  return slug.split(/[_-]+/).filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
}

/** Strips markdown syntax for one-paragraph summaries. */
export function plainText(md: string): string {
  return md
    .split("\n")
    .filter((l) => !/^\s*\|/.test(l) && !/^\s*[-*_]{3,}\s*$/.test(l))
    .map((l) => l.replace(/^#+\s*/, "").replace(/^\s*[-*]\s+/, "").replace(/\*\*|__|`/g, "").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1"))
    .join(" ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** Keep only the newest version of files that share a base name (person_rosie.png, person_rosie_v2.png, clip_01_v4.mp4 ...).
 *  "Newest" is the most recently written file when times are known (agents differ: some put the current take in the plain
 *  name and archive old takes as _vN, others the reverse), otherwise the highest _vN. */
export function latestVersions<T extends { name: string; mtime?: number }>(files: T[]): T[] {
  const best = new Map<string, { v: number; t: number; file: T }>();
  for (const f of files) {
    const m = f.name.match(/^(.*?)(?:_v(\d+)(?:_[a-z0-9-]+)*)?(\.[a-z0-9]+)$/i);
    const base = m ? `${m[1]}${m[3]}`.toLowerCase() : f.name.toLowerCase();
    const v = m && m[2] ? Number(m[2]) : 0;
    const t = typeof f.mtime === "number" ? f.mtime : 0;
    const cur = best.get(base);
    // the plain name is the current take (older takes are renamed _vN); among versioned takes the newest wins
    const better = !cur || (v === 0 && cur.v !== 0) || (v !== 0 && cur.v !== 0 && (t && cur.t ? t > cur.t : v > cur.v));
    if (better) best.set(base, { v, t, file: f });
  }
  const keep = new Set([...best.values()].map((x) => x.file.name));
  return files.filter((f) => keep.has(f.name) && !/__[a-z0-9]{5}\.[a-z0-9]+$/i.test(f.name) && !/^cgt-/i.test(f.name));
}
