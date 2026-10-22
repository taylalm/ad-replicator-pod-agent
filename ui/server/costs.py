"""Production time and cost of one video, from the job's own records.

Time: for each workflow step, the agent's working time between the step's FIRST "started" and its FIRST "done" line,
counting only the periods the session was running (session.status_running -> status_idle). Waiting for a human
(approvals, reviews) and later regenerations/revisions are left out, so the number shows what one video takes.

Cost: unit prices from the official ModelArk pricing page (PRICES below, with the source and the date read).
- Seedance 2.5: the task's own usage.completion_tokens (GET /contents/generations/tasks/{id}, cached by sync.py in
  cost_cache.json) x the per-million-token price for its resolution; without that record, the page's estimate
  formula (duration x width x height x fps / 1024).
- Seedream 5.0 pro: per output image, tier by output pixels (<= 2.61 MP / above), size read from the paid-call note.
- Agent model and evaluator: tokens x per-million prices. The session's model_usage reports input_tokens INCLUDING the
  cached part (cache_read_input_tokens <= input_tokens, equal on fully cached requests), so uncached = input - cached.
  Evaluator calls have no usage record in the log: a fixed per-call estimate is used and labelled as such.
"first_pass" counts only the calls made inside the steps' first-pass windows; "total" counts everything the job spent.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PRICES = {
    "source": "https://ai.byteplus.com/ark/region:ap-southeast-1/docs/model-pricing (Online inference, USD), read 22 Oct 2026",
    "currency": "USD",
    # Seedance 2.5 (dreamina-seedance-2-5-260628), per million tokens, input without video
    "seedance_per_m": {"480p": 10.70, "720p": 10.70, "1080p": 11.7},
    # Seedance 2.5, input with a reference video
    "seedance_with_video_per_m": {"480p": 6.40, "720p": 6.40, "1080p": 7.0},
    # Seedream 5.0 pro (dola-seedream-5-0-pro-260628), per output image
    "seedream_image_small": 0.045,   # <= 2.61 million pixels ("1.5K or lower")
    "seedream_image_large": 0.09,    # > 2.61 million pixels
    "seedream_tier_pixels": 2_610_000,
    # GLM-5.3 Flash (glm-5-3-flash-260828), per million tokens
    "agent_input_per_m": 0.15, "agent_cached_per_m": 0.03, "agent_output_per_m": 0.5,
    # seed-2-0-lite-260428, prompt <= 128K, per million tokens; per call estimate for the evaluator (about 15K in / 1.5K out)
    "evaluator_input_per_m": 0.25, "evaluator_output_per_m": 2.00,
    "evaluator_call_estimate": round(15_000 * 0.25 / 1e6 + 1_500 * 2.00 / 1e6, 4),
}
SEEDANCE_DIMS = {"480p": (480, 864), "720p": (720, 1280), "1080p": (1080, 1920)}
STEP_RE = re.compile(r"STEP\s+(\d+)\s*/\s*(\d+)\s*:\s*([^\n]+?)\s+-\s+(started|done|failed|skipped)\b", re.I)


def _ts(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        s = re.sub(r"(\.\d{6})\d+", r"\1", s)  # nanoseconds -> microseconds
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _text(e: dict) -> str:
    c = e.get("content")
    if isinstance(c, list):
        return "".join(x.get("text", "") for x in c if isinstance(x, dict))
    return str(c or e.get("text") or "")


def running_intervals(events: List[dict]) -> List[Tuple[float, float]]:
    out, start = [], None
    for e in events:
        t = _ts(e.get("processed_at"))
        if t is None:
            continue
        if e.get("type") == "session.status_running" and start is None:
            start = t
        elif e.get("type") in ("session.status_idle", "session.status_terminated", "session.error") and start is not None:
            out.append((start, t))
            start = None
    if start is not None and events:
        last = _ts(events[-1].get("processed_at"))
        if last and last > start:
            out.append((start, last))
    return out


def first_pass_windows(events: List[dict]) -> Dict[int, Tuple[float, float]]:
    """Step -> (first started, first done). A step that never says started begins where the previous step ended."""
    started: Dict[int, float] = {}
    done: Dict[int, float] = {}
    order: List[Tuple[float, int, str]] = []
    for e in events:
        if e.get("type") != "agent.message":
            continue
        t = _ts(e.get("processed_at"))
        if t is None:
            continue
        for m in STEP_RE.finditer(_text(e)):
            n, kind = int(m.group(1)), m.group(4).lower()
            order.append((t, n, kind))
    first_t = _ts(events[0].get("processed_at")) if events else None
    last_done: Dict[int, float] = {}
    for t, n, kind in order:
        if kind == "started" and n not in started:
            started[n] = t
        if kind in ("done", "skipped") and n not in done:
            done[n] = t
        if kind in ("done", "skipped"):
            last_done[n] = t
    # rework = a human message that is not a plain approval (CHANGES:, REGENERATE:, REVISION:, ADD CLIP:, notes...)
    user_ts = sorted(t for t in (_ts(e.get("processed_at")) for e in events
                                 if e.get("type") == "user.message" and not re.match(r"\s*APPROVE\b", _text(e), re.I)) if t)
    windows = {}
    prev_end = first_t
    for n in sorted(done):
        s = started.get(n)
        if s is None or s > done[n]:
            s = prev_end if prev_end is not None and prev_end <= done[n] else done[n]
        # a human message during the step means rework from there on: the first pass ends at it
        cut = next((u for u in user_ts if s + 1 < u < done[n]), None)
        if cut is None:
            windows[n] = (s, done[n])
        else:
            # no uninterrupted first pass: use the last clean pass (from the last rework message to the step's final done)
            ld = last_done[n]
            ls = max([u for u in user_ts if u < ld] + [s])
            windows[n] = (ls, ld)
        prev_end = done[n]
    return windows


def _overlap(a: Tuple[float, float], spans: List[Tuple[float, float]]) -> float:
    return sum(max(0.0, min(a[1], b) - max(a[0], s)) for s, b in spans)


def production_time(events: List[dict]) -> Dict[str, Any]:
    spans = running_intervals(events)
    windows = first_pass_windows(events)
    steps = [{"n": n, "active_s": round(_overlap(w, spans))} for n, w in sorted(windows.items())]
    return {"active_s": sum(s["active_s"] for s in steps), "steps": steps, "windows": windows}


def _in_windows(t: Optional[float], windows: Dict[int, Tuple[float, float]]) -> bool:
    if t is None:
        return True  # no timestamp: count it (conservative)
    return any(s - 5 <= t <= d + 5 for s, d in windows.values())


def _seedream_price(note: str) -> float:
    m = re.search(r"(\d{3,4})\s*[x×]\s*(\d{3,4})", note)
    if m:
        px = int(m.group(1)) * int(m.group(2))
    elif re.search(r"\b2K\b|\b4K\b", note, re.I):
        px = 4_000_000
    else:
        px = 1_000_000  # 1K / 1.5K default
    return PRICES["seedream_image_large"] if px > PRICES["seedream_tier_pixels"] else PRICES["seedream_image_small"]


def _first_mention(events: List[dict], token: str) -> Optional[float]:
    for e in events:
        blob = _text(e) if e.get("content") is not None else ""
        if not blob and e.get("input"):
            blob = json.dumps(e["input"])[:20000]
        if token in blob:
            return _ts(e.get("processed_at"))
    return None


def delivered_clips(files_dir: Path) -> List[str]:
    """Unique video files used by the newest edit plan (the delivered cut)."""
    plans = sorted(files_dir.glob("edit_plan*.json"), key=lambda p: p.stat().st_mtime)
    if not plans:
        return []
    try:
        plan = json.loads(plans[-1].read_text())
    except (ValueError, OSError):
        return []
    out = []
    for c in plan.get("clips", []):
        name = Path(str(c.get("path") or "")).name
        if name and name not in out:
            out.append(name)
    return out


def compute(job_dir: Path, files_dir: Path, events: List[dict]) -> Dict[str, Any]:
    prod = production_time(events)
    windows = prod.pop("windows")
    cache_path = job_dir / "cost_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    paid_path = files_dir / "paid_calls.json"
    calls = []
    if paid_path.exists():
        try:
            d = json.loads(paid_path.read_text())
            calls = d if isinstance(d, list) else d.get("calls", [])
        except (ValueError, OSError):
            calls = []
    b = {k: {"first_pass": 0.0, "total": 0.0, "count_first": 0, "count_total": 0} for k in ("seedance", "seedream", "evaluator", "agent")}
    seedance_tokens = 0
    for c in calls:
        if not isinstance(c, dict) or str(c.get("status", "")).lower() not in ("succeeded", "success", "ok", "done"):
            continue  # failed or rejected submissions are not billed
        kind = str(c.get("kind", "")).lower()
        cid, note = str(c.get("id", "")), str(c.get("note", ""))
        if kind == "seedance":
            rec = cache.get(cid) or {}
            res = rec.get("resolution") or ("1080p" if "1080p" in note else "720p" if "720p" in note else "480p")
            tokens = (rec.get("usage") or {}).get("completion_tokens")
            if not tokens:
                dur = rec.get("duration") or (int(m.group(1)) if (m := re.search(r"(\d+)\s*s\b", note)) else 5)
                w, h = SEEDANCE_DIMS.get(res, (480, 864))
                tokens = dur * w * h * (rec.get("framespersecond") or 24) / 1024
            price = PRICES["seedance_per_m"].get(res, 10.70) * tokens / 1e6
            seedance_tokens += int(tokens)
            t = rec.get("created_at") or _first_mention(events, cid)
        elif kind == "seedream":
            price = _seedream_price(note)
            t = _first_mention(events, cid) if not cid.startswith("unrecorded") else None
        elif kind == "evaluator":
            price = PRICES["evaluator_call_estimate"]
            t = _first_mention(events, cid)
        else:
            continue
        b[kind]["total"] += price
        b[kind]["count_total"] += 1
        if _in_windows(t, windows):
            b[kind]["first_pass"] += price
            b[kind]["count_first"] += 1
    for e in events:
        u = e.get("model_usage") if e.get("type") == "span.model_request_end" else None
        if not isinstance(u, dict):
            continue
        cached = u.get("cache_read_input_tokens") or 0
        uncached = max(0, (u.get("input_tokens") or 0) - cached)
        usd = (uncached * PRICES["agent_input_per_m"] + cached * PRICES["agent_cached_per_m"] + (u.get("output_tokens") or 0) * PRICES["agent_output_per_m"]) / 1e6
        b["agent"]["total"] += usd
        b["agent"]["count_total"] += 1
        if _in_windows(_ts(e.get("processed_at")), windows):
            b["agent"]["first_pass"] += usd
            b["agent"]["count_first"] += 1
    # cost of the delivered video: Seedance tokens of every clip take in the final edit (task record, or the clip's
    # duration x this job's measured tokens per second); images, agent and evaluator from the clean windows
    recs = [r for r in cache.values() if isinstance(r, dict) and (r.get("usage") or {}).get("completion_tokens") and r.get("duration")]
    tps = (sum(r["usage"]["completion_tokens"] for r in recs) / sum(r["duration"] for r in recs)) if recs else 480 * 864 * 24 / 1024
    cj = {}
    try:
        raw = json.loads((files_dir / "clips.json").read_text())
        for m in (raw.get("clips", []) if isinstance(raw, dict) else raw):
            if isinstance(m, dict) and m.get("file") and m.get("task_id"):
                cj[Path(m["file"]).name] = m["task_id"]
    except (ValueError, OSError):
        pass
    durations = cache.get("_durations", {})
    video = []
    for name in delivered_clips(files_dir):
        tid = cj.get(name)
        tok = ((cache.get(tid) or {}).get("usage") or {}).get("completion_tokens") if tid else None
        how = "task record"
        if not tok:
            dur = durations.get(name) or 5
            tok, how = dur * tps, f"{dur:.1f} s x measured tokens/s"
        video.append({"clip": name, "tokens": int(tok), "usd": round(tok * PRICES["seedance_per_m"]["480p"] / 1e6, 3), "how": how})
    per_video = {"seedance": round(sum(v["usd"] for v in video), 3), "seedream": round(b["seedream"]["first_pass"], 3),
                 "agent": round(b["agent"]["first_pass"], 3),
                 "evaluator": round(max(b["evaluator"]["first_pass"], PRICES["evaluator_call_estimate"] * (len(video) + 1)), 3)}
    for v in b.values():
        v["first_pass"] = round(v["first_pass"], 3)
        v["total"] = round(v["total"], 3)
    return {
        "production_s": prod["active_s"], "steps": prod["steps"],
        "cost_per_video_usd": round(sum(per_video.values()), 2), "per_video": per_video, "video_clips": video,
        "cost_first_pass_usd": round(sum(v["first_pass"] for v in b.values()), 2),
        "cost_total_usd": round(sum(v["total"] for v in b.values()), 2),
        "breakdown": b, "seedance_tokens": seedance_tokens, "prices": PRICES,
        "notes": ["Evaluator calls are an estimate per call (about 15K input and 1.5K output tokens).",
                  "Seedream input images beyond the first ($0.003 each) are not in the log and are left out.",
                  "List prices; a negotiated contract price list would replace PRICES."],
    }


def _read_range_local(p: Path, start: int, end: int) -> bytes:
    with open(p, "rb") as fh:
        fh.seek(start)
        return fh.read(end - start + 1)


def _read_range_http(url: str, start: int, end: int) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(end - start + 1)


def mp4_duration(read, size: int) -> Optional[float]:
    """Seconds from the MP4 'mvhd' box, found in the first or the last 256 KB (moov sits at either end)."""
    import struct
    chunks = [read(0, min(size, 262144) - 1 if size else 262143)]
    if size > 262144:
        chunks.append(read(max(0, size - 262144), size - 1))
    for buf in chunks:
        i = buf.find(b"mvhd")
        if i < 4 or i + 32 > len(buf):
            continue
        version = buf[i + 4]
        if version == 1:
            timescale, duration = struct.unpack(">IQ", buf[i + 24:i + 36])
        else:
            timescale, duration = struct.unpack(">II", buf[i + 16:i + 24])
        if timescale:
            return duration / timescale
    return None


def fetch_seedance_usage(client, job_dir: Path, files_dir: Path) -> int:
    """Caches each Seedance task's usage/resolution/duration/created_at once (sync thread). Returns how many were added."""
    paid_path = files_dir / "paid_calls.json"
    if not paid_path.exists():
        return 0
    try:
        d = json.loads(paid_path.read_text())
        calls = d if isinstance(d, list) else d.get("calls", [])
    except (ValueError, OSError):
        return 0
    cache_path = job_dir / "cost_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    added = 0
    for c in calls:
        cid = str((c or {}).get("id", ""))
        if not cid.startswith("cgt-") or cid in cache or cid == "_durations":
            continue
        try:
            r = client.get(f"/contents/generations/tasks/{cid}")
            cache[cid] = {k: r.get(k) for k in ("usage", "resolution", "ratio", "duration", "framespersecond", "created_at", "status", "model")}
            added += 1
        except Exception as e:  # keep going; the estimate formula covers a missing record
            cache[cid] = {"error": str(e)[:120]}
    # durations of the delivered clips (for clips without a task record): read from the MP4 header (mvhd), from the
    # local file or, when the file stays on ModelArk storage, with two small HTTP range requests on its link
    durs = cache.setdefault("_durations", {})
    remote_urls = None
    jf = {}
    try:
        jf = json.loads((job_dir / "job.json").read_text())
    except (ValueError, OSError):
        pass
    for name in delivered_clips(files_dir):
        p = files_dir / name
        meta = (jf.get("files_index") or {}).get(name) or {}
        key = f"{name}:{meta.get('id') or (int(p.stat().st_mtime) if p.exists() else 0)}"
        if durs.get("_key_" + name) == key:
            continue
        d = None
        try:
            if p.exists():
                d = mp4_duration(lambda a, b: _read_range_local(p, a, b), p.stat().st_size)
            elif meta.get("remote") and meta.get("id"):
                if remote_urls is None:
                    remote_urls = {f["id"]: f.get("download_url") for f in client.session_files(jf.get("session_id"))}
                url = remote_urls.get(meta["id"])
                if url:
                    d = mp4_duration(lambda a, b: _read_range_http(url, a, b), meta.get("bytes") or 0)
        except Exception:
            d = None
        if d:
            durs[name] = round(d, 2)
            durs["_key_" + name] = key
            added += 1
    if added:
        cache_path.write_text(json.dumps(cache, indent=1))
    return added
