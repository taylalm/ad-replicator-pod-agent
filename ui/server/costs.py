"""Production time and cost of one video, from the job's own records.

Time: for each workflow step, the agent's working time between the step's FIRST "started" and its FIRST "done" line,
counting only the periods the session was running (session.status_running -> status_idle). Waiting for a human
(approvals, reviews) and later regenerations/revisions are left out, so the number shows what one video takes.

Cost: unit prices from the official ModelArk pricing page (PRICES below, with the source and the date read).
- Seedance: the task's own usage.completion_tokens (GET /contents/generations/tasks/{id}, cached by sync.py in
  cost_cache.json) x the per-million-token price for its model and resolution; without that record, the page's estimate
  formula (duration x width x height x fps / 1024). A task with a video input (edit/extend/reference video) is priced
  from the "Input with video" table; see video_input().
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
    zero.update({"seedance_per_m_by_model": {}, "seedance_with_video_per_m_by_model": {}, "seedream_flash_image": 0,
                 "agent_runtime_per_h": 0, "web_search_per_call": 0, "web_fetch_per_call": 0})
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
VIDEO_INPUT_RATIO = 1.3  # billed tokens above this multiple of the output-only estimate mean a video went in


def task_inputs(files_dir: Path) -> Dict[str, dict]:
    """Task id -> recorded inputs (batch.py keeps them in tasks.json since generate-with-seedance v5)."""
    try:
        raw = json.loads((files_dir / "tasks.json").read_text())
    except (ValueError, OSError):
        return {}
    tasks = raw.get("tasks", raw) if isinstance(raw, dict) else {}
    return {v["task_id"]: v.get("inputs") or {} for v in tasks.values() if isinstance(v, dict) and v.get("task_id")}


def video_input(rec: dict, call: Optional[dict] = None, inputs: Optional[dict] = None) -> bool:
    """True when a Seedance task had a video input. The task record does not list its inputs, so: an explicit record
    (the web app's video_input field, batch.py's recorded --reference-video), else the billed tokens. The pricing page
    bills (input video duration + output duration) x width x height x fps / 1024, so a task billed well above its own
    output-only estimate had a video in. A short video in front of a long output can stay under the threshold and be
    priced at the higher no-video rate (an overestimate, never an underestimate)."""
    if call and isinstance(call.get("video_input"), bool):
        return call["video_input"]
    if inputs and inputs.get("videos"):
        return True
    tokens = (rec.get("usage") or {}).get("completion_tokens")
    dur = rec.get("duration")
    if not tokens or not dur:
        return False
    w, h = SEEDANCE_DIMS.get(rec.get("resolution") or "480p", (480, 864))
    return tokens > VIDEO_INPUT_RATIO * dur * w * h * (rec.get("framespersecond") or 24) / 1024


def seedance_price_per_m(model_id: str, res: str, with_video: bool) -> float:
    """List price per 1M tokens for a Seedance model, resolution and input kind."""
    if with_video:
        table = (PRICES.get("seedance_with_video_per_m_by_model") or {}).get(model_id) or PRICES["seedance_with_video_per_m"]
    else:
        table = (PRICES.get("seedance_per_m_by_model") or {}).get(model_id) or PRICES["seedance_per_m"]
    return table.get(res, table.get("480p", 0))
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
    from steplines import normalize
    c = e.get("content")
    if isinstance(c, list):
        return normalize("".join(x.get("text", "") for x in c if isinstance(x, dict)))
    return normalize(str(c or e.get("text") or ""))


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
    inputs_by_task = task_inputs(files_dir)
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
            with_video = video_input(rec, c, inputs_by_task.get(cid))
            price = seedance_price_per_m(model_id, res, with_video) * tokens / 1e6
            per = mu["seedance"].setdefault("by_model", {}).setdefault(model_id, {"tasks": 0, "tokens": 0, "usd": 0.0, "video_tasks": 0})
            per["tasks"] += 1
            per["video_tasks"] = per.get("video_tasks", 0) + int(with_video)
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
        rec = (cache.get(tid) or {}) if tid else {}
        tok = (rec.get("usage") or {}).get("completion_tokens")
        rate = seedance_price_per_m(_seedance_model(rec.get("model"), ""), rec.get("resolution") or "480p",
                                    video_input(rec, None, inputs_by_task.get(tid)))
        how = "task record"
        if not tok:
            dur = durations.get(name) or 5
            tok, how = dur * tps, f"{dur:.1f} s x measured tokens/s"
            rate = seedance_price_per_m(SEEDANCE_ID["2.5"], "480p", False)
        video.append({"clip": name, "tokens": int(tok), "usd": round(tok * rate / 1e6, 3), "how": how})
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



# ----------------------------------------------------------------------------- breakdown by step (Managed Agents billing)
# Managed Agents fee = model invocation (tokens) + agent runtime (only while the session status is running, per second)
# + tool calls (web_search per request, web_fetch free for now): docs.byteplus.com/en/docs/modelark/model-pricing.
# Seedance, Seedream and the evaluator are separate model API calls, added so the page shows what one ad costs.
STEP_NAMES = {1: "Analyze the sample", 2: "Read the product page", 3: "Plan", 4: "AI people", 5: "Personalize the product",
              6: "Prompts and first frames", 7: "Clips", 8: "Assemble", 9: "Quality check", 10: "Retries", 11: "Deliver",
              99: "Regenerations on this site"}
MENTION_RE = re.compile(r"STEP\s+(\d+)(?:\s*/\s*11)?", re.I)
PARTS = ("agent_model", "runtime", "tools", "seedance", "seedream", "checks")


def step_markers(events: List[dict], first_clip_t: Optional[float] = None) -> List[Tuple[float, int]]:
    """(time, step in progress from then on). 'n - started' sets n (rework may go back), 'n - done' moves to n+1, a loose
    'STEP n' mention only moves forward. Agents that skip the step-7 line: step 7 starts at the first Seedance task."""
    out, cur = [], 0
    for e in events:
        if e.get("type") != "agent.message":
            continue
        t, txt = _ts(e.get("processed_at")), _text(e)
        if t is None:
            continue
        nxt = cur
        for m in STEP_RE.finditer(txt):
            n, kind = int(m.group(1)), m.group(4).lower()
            nxt = n + 1 if kind in ("done", "skipped") else n
        loose = [int(m.group(1)) for m in MENTION_RE.finditer(txt) if 1 <= int(m.group(1)) <= 11]
        if loose and max(loose) > nxt and not STEP_RE.search(txt):
            nxt = max(loose)
        if first_clip_t and cur < 7 < nxt and t > first_clip_t:
            out.append((first_clip_t, 7))
        if nxt != cur:
            out.append((t, nxt))
            cur = nxt
    return sorted(out)


def _bucket(n: int) -> int:
    return 99 if n == 99 else min(11, max(1, int(n or 1)))


def breakdown(job_dir: Path, files_dir: Path, events: List[dict], spans: Optional[List[Tuple[Optional[float], Optional[float]]]] = None,
              skip=None, first_checks: Optional[int] = None) -> Dict[str, Any]:
    """Time, tokens and list-price cost per workflow step.

    Default ("full"): everything the job used, including regenerations made on this site.
    spans: count only these (start, end) periods of the log (None = open end). skip(call) -> True leaves a paid call out;
    first_checks keeps only the first N clip checks of step 7."""
    lo_hi = [(a if a is not None else float("-inf"), b if b is not None else float("inf")) for a, b in (spans or [(None, None)])]
    inside = lambda t: t is not None and any(a <= t <= b + 1 for a, b in lo_hi)
    whole_start = len(lo_hi) == 1 and lo_hi[0][0] == float("-inf")  # calls without a time count only when nothing is cut out
    cache_path = job_dir / "cost_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    rec_t = lambda r: r.get("created_at") if isinstance(r.get("created_at"), (int, float)) else _ts(r.get("created_at"))
    sd_times = sorted(t for t in (rec_t(r) for r in cache.values() if isinstance(r, dict) and r.get("usage")) if t and inside(t))
    marks = step_markers(events, sd_times[0] if sd_times else None)
    at = lambda t: _bucket(_step_at(marks, t))
    run_iv = running_intervals(events)
    steps: Dict[int, Dict[str, float]] = {}

    def row(n):
        return steps.setdefault(_bucket(n), {"runtime_s": 0.0, "tokens": 0, "input": 0, "cached": 0, "output": 0, "requests": 0, "tool_calls": 0,
                                             "web_search": 0, "web_fetch": 0, **{k: 0.0 for k in PARTS}})
    # runtime per step: the session's running time, cut at the step boundaries
    times = [_ts(e.get("processed_at")) for e in events]
    times = [t for t in times if t is not None]
    if times:
        cuts = sorted({times[0], times[-1], *[t for t, _ in marks]})
        for a, b in zip(cuts, cuts[1:]):
            for wa, wb in lo_hi:
                lo, hi = max(a, wa), min(b, wb)
                if hi > lo:
                    secs = _overlap((lo, hi), run_iv)
                    r = row(at(a + 0.001))
                    r["runtime_s"] += secs
                    r["runtime"] += secs / 3600 * PRICES.get("agent_runtime_per_h", 0)
    for e in events:
        t = _ts(e.get("processed_at"))
        if not inside(t):
            continue
        if e.get("type") == "span.model_request_end" and isinstance(e.get("model_usage"), dict):
            u = e["model_usage"]
            cached = u.get("cache_read_input_tokens") or 0
            unc, out = max(0, (u.get("input_tokens") or 0) - cached), u.get("output_tokens") or 0
            r = row(at(t))
            r["requests"] += 1
            r["input"] += unc
            r["cached"] += cached
            r["output"] += out
            r["tokens"] += unc + cached + out
            r["agent_model"] += (unc * PRICES["agent_input_per_m"] + cached * PRICES["agent_cached_per_m"] + out * PRICES["agent_output_per_m"]) / 1e6
        elif e.get("type") == "agent.tool_use":
            r = row(at(t))
            r["tool_calls"] += 1
            if e.get("name") in ("web_search", "web_fetch"):
                r[e["name"]] += 1
                r["tools"] += PRICES.get(f"{e['name']}_per_call", 0)
    from derive import read_paid_calls
    inputs_by_task = task_inputs(files_dir)
    n_checks = 0
    counts = {"seedance_tasks": 0, "seedance_tokens": 0, "seedream_images": 0, "checks": 0}
    calls = [(c, False) for c in read_paid_calls(files_dir / "paid_calls.json")]
    if spans is None and skip is None:
        try:
            calls += [(c, True) for c in json.loads((job_dir / "web_paid_calls.json").read_text())]
        except (OSError, ValueError):
            pass
    for c, web in calls:
        if not isinstance(c, dict):
            continue
        kind, cid, note = str(c.get("kind", "")).lower(), str(c.get("id") or c.get("task_id") or ""), str(c.get("note", ""))
        rec = cache.get(cid) or {}
        status = str(rec.get("status") or c.get("status") or ("succeeded" if web else "")).lower()
        if kind in ("clip_check", "still_check"):
            status = "succeeded"  # a check is billed whatever its verdict
        if status not in ("succeeded", "success", "ok", "done"):
            continue  # failed or refused submissions are not billed
        t = rec_t(rec) if kind == "seedance" and rec else (_first_mention(events, cid) if cid and not web else None)
        if skip is not None:
            if skip(c):
                continue
            if kind == "clip_check" and str(c.get("step")) == "7":
                n_checks += 1
                if first_checks is not None and n_checks > first_checks:
                    continue
        elif spans is not None and ((t is None and not whole_start) or (t is not None and not inside(t))):
            continue
        try:
            n = 99 if web else (int(c.get("step") or 0) or _step_at(marks, t or 0))
        except (TypeError, ValueError):
            n = _step_at(marks, t or 0)
        r = row(n)
        if kind == "seedance":
            res = rec.get("resolution") or c.get("resolution") or "480p"
            tokens = (rec.get("usage") or {}).get("completion_tokens") or c.get("completion_tokens")
            if not tokens:
                dur = rec.get("duration") or (int(m.group(1)) if (m := re.search(r"(\d+)\s*s\b", note)) else 5)
                w, h = SEEDANCE_DIMS.get(res, (480, 864))
                tokens = dur * w * h * (rec.get("framespersecond") or 24) / 1024
            model_id = _seedance_model(rec.get("model"), c.get("model"))
            r["seedance"] += seedance_price_per_m(model_id, res, video_input(rec, c, inputs_by_task.get(cid))) * tokens / 1e6
            counts["seedance_tasks"] += 1
            counts["seedance_tokens"] += int(tokens)
        elif kind == "seedream":
            k = int(c.get("images") or 1)
            flash = "flash" in (str(c.get("model") or "") + note).lower()
            size = str(c.get("size") or note)
            r["seedream"] += k * (PRICES.get("seedream_flash_image", 0) if flash else _seedream_price(size))
            counts["seedream_images"] += k
        elif kind in ("evaluator", "clip_check", "still_check"):
            r["checks"] += PRICES["evaluator_call_estimate"]
            counts["checks"] += 1
    rows = []
    for n in sorted(steps):
        r = steps[n]
        usd = sum(r[k] for k in PARTS)
        if r["runtime_s"] < 1 and usd < 0.0005 and not r["tokens"]:
            continue
        rows.append({"n": n, "name": STEP_NAMES.get(n, f"Step {n}"), "runtime_s": round(r["runtime_s"]), "tokens": int(r["tokens"]),
                     "tool_calls": int(r["tool_calls"]), "usd": round(usd, 4), "parts": {k: round(r[k], 4) for k in PARTS}})
    tot = {k: sum(steps[n][k] for n in steps) for k in ("runtime_s", "tokens", "input", "cached", "output", "requests", "tool_calls", "web_search", "web_fetch", *PARTS)}
    return {
        "mode": "selected" if skip is not None else "full",
        "total_usd": round(sum(tot[k] for k in PARTS), 2), "runtime_s": round(tot["runtime_s"]),
        "tokens": {"total": int(tot["tokens"]), "input": int(tot["input"]), "cached": int(tot["cached"]), "output": int(tot["output"])},
        "requests": int(tot["requests"]), "tool_calls": int(tot["tool_calls"]), "web_search": int(tot["web_search"]), "web_fetch": int(tot["web_fetch"]),
        "parts": {k: round(tot[k], 4) for k in PARTS}, "counts": counts, "steps": rows,
        "prices_source": PRICES.get("source"), "runtime_per_h": PRICES.get("agent_runtime_per_h", 0),
        "web_search_per_call": PRICES.get("web_search_per_call", 0),
    }

def _model_rows(m: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One row per model for the internal cost view: what was used, at which list price, and the USD amount."""
    a, sd, sr, eg, ec = m["agent"], m["seedance"], m["seedream"], m["evaluator_gate"], m["evaluator_clip_checks"]
    return [
        {"model": "GLM-5.3 Flash (agent)", "id": "glm-5-3-flash-260828",
         "usage": f"{a['input_tokens']:,} input + {a['cached_tokens']:,} cached input + {a['output_tokens']:,} output tokens ({a['requests']} requests)",
         "unit_price": f"${PRICES['agent_input_per_m']} / ${PRICES['agent_cached_per_m']} / ${PRICES['agent_output_per_m']} per 1M tokens", "usd": round(a["usd"], 3)},
        *[{"model": f"Seedance {ver} (video)", "id": mid,
           "usage": f"{row['tasks']} tasks ({row.get('video_tasks', 0)} with video input), {row['tokens']:,} tokens",
           "unit_price": f"${seedance_price_per_m(mid, '480p', False)} per 1M tokens (480p/720p), ${seedance_price_per_m(mid, '480p', True)} with video input",
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
