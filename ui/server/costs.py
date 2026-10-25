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

def _load_prices() -> dict:
    """List prices live in prices_local.json next to this file: kept on the operator's machine only (not in git, not in
    the deployed package). Without it every amount is 0 and only times and usage are reported."""
    p = Path(__file__).with_name("prices_local.json")
    if p.exists():
        return json.loads(p.read_text())
    zero = {"source": "not configured (no prices_local.json)", "currency": "USD", "seedance_per_m": {"480p": 0, "720p": 0, "1080p": 0},
            "seedance_with_video_per_m": {"480p": 0, "720p": 0, "1080p": 0}, "seedream_image_small": 0, "seedream_image_large": 0,
            "seedream_tier_pixels": 2_610_000, "agent_input_per_m": 0, "agent_cached_per_m": 0, "agent_output_per_m": 0,
            "evaluator_input_per_m": 0, "evaluator_output_per_m": 0, "evaluator_call_estimate": 0}
    zero.update({"seedance_per_m_by_model": {}, "seedream_flash_image": 0})
    return zero


PRICES = _load_prices()
# model IDs behind the versions and the account's endpoints (ui/server/models.py), for pricing each task by its model
SEEDANCE_ID = {"2.5": "dreamina-seedance-2-5-260628", "2.0": "dreamina-seedance-2-0-260128",
               "2.0-fast": "dreamina-seedance-2-0-fast-260128", "2.0-mini": "dreamina-seedance-2-0-mini-260615"}


def _seedance_model(rec_model: str, logged: str) -> str:
    """Base model ID of a Seedance task from its record (model ID or endpoint) or the logged version."""
    try:
        from models import VIDEO_MODELS
        by_ep = {m["endpoint"]: SEEDANCE_ID[m["version"]] for m in VIDEO_MODELS.values() if m.get("endpoint")}
    except Exception:
        by_ep = {}
    for cand in (rec_model, logged):
        cand = str(cand or "")
        if cand in SEEDANCE_ID.values():
            return cand
        if cand in by_ep:
            return by_ep[cand]
        if cand in SEEDANCE_ID:
            return SEEDANCE_ID[cand]
    return SEEDANCE_ID["2.5"]
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
    # a step that was started but never reported done ends where the next step starts, the last one at the agent's
    # final message (agent v85 sent only "started" lines)
    starts = sorted((t, n) for n, t in started.items())
    last_msg = max((t for t, _, _ in order), default=None)
    agent_ts = [_ts(e.get("processed_at")) for e in events if e.get("type") == "agent.message"]
    last_msg = max([t for t in agent_ts if t] + ([last_msg] if last_msg else []), default=None)
    for i, (t, n) in enumerate(starts):
        if n not in done:
            nxt = next((t2 for t2, n2 in starts[i + 1:] if t2 > t), None)
            end = nxt or last_msg
            if end and end > t:
                done[n] = end
                last_done[n] = end
    # rework = a human message that is not a plain approval (CHANGES:, REGENERATE:, REVISION:, ADD CLIP:, notes...)
    user_ts = sorted(t for t in (_ts(e.get("processed_at")) for e in events
                                 if e.get("type") == "user.message" and not re.match(r"\s*APPROVE\b", _text(e), re.I)
                                 and not _is_resume(_text(e))) if t)
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
    # the step in progress counts too (from its start, or its last rework message, to the newest event)
    current = [n for n in started if n not in done and n > max(done, default=0)]
    end = _ts(events[-1].get("processed_at")) if events else None
    if current and end is not None:
        n = max(current)
        s = max([u for u in user_ts if started[n] + 1 < u <= end] + [started[n]])
        if end > s:
            windows[n] = (s, end)
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


def _step_starts(events: List[dict]) -> List[Tuple[float, int]]:
    """(time, step) of each 'STEP n/11: ... - started' line, in time order, for assigning costs to steps."""
    out = []
    for e in events:
        if e.get("type") != "agent.message":
            continue
        t = _ts(e.get("processed_at"))
        for mm in STEP_RE.finditer(_text(e)):
            if mm.group(4).lower() == "started" and t is not None:
                out.append((t, int(mm.group(1))))
    return sorted(out)


def _step_at(starts: List[Tuple[float, int]], t: Optional[float]) -> int:
    n = 0
    for st, k in starts:
        if t is not None and st <= t:
            n = k
    return n


def compute(job_dir: Path, files_dir: Path, events: List[dict]) -> Dict[str, Any]:
    prod = production_time(events)
    windows = prod.pop("windows")
    cache_path = job_dir / "cost_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    paid_path = files_dir / "paid_calls.json"
    from derive import read_paid_calls
    calls = read_paid_calls(paid_path)
    b = {k: {"first_pass": 0.0, "total": 0.0, "count_first": 0, "count_total": 0} for k in ("seedance", "seedream", "evaluator", "agent")}
    seedance_tokens = 0
    mu = {"agent": {"input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "requests": 0, "usd": 0.0},
         "seedance": {"tasks": 0, "tokens": 0, "usd": 0.0},
         "seedream": {"images_small": 0, "images_large": 0, "usd": 0.0},
         "evaluator_gate": {"calls": 0, "usd": 0.0}, "evaluator_clip_checks": {"calls": 0, "usd": 0.0}}
    starts = _step_starts(events)
    by_step: Dict[int, Dict[str, float]] = {}

    def add_step(n, key, usd):
        row = by_step.setdefault(int(n or 0), {})
        row[key] = row.get(key, 0.0) + usd

    for c in calls:
        status = str(c.get("status", "")).lower()
        rec_status = str((cache.get(str(c.get("id", ""))) or {}).get("status") or "").lower()
        if rec_status in ("succeeded", "failed", "cancelled", "expired"):  # a finished task's own record is the truth
            status = rec_status
        if str(c.get("kind", "")).lower() == "clip_check":
            status = "succeeded"  # a check is billed whatever its verdict (agents log the exit code or verdict here)
        if not isinstance(c, dict) or status not in ("succeeded", "success", "ok", "done"):
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
            model_id = _seedance_model(rec.get("model"), c.get("model"))
            table = (PRICES.get("seedance_per_m_by_model") or {}).get(model_id) or PRICES["seedance_per_m"]
            price = table.get(res, table.get("480p", 0)) * tokens / 1e6
            per = mu["seedance"].setdefault("by_model", {}).setdefault(model_id, {"tasks": 0, "tokens": 0, "usd": 0.0})
            per["tasks"] += 1
            per["tokens"] += int(tokens)
            per["usd"] += price
            seedance_tokens += int(tokens)
            mu["seedance"]["tasks"] += 1
            mu["seedance"]["tokens"] += int(tokens)
            mu["seedance"]["usd"] += price
            t = rec.get("created_at") or _first_mention(events, cid)
        elif kind == "seedream":
            flash = "flash" in (str(c.get("model") or "") + note).lower()
            price = PRICES.get("seedream_flash_image", 0) if flash else _seedream_price(note)
            if flash:
                mu["seedream"]["images_flash"] = mu["seedream"].get("images_flash", 0) + 1
            if not flash:
                mu["seedream"]["images_large" if price == PRICES["seedream_image_large"] else "images_small"] += 1
            mu["seedream"]["usd"] += price
            t = _first_mention(events, cid) if not cid.startswith("unrecorded") else None
        elif kind in ("evaluator", "clip_check"):
            row = mu["evaluator_clip_checks" if kind == "clip_check" else "evaluator_gate"]
            kind = "evaluator"  # per-clip checks use the same evaluator model and price
            price = PRICES["evaluator_call_estimate"]
            row["calls"] += 1
            row["usd"] += price
            t = _first_mention(events, cid)
        else:
            continue
        b[kind]["total"] += price
        b[kind]["count_total"] += 1
        try:
            n_step = int(c.get("step") or 0)
        except (TypeError, ValueError):
            n_step = 0
        add_step(n_step or _step_at(starts, t if isinstance(t, (int, float)) else None), kind, price)
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
        add_step(_step_at(starts, _ts(e.get("processed_at"))), "agent", usd)
        mu["agent"]["input_tokens"] += uncached
        mu["agent"]["cached_tokens"] += cached
        mu["agent"]["output_tokens"] += (u.get("output_tokens") or 0)
        mu["agent"]["requests"] += 1
        mu["agent"]["usd"] += usd
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
        "models": _model_rows(mu), "waiting_s": waiting_time(events), "stalled_s": waiting_time(events, stalls=True),
        "by_step": [{"step": n, **{k: round(v, 3) for k, v in row.items()}, "usd": round(sum(row.values()), 3)} for n, row in sorted(by_step.items())],
        "notes": ["Evaluator calls are an estimate per call (about 15K input and 1.5K output tokens).",
                  "Seedream input images beyond the first ($0.003 each) are not in the log and are left out.",
                  "List prices; a negotiated contract price list would replace PRICES."],
    }


def _model_rows(m: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One row per model for the internal cost view: what was used, at which list price, and the USD amount."""
    a, sd, sr, eg, ec = m["agent"], m["seedance"], m["seedream"], m["evaluator_gate"], m["evaluator_clip_checks"]
    return [
        {"model": "GLM-5.3 Flash (agent)", "id": "glm-5-3-flash-260828",
         "usage": f"{a['input_tokens']:,} input + {a['cached_tokens']:,} cached input + {a['output_tokens']:,} output tokens ({a['requests']} requests)",
         "unit_price": f"${PRICES['agent_input_per_m']} / ${PRICES['agent_cached_per_m']} / ${PRICES['agent_output_per_m']} per 1M tokens", "usd": round(a["usd"], 3)},
        *[{"model": f"Seedance {ver} (video)", "id": mid,
           "usage": f"{row['tasks']} tasks, {row['tokens']:,} tokens",
           "unit_price": f"${((PRICES.get('seedance_per_m_by_model') or {}).get(mid) or PRICES['seedance_per_m']).get('480p')} per 1M tokens (480p/720p)",
           "usd": round(row["usd"], 3)}
          for mid, row in (sd.get("by_model") or {}).items() for ver in [next((v for v, i in SEEDANCE_ID.items() if i == mid), mid)]],
        {"model": "Seedream 5.0 (images)", "id": "dola-seedream-5-0-pro-260628 / dola-seedream-5-0-flash-260915",
         "usage": f"pro: {sr['images_small']} images up to 2.6 MP + {sr['images_large']} larger; flash: {sr.get('images_flash', 0)} images",
         "unit_price": f"pro ${PRICES['seedream_image_small']} / ${PRICES['seedream_image_large']}, flash ${PRICES.get('seedream_flash_image', 0)} per image", "usd": round(sr["usd"], 3)},
        {"model": "Seed 2.0 lite (quality gate)", "id": "seed-2-0-lite-260428",
         "usage": f"{eg['calls']} calls (estimate per call)", "unit_price": f"${PRICES['evaluator_input_per_m']} in / ${PRICES['evaluator_output_per_m']} out per 1M tokens", "usd": round(eg["usd"], 3)},
        {"model": "Seed 2.0 lite (clip checks)", "id": "seed-2-0-lite-260428",
         "usage": f"{ec['calls']} calls (estimate per call)", "unit_price": f"${PRICES['evaluator_input_per_m']} in / ${PRICES['evaluator_output_per_m']} out per 1M tokens", "usd": round(ec["usd"], 3)},
    ]


RESUME_RE = re.compile(r"^\s*The model was busy for a moment \(rate limit\)", re.I)


def _is_resume(text: str) -> bool:
    """The automatic 'continue' sent after a model rate limit: not a human change and not a review."""
    return bool(RESUME_RE.match(text or ""))


def waiting_time(events: List[dict], stalls: bool = False) -> int:
    """Seconds the session sat idle waiting for a person (from each idle event to the next user message). With
    stalls=True: the idle time after model rate limits instead (ended by the automatic 'continue')."""
    total, idle_at = 0.0, None
    for e in events:
        t = _ts(e.get("processed_at"))
        if t is None:
            continue
        if e.get("type") == "session.status_idle":
            idle_at = t
        elif e.get("type") == "user.message" and idle_at is not None:
            if _is_resume(_text(e)) == stalls:
                total += max(0.0, t - idle_at)
            idle_at = None
    return int(total)


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
    from derive import read_paid_calls
    calls = read_paid_calls(files_dir / "paid_calls.json")
    if not calls:
        return 0
    cache_path = job_dir / "cost_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    added = 0
    for c in calls:
        cid = str((c or {}).get("id", ""))
        done = str((cache.get(cid) or {}).get("status") or "") in ("succeeded", "failed", "cancelled", "expired")
        if not cid.startswith("cgt-") or (cid in cache and done) or cid == "_durations":
            continue  # finished records are final; a record saved while the task was still running is fetched again
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
