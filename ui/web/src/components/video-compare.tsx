"use client";

import { Camera, Download, Pause, Play, Volume2, VolumeX } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { fmtClock } from "@/lib/format";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";

/** Two 9:16 players (sample vs new ad) driven by one play/pause/scrub control. Muted by default (autoplay-safe). */
export function VideoCompare({ sampleSrc, finalSrc, downloadName }: { sampleSrc: string | null; finalSrc: string | null; downloadName?: string }) {
  const s = t();
  const a = useRef<HTMLVideoElement>(null);
  const b = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const syncing = useRef(false);

  const both = useCallback(() => [a.current, b.current].filter(Boolean) as HTMLVideoElement[], []);

  useEffect(() => {
    const vids = both();
    const lead = a.current;
    const onMeta = () => setDuration(Math.max(...vids.map((v) => v.duration || 0)));
    const onTime = () => { if (!syncing.current && lead) setTime(lead.currentTime); };
    const onEnd = () => { if (vids.every((v) => v.ended || v.paused)) setPlaying(false); };
    vids.forEach((v) => { v.addEventListener("loadedmetadata", onMeta); v.addEventListener("ended", onEnd); });
    lead?.addEventListener("timeupdate", onTime);
    onMeta();
    return () => {
      vids.forEach((v) => { v.removeEventListener("loadedmetadata", onMeta); v.removeEventListener("ended", onEnd); });
      lead?.removeEventListener("timeupdate", onTime);
    };
  }, [both, sampleSrc, finalSrc]);

  // Save the new ad's current frame as a full-resolution PNG (pause and scrub to the frame first).
  const saveFrame = useCallback(() => {
    const v = b.current;
    if (!v || !v.videoWidth) return;
    const c = document.createElement("canvas");
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    try {
      c.getContext("2d")?.drawImage(v, 0, 0);
      c.toBlob((blob) => {
        if (!blob) return;
        const a2 = document.createElement("a");
        a2.href = URL.createObjectURL(blob);
        a2.download = `frame_${v.currentTime.toFixed(2).replace(".", "_")}s.png`;
        a2.click();
        setTimeout(() => URL.revokeObjectURL(a2.href), 1000);
      }, "image/png");
    } catch {
      window.alert(s.results.saveFrameFailed);
    }
  }, [s]);

  const toggle = useCallback(async () => {
    const vids = both();
    if (playing) {
      vids.forEach((v) => v.pause());
      setPlaying(false);
    } else {
      if (vids.every((v) => v.ended)) vids.forEach((v) => { v.currentTime = 0; });
      // keep them aligned when starting
      const t0 = a.current?.currentTime ?? 0;
      vids.forEach((v) => { if (Math.abs(v.currentTime - t0) > 0.15) v.currentTime = t0; });
      await Promise.all(vids.map((v) => v.play().catch(() => {})));
      setPlaying(true);
    }
  }, [both, playing]);

  const seek = useCallback((v: number) => {
    syncing.current = true;
    both().forEach((el) => { el.currentTime = v; });
    setTime(v);
    window.setTimeout(() => { syncing.current = false; }, 50);
  }, [both]);

  // drift correction while playing
  useEffect(() => {
    if (!playing) return;
    const iv = window.setInterval(() => {
      const [x, y] = [a.current, b.current];
      if (x && y && !x.paused && !y.paused && Math.abs(x.currentTime - y.currentTime) > 0.25) y.currentTime = x.currentTime;
    }, 500);
    return () => window.clearInterval(iv);
  }, [playing]);

  useEffect(() => { both().forEach((v) => { v.muted = muted; }); }, [muted, both]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === " " || e.key === "k") { e.preventDefault(); void toggle(); }
    if (e.key === "ArrowLeft") seek(Math.max(0, time - 2));
    if (e.key === "ArrowRight") seek(Math.min(duration, time + 2));
  };

  return (
    <div className="rounded-2xl bg-card p-4 shadow-soft ring-1 ring-foreground/8 sm:p-6" onKeyDown={onKey} tabIndex={0} aria-label="Side-by-side player">
      <div className="grid grid-cols-2 gap-3 sm:gap-6">
        <Pane label={s.results.sample} src={sampleSrc} refEl={a} muted />
        <Pane label={s.results.newAd} src={finalSrc} refEl={b} muted highlight emptyText={s.results.noFinal} />
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button size="lg" onClick={toggle} aria-label={playing ? s.results.pause : s.results.play} className="rounded-full bg-brand px-4 text-brand-foreground hover:bg-brand/90">
          {playing ? <Pause className="size-4" fill="currentColor" /> : <Play className="size-4" fill="currentColor" />}
          {playing ? s.results.pause : s.results.play}
        </Button>
        <span className="w-12 text-sm tabular-nums text-muted-foreground">{fmtClock(time)}</span>
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.05}
          value={Math.min(time, duration || 0)}
          onChange={(e) => seek(parseFloat(e.target.value))}
          aria-label="Scrub both videos"
          className="range-brand h-1.5 min-w-32 flex-1 cursor-pointer rounded-full"
        />
        <span className="w-12 text-right text-sm tabular-nums text-muted-foreground">{fmtClock(duration)}</span>
        <Button variant="outline" size="icon-lg" aria-label={muted ? s.results.unmute : s.results.mute} onClick={() => setMuted((m) => !m)} className="rounded-full">
          {muted ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
        </Button>
        {finalSrc && (
          <Button variant="outline" size="lg" className="rounded-full" onClick={saveFrame} title={s.results.saveFrameHint}>
            <Camera className="size-4" />
            {s.results.saveFrame}
          </Button>
        )}
        {finalSrc && (
          <Button variant="outline" size="lg" className="rounded-full" nativeButton={false} render={<a href={finalSrc} download={downloadName ?? "final.mp4"} />}>
            <Download className="size-4" />
            {s.results.download}
          </Button>
        )}
      </div>
    </div>
  );
}

function Pane({ label, src, refEl, muted, highlight, emptyText }: { label: string; src: string | null; refEl: React.RefObject<HTMLVideoElement | null>; muted: boolean; highlight?: boolean; emptyText?: string }) {
  return (
    <figure className="min-w-0">
      <div className={cn("relative mx-auto aspect-9-16 w-full max-w-[320px] overflow-hidden rounded-xl bg-black ring-1 ring-foreground/10", highlight && "ring-2 ring-brand/60")}>
        {src ? (
          <video ref={refEl} src={src} muted={muted} playsInline preload="metadata" className="size-full object-contain" />
        ) : (
          <div className="grid size-full place-items-center px-4 text-center text-sm text-white/70">{emptyText}</div>
        )}
      </div>
      <figcaption className="mt-2 text-center text-sm font-medium">{label}</figcaption>
    </figure>
  );
}
