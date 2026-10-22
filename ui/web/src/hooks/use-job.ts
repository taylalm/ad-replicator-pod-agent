"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Job, type RawEvent } from "@/lib/api";

export interface ReplayOptions {
  /** replay a finished job: the backend releases events up to `t` seconds after the first event */
  enabled: boolean;
  /** replay clock speed; 0 freezes the clock at `startT` (used for screenshots) */
  speed: number;
  startT: number;
}

const LIVE_POLL_MS = 3000;
const IDLE_POLL_MS = 10000;
const REPLAY_TICK_MS = 500;
const ACTIVE: Job["status"][] = ["running", "queued"];

export function useJob(id: string, replay: ReplayOptions) {
  const [job, setJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<RawEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [replayT, setReplayT] = useState(replay.startT);
  const [replayPaused, setReplayPaused] = useState(false);
  const replayTRef = useRef(replay.startT);
  const jobRef = useRef<Job | null>(null);
  const eventsCursor = useRef(0);
  const inflight = useRef(false);

  const refresh = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    try {
      const t = replay.enabled ? replayTRef.current : null;
      const j = await api.job(id, t);
      jobRef.current = j;
      setJob(j);
      setError(null);
      // events: incremental for live, cursor reset if the replay cut shrank
      const ev = await api.events(id, replay.enabled ? 0 : eventsCursor.current, t);
      if (replay.enabled) {
        setEvents(ev.events);
      } else if (ev.events.length) {
        eventsCursor.current = ev.next;
        setEvents((prev) => [...prev, ...ev.events]);
      }
    } catch (e) {
      const msg = e instanceof ApiError ? (e.status === 0 ? "backend" : e.message) : String(e);
      setError(msg);
    } finally {
      inflight.current = false;
    }
  }, [id, replay.enabled]);

  // first load (the page remounts per job id, so no state reset is needed here)
  useEffect(() => {
    eventsCursor.current = 0;
    void refresh();
  }, [refresh]);

  // live polling
  useEffect(() => {
    if (replay.enabled) return;
    const tick = () => {
      const s = jobRef.current?.status;
      const ms = !s || ACTIVE.includes(s) ? LIVE_POLL_MS : IDLE_POLL_MS;
      timer = window.setTimeout(async () => { await refresh(); tick(); }, ms);
    };
    let timer = 0;
    tick();
    return () => window.clearTimeout(timer);
  }, [refresh, replay.enabled]);

  // replay clock
  useEffect(() => {
    if (!replay.enabled) return;
    const iv = window.setInterval(() => {
      const j = jobRef.current;
      const total = j?.replay?.total_s ?? Infinity;
      const blocked = replayPaused || replay.speed <= 0 || !j || j.awaiting_approval || j.status === "done" || j.status === "failed" || j.status === "stopped";
      if (!blocked && replayTRef.current < total + 2) {
        replayTRef.current = Math.min(total + 2, replayTRef.current + (REPLAY_TICK_MS / 1000) * replay.speed);
        setReplayT(replayTRef.current);
        void refresh();
      }
    }, REPLAY_TICK_MS);
    return () => window.clearInterval(iv);
  }, [replay.enabled, replay.speed, replayPaused, refresh]);

  /** Sends APPROVE / CHANGES / REVISION / free text; in replay mode it just advances the clock. */
  const send = useCallback(async (text: string) => {
    if (replay.enabled) {
      const j = jobRef.current;
      const approveAt = j?.replay?.approve_at_s;
      if (/^APPROVE/i.test(text) && approveAt != null) {
        replayTRef.current = approveAt + 1;
        setReplayT(replayTRef.current);
      } else if (/^(CHANGES|REVISION)/i.test(text) && j?.replay?.total_s != null) {
        // a recorded run has no alternative branch: restart the live part from the approval
        replayTRef.current = (approveAt ?? 0) + 1;
        setReplayT(replayTRef.current);
      }
      await refresh();
      return { ok: true, demo: true };
    }
    const r = await api.message(id, text);
    jobRef.current = jobRef.current ? { ...jobRef.current, status: "running", awaiting_approval: false } : null;
    setJob(jobRef.current);
    window.setTimeout(() => void refresh(), 800);
    return r;
  }, [id, replay.enabled, refresh]);

  const jumpTo = useCallback((t: number) => {
    replayTRef.current = t;
    setReplayT(t);
    void refresh();
  }, [refresh]);

  return { job, events, error, refresh, send, replayT, jumpTo, replayPaused, setReplayPaused };
}
