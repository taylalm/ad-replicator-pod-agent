"""Derive the UI state of a job from its event log and synced files.

Everything the UI shows is computed here from `events.json` + `files/` so live jobs, imported
jobs and demo jobs behave identically. `replay_t` (seconds since the first event) cuts the
event log so the live screen can be animated from a finished job.
"""
from __future__ import annotations

import json
import re
import fnmatch
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

STEP_NAMES = {
    1: "analyze", 2: "read-product", 3: "plan", 4: "people", 5: "personalize", 6: "prompts",
    7: "clips", 8: "assemble", 9: "quality-check", 10: "retries", 11: "deliver",
}
STEP_RE = re.compile(r"STEP\s+(\d+)\s*/\s*(\d+)\s*:\s*([^\n]+?)\s+-\s+(started|done|failed|skipped)\b\s*:?\s*([^\n]*)", re.I)

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}

# (regex on the file name, step number). First match wins. Step 0 = run-level metadata.
STEP_PATTERNS = [
    (r"^(manifest|paid_calls)\.json$", 0),
    (r"^(analysis|extraction)\.json$|^contact_sheet_|^scene_|^watermark_check|^sample\.(mp4|mov)$|^source\.mp4$", 1),
    (r"^product\.json$|^probe|^gallery_", 2),
    (r"^plan\.(json|md)$", 3),
    (r"^person_", 4),
    (r"^product_|^artwork_|^form_filled|^after_step_|^variant_|dialog", 5),
    (r"^prompts\.json$|^commands\.sh$|^prompt", 6),
    (r"^clip_|^clips\.json$|^cgt-", 7),
    (r"^final_v\d+(\.mp4|_frame_)|^edit_plan|^assembly", 8),
    (r"^report_round_|^quality_round_|^context\.json$|^report\.json$|^final_\d+\.jpg$", 9),
    (r"^retries", 10),
    (r"^final\.mp4$|^final_report|^deliver|^report\.md$", 11),
]


# ----------------------------------------------------------------------------- helpers
def parse_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        s2 = s.strip()
        if s2.endswith("Z"):
            s2 = s2[:-1] + "+00:00"
        # python 3.9 fromisoformat accepts at most 6 fractional digits
        m = re.match(r"^(.*?\.\d{1,6})\d*([+-]\d\d:\d\d)$", s2)
        if m:
            s2 = m.group(1) + m.group(2)
        return datetime.fromisoformat(s2)
    except ValueError:
        return None


def ts_seconds(e: dict) -> Optional[float]:
    d = parse_ts(e.get("processed_at"))
    return d.timestamp() if d else None


def text_of(content: Any) -> str:
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return str(content or "")


def file_kind(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext == ".json":
        return "json"
    if ext == ".md":
        return "md"
    return "other"


def guess_step(name: str) -> int:
    for pat, n in STEP_PATTERNS:
        if re.search(pat, name, re.I):
            return n
    return 0


def pretty_name(slug: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[_\-\s]+", slug) if w)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_prompts(job_dir: Path, files: List[dict]) -> Dict[str, Any]:
    """Prompts the agent saved: 04_people/people_prompts.json and 06_prompts/clip_<id>.prompt.txt."""
    out: Dict[str, Any] = {"people": [], "clips": []}
    fdir = job_dir / "files"
    pp = fdir / "people_prompts.json"
    if pp.exists():
        try:
            data = json.loads(pp.read_text())
            if isinstance(data, dict):
                data = data.get("people") or data.get("prompts") or []
            for e in data if isinstance(data, list) else []:
                if isinstance(e, dict) and e.get("prompt"):
                    out["people"].append({"name": e.get("name"), "file": e.get("file"), "prompt": e.get("prompt"), "model": e.get("model"),
                                          "size": e.get("size"), "version": e.get("version"), "references": e.get("references") or []})
        except (OSError, ValueError):
            pass
    for f in files:
        m = re.match(r"^(clip_\d+[A-Za-z0-9_-]*?)(?:_v\d+)?\.prompt\.txt$", f.get("name", ""))
        if m:
            try:
                out["clips"].append({"id": m.group(1), "file": f["name"], "prompt": (fdir / f["name"]).read_text()[:4000]})
            except OSError:
                pass
    return out


# ----------------------------------------------------------------------------- replay
def replay_cut(events: List[dict], replay_t: Optional[float]) -> List[dict]:
    if replay_t is None or not events:
        return events
    t0 = ts_seconds(events[0])
    if t0 is None:
        return events
    out = []
    for e in events:
        t = ts_seconds(e)
        if t is None or t - t0 <= replay_t:
            out.append(e)
    return out


def replay_info(events: List[dict]) -> Optional[dict]:
    """Timing markers (seconds from the first event) for the replay clock."""
    if not events:
        return None
    t0 = ts_seconds(events[0])
    if t0 is None:
        return None
    total = 0.0
    approve_at = None
    done_at = None
    for e in events:
        t = ts_seconds(e)
        if t is None:
            continue
        rel = t - t0
        total = max(total, rel)
        if e.get("type") == "user.message" and text_of(e.get("content")).strip().upper().startswith("APPROVE") and approve_at is None:
            approve_at = rel
        if e.get("type") == "agent.message":
            for m in STEP_RE.finditer(text_of(e.get("content"))):
                if int(m.group(1)) == 11 and m.group(4).lower() == "done":
                    done_at = rel
    return {"total_s": round(total, 1), "approve_at_s": round(approve_at, 1) if approve_at is not None else None,
            "done_at_s": round(done_at, 1) if done_at is not None else None}


# ----------------------------------------------------------------------------- steps
def parse_steps(events: List[dict], now_s: float) -> Dict[str, Any]:
    steps: Dict[int, dict] = {
        n: {"n": n, "name": STEP_NAMES[n], "status": "pending", "started_at": None, "finished_at": None,
            "elapsed_s": None, "latest_message": None, "reason": None, "rounds": 0}
        for n in STEP_NAMES
    }
    plan_text = None
    plan_at = None
    step_events = []  # (n, status, at)
    for e in events:
        if e.get("type") != "agent.message":
            continue
        txt = text_of(e.get("content"))
        at = e.get("processed_at")
        first_line_only = txt.strip().split("\n", 1)
        body = first_line_only[1].strip() if len(first_line_only) > 1 else ""
        for m in STEP_RE.finditer(txt):
            n = int(m.group(1))
            if n not in steps:
                continue
            status = m.group(4).lower()
            reason = (m.group(5) or "").strip() or None
            st = steps[n]
            step_events.append((n, status, at))
            if status == "started":
                st["status"] = "running"
                st["started_at"] = at
                st["finished_at"] = None
                st["rounds"] += 1
                st["reason"] = None
            elif status in ("done", "skipped"):
                st["status"] = "done"
                st["finished_at"] = at
                if st["started_at"] is None:
                    st["started_at"] = at
            elif status == "failed":
                st["status"] = "failed"
                st["finished_at"] = at
                st["reason"] = reason
                if st["started_at"] is None:
                    st["started_at"] = at
            if body:
                st["latest_message"] = body
            if n == 3 and status == "done":
                plan_text = body or txt
                plan_at = at
    # a step re-run without a closing line (e.g. a second quality-check round) is over once a later step has finished
    # likewise a step the agent never closed is over once a later step has started (seen with agent v85: only
    # "started" lines were sent)
    later_done = [n for n in steps if steps[n]["status"] in ("done", "running")]
    for n, st in steps.items():
        if st["status"] == "running" and any(m > n for m in later_done):
            st["status"] = "done"
            st["inferred"] = True
    # delivery reported: steps the agent forgot to announce (no STEP line) were still part of the run
    if steps.get(11, {}).get("status") == "done":
        for n, st in steps.items():
            if n < 11 and st["status"] == "pending":
                st["status"] = "done"
                st["inferred"] = True
    for st in steps.values():
        a = parse_ts(st["started_at"])
        b = parse_ts(st["finished_at"])
        if a and b:
            st["elapsed_s"] = max(0, round((b - a).total_seconds()))
        elif a and st["status"] == "running":
            st["elapsed_s"] = max(0, round(now_s - a.timestamp()))
    current = None
    for n in sorted(steps):
        if steps[n]["status"] == "running":
            current = n
    if current is None:
        touched = [n for n in sorted(steps) if steps[n]["status"] != "pending"]
        current = touched[-1] if touched else None
    return {"steps": [steps[n] for n in sorted(steps)], "current_step": current, "plan_text": plan_text,
            "plan_at": plan_at, "step_events": step_events}


def _delivered(files_dir, job: dict) -> bool:
    """A final MP4 exists (on disk or listed in the job's file index) and the latest gate report says PASS."""
    from pathlib import Path
    d = Path(files_dir)
    names = {p.name for p in d.glob("*")} if d.is_dir() else set()
    names |= set((job.get("files_index") or {}).keys())
    if "final.mp4" not in names and not any(n.startswith("final_v") and n.endswith(".mp4") for n in names):
        return False
    reports = sorted(d.glob("report_round_*.json")) if d.is_dir() else []
    if not reports:
        return False
    try:
        return str(json.loads(reports[-1].read_text()).get("verdict", "")).upper() == "PASS"
    except Exception:
        return False


def _asks_user(events: List[dict]) -> bool:
    """True when the agent's last message asks the user to choose or reply."""
    for e in reversed(events):
        if e.get("type") == "agent.message":
            t = text_of(e.get("content"))
            return bool(re.search(r"\breply\b|\byour options\b|\bchoose\b|\bwhich (one|option)\b|\?\s*$", t, re.I))
        if e.get("type") == "user.message":
            return False
    return False


# ----------------------------------------------------------------------------- status
def session_phase(events: List[dict]) -> str:
    """'running' | 'idle' | 'none' from the last session status event."""
    phase = "none"
    for e in events:
        t = e.get("type")
        if t == "session.status_running":
            phase = "running"
        elif t in ("session.status_idle", "session.status_terminated", "session.deleted"):
            phase = "idle"
        elif t == "user.message" and phase == "idle":
            # a user message re-activates the session; status_running follows shortly
            phase = "running"
    return phase


def derive_status(events: List[dict], parsed: dict, auto_approve: bool, step_approve: bool = False) -> Dict[str, Any]:
    phase = session_phase(events)
    steps = {s["n"]: s for s in parsed["steps"]}
    plan_at = parsed["plan_at"]
    awaiting = False
    awaiting_step = None
    # Step-by-step review: the agent stops after every "STEP n done" (n < 11) until the user sends APPROVE / CHANGES.
    if step_approve and phase != "running" and parsed["step_events"]:
        n, status, at = parsed["step_events"][-1]
        if status == "done" and n < 11:
            step_ts = parse_ts(at)
            later_user = False
            for e in events:
                et = parse_ts(e.get("processed_at"))
                if e.get("type") == "user.message" and et and step_ts and et > step_ts:
                    t = text_of(e.get("content")).strip().upper()
                    if t.startswith("APPROVE") or t.startswith("CHANGES"):
                        later_user = True
            if not later_user:
                awaiting, awaiting_step = True, n
    if plan_at and not auto_approve:
        plan_ts = parse_ts(plan_at)
        later_approval = False
        later_progress = False
        for e in events:
            et = parse_ts(e.get("processed_at"))
            if not et or not plan_ts or et <= plan_ts:
                continue
            if e.get("type") == "user.message":
                t = text_of(e.get("content")).strip().upper()
                if t.startswith("APPROVE"):
                    later_approval = True
            if e.get("type") == "agent.message" and STEP_RE.search(text_of(e.get("content"))):
                later_progress = True
        if phase != "running" and not later_approval and not later_progress:
            awaiting, awaiting_step = True, 3

    # last STEP event (ordered as they came)
    last_step = parsed["step_events"][-1] if parsed["step_events"] else None
    last_user_ts = None
    for e in events:
        if e.get("type") == "user.message":
            last_user_ts = parse_ts(e.get("processed_at"))
    session_errors = []
    for e in events:
        if e.get("type") == "session.error":
            et = parse_ts(e.get("processed_at"))
            if last_user_ts is None or (et and et >= last_user_ts):
                session_errors.append(e)

    if awaiting:
        status = "awaiting_approval"
    elif phase == "running":
        status = "running"
    elif last_step and last_step[0] == 11 and last_step[1] == "done":
        status = "done"
    elif last_step and last_step[1] == "failed" and phase == "idle" and _asks_user(events):
        status = "stopped"  # the step stopped on a decision for the user (e.g. no ad-safe option): a pause, not a crash
    elif last_step and last_step[1] == "failed":
        status = "failed"
    elif session_errors and phase == "idle":
        status = "failed"
    elif phase == "idle":
        # the agent stopped without delivering (asked a question, refused, etc.)
        status = "stopped" if last_step else ("done" if steps[11]["status"] == "done" else "stopped")
    else:
        status = "running" if events else "queued"
    return {"status": status, "awaiting_approval": awaiting, "awaiting_step": awaiting_step, "phase": phase}


# ----------------------------------------------------------------------------- errors
def _friendly_error(err) -> tuple:
    """(plain text, what happens next) for a session.error payload."""
    msg = err.get("message") if isinstance(err, dict) else str(err)
    raw = str(msg or err)
    m = re.search(r'"code"\s*:\s*"([A-Za-z_.]+)"', raw)
    code = (m.group(1) if m else None) or ((err.get("type") or err.get("code")) if isinstance(err, dict) else None)
    if "EntryTooBig" in raw or "Too Large" in raw:
        return ("The agent's working memory got too large (it had looked at many big images).",
                "Resolved by compacting the session; the agent now looks at smaller image copies. If it happens again, send 'continue'.", code)
    if "rate" in raw.lower():
        return ("The AI model is temporarily busy (rate-limited).",
                "The platform retries automatically; if the run stays stuck, send 'continue' in a few minutes.", code)
    return (raw[:300], "The platform reported a problem with the session. The run can be resumed by sending a message; if it keeps failing, start a new video later.", code)


def plain_errors(events: List[dict], parsed: dict) -> List[dict]:
    """Errors in plain words. Errors followed by successful agent activity are marked resolved and collapsed; repeated
    model-request failures within one incident are counted instead of listed one by one."""
    out = []
    for s in parsed["steps"]:
        if s["status"] == "failed":
            out.append({
                "kind": "step_failed", "step": s["n"],
                "title": f"Step {s['n']} ({pretty_name(s['name'])}) could not finish",
                "text": s["reason"] or "The agent reported a failure without a reason.",
                "next": "The run stops here. Fix the input it mentions (for example a direct MP4 link or a reachable product page) and start a new video, or send a message below to tell the agent how to continue.",
                "at": s["finished_at"], "resolved": False,
            })
    # last time the agent did real work (a successful model request, a tool call or a message)
    last_ok = None
    for e in events:
        t = e.get("type")
        if (t == "span.model_request_end" and not e.get("is_error")) or t in ("agent.tool_use", "agent.message", "agent.thread_context_compacted"):
            last_ok = e.get("processed_at")
    incidents = []
    for e in events:
        t = e.get("type")
        if t == "session.error" or (t == "span.model_request_end" and e.get("is_error")):
            at = e.get("processed_at")
            if incidents and incidents[-1]["last"] and at and (parse_ts(at) - parse_ts(incidents[-1]["last"])).total_seconds() < 120:
                inc = incidents[-1]
            else:
                inc = {"first": at, "last": at, "failed_requests": 0, "errors": []}
                incidents.append(inc)
            inc["last"] = at
            if t == "session.error":
                inc["errors"].append(e.get("error") or {})
            else:
                inc["failed_requests"] += 1
    for inc in incidents:
        resolved = bool(last_ok and parse_ts(last_ok) and parse_ts(inc["last"]) and parse_ts(last_ok) > parse_ts(inc["last"]))
        if inc["errors"]:
            text, nxt, code = _friendly_error(inc["errors"][-1])
        else:
            text, nxt, code = ("The agent model did not answer.", "The platform retries automatically. Nothing to do unless the run stops.", None)
        extra = f" ({inc['failed_requests']} failed model requests)" if inc["failed_requests"] > 1 else ""
        out.append({"kind": "session_error" if inc["errors"] else "model_error",
                    "title": ("Resolved: " if resolved else "") + ("The platform reported an error" if inc["errors"] else "A model request failed"),
                    "text": text + extra, "code": code,
                    "next": "The run recovered and continued. Nothing to do." if resolved else nxt,
                    "at": inc["first"], "resolved": resolved})
    return out


# ----------------------------------------------------------------------------- usage
def usage_of(events: List[dict]) -> dict:
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
             "model_requests": 0}
    for e in events:
        if e.get("type") == "span.model_request_end":
            mu = e.get("model_usage") or {}
            usage["model_requests"] += 1
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                usage[k] += int(mu.get(k) or 0)
    tool_calls = sum(1 for e in events if e.get("type") == "agent.tool_use")
    usage["tool_calls"] = tool_calls
    return usage


# ----------------------------------------------------------------------------- files
def read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def read_paid_calls(path: Path) -> List[dict]:
    """paid_calls.json as a list: a JSON array, {"calls": [...]}, or one JSON object per line (the agent writes either)."""
    if not path.exists():
        return []
    try:
        text = path.read_text()
    except OSError:
        return []
    try:
        data = json.loads(text)
        data = data if isinstance(data, list) else (data.get("calls", []) if isinstance(data, dict) else [])
    except ValueError:
        data = []
        for line in text.splitlines():
            line = line.strip().rstrip(",")
            if line.startswith("{"):
                try:
                    data.append(json.loads(line))
                except ValueError:
                    continue
    return [c for c in data if isinstance(c, dict)]


def list_files(files_dir: Path, job_id: str, visible_steps: Optional[set] = None) -> List[dict]:
    out = []
    if not files_dir.exists():
        return out
    for p in sorted(files_dir.iterdir()):
        if p.is_dir() or p.name.startswith("."):
            continue
        step = guess_step(p.name)
        if visible_steps is not None and step != 0 and step not in visible_steps:
            continue
        out.append({"name": p.name, "kind": file_kind(p.name), "step": step, "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime, "local_url": f"/api/jobs/{job_id}/files/{p.name}"})
    # media kept on ModelArk (serverless mode): listed like local files, served by redirect
    have = {f["name"] for f in out}
    jf = read_json(files_dir.parent / "job.json") if (files_dir.parent / "job.json").exists() else None
    for name, meta in ((jf or {}).get("files_index") or {}).items():
        if not isinstance(meta, dict) or not meta.get("remote") or name in have or name.startswith("."):
            continue
        step = guess_step(name)
        if visible_steps is not None and step != 0 and step not in visible_steps:
            continue
        out.append({"name": name, "kind": file_kind(name), "step": step, "size": meta.get("bytes") or 0,
                    "mtime": float(meta.get("created_at") or 0), "local_url": f"/api/jobs/{job_id}/files/{name}", "remote": True})
    out.sort(key=lambda f: f["name"])
    return out


def name_from(fname: str, prefix: str) -> str:
    stem = Path(fname).stem
    return pretty_name(stem[len(prefix):]) if stem.startswith(prefix) else pretty_name(stem)


def _arg_values(args: List[str], flag: str) -> List[str]:
    return [args[i + 1] for i, a in enumerate(args[:-1]) if a == flag]


def command_inputs(files_dir: Path, names: set) -> Dict[str, dict]:
    """What each clip was actually generated from: batch.py's tasks.json "inputs" (recorded since 25 Oct 2026) or,
    for older runs, the generate-with-seedance lines of commands*.sh ("# <clip_id> (...)" then the node line).
    clip_id -> {first_frame, images [in @Image order], videos, version, model}; file names are local basenames."""
    import shlex
    out: Dict[str, dict] = {}
    cmd_files = sorted((n for n in names if re.match(r"^commands.*\.sh$", n)), key=lambda n: (files_dir / n).stat().st_mtime if (files_dir / n).exists() else 0)
    for n in cmd_files:
        try:
            lines = (files_dir / n).read_text().splitlines()
        except OSError:
            continue
        cid = None
        for line in lines:
            m = re.match(r"\s*#\s*([A-Za-z0-9_.-]+)\s*\(", line)
            if m:
                cid = m.group(1)
                continue
            if cid and "seedance-generate" in line:
                try:
                    args = shlex.split(line)
                except ValueError:
                    cid = None
                    continue
                out[cid] = _inputs_from_args(args)
                cid = None
    tj = read_json(files_dir / "tasks.json") if "tasks.json" in names else None
    for cid, t in ((tj or {}).get("tasks") or {}).items() if isinstance(tj, dict) else []:
        if isinstance(t, dict) and isinstance(t.get("inputs"), dict):
            out[cid] = {k: t["inputs"].get(k) for k in ("first_frame", "images", "videos", "version", "model", "prompt_file")}
    for v in out.values():
        for k in ("first_frame",):
            if v.get(k):
                v[k] = Path(str(v[k])).name
        v["images"] = [Path(str(x)).name for x in v.get("images") or []]
    return out


def _inputs_from_args(args: List[str]) -> dict:
    ff = _arg_values(args, "--first-frame")
    return {"first_frame": ff[0] if ff else None, "images": _arg_values(args, "--reference-image") + _arg_values(args, "--image"),
            "videos": _arg_values(args, "--reference-video"), "version": (_arg_values(args, "--version") or [None])[0],
            "model": (_arg_values(args, "--model") or [None])[0]}


def still_jobs(files_dir: Path, names: set) -> Dict[str, dict]:
    """Seedream stills made through edit_batch job files (jobs_*.json / still_jobs*.json: [{name, args}]):
    output stem -> {prompt, images [basenames in order]}."""
    out: Dict[str, dict] = {}
    for n in sorted(names):
        if not re.match(r"^(jobs|still_jobs|edit_jobs)[\w-]*\.json$", n):
            continue
        data = read_json(files_dir / n)
        for job in data if isinstance(data, list) else []:
            if not isinstance(job, dict) or not isinstance(job.get("args"), list):
                continue
            args = [str(a) for a in job["args"]]
            stem = (_arg_values(args, "--name") or [job.get("name")])[0]
            if stem:
                out[str(stem)] = {"prompt": (_arg_values(args, "--prompt") or [""])[0],
                                  "images": [Path(x).name for x in _arg_values(args, "--image")]}
    return out


def derive_assets(files: List[dict], files_dir: Path, job_id: str, visible_steps: Optional[set]) -> dict:
    by_name = {f["name"]: f for f in files}
    url = lambda n: f"/api/jobs/{job_id}/files/{n}"  # noqa: E731

    manifest = read_json(files_dir / "manifest.json") if (files_dir / "manifest.json").exists() else None
    people, products = [], []
    if manifest:
        for p in manifest.get("people") or []:
            img = Path(str(p.get("image") or "")).name
            if img in by_name:
                people.append({"name": str(p.get("name") or name_from(img, "person_")), "image": url(img), "file": img})
        for p in manifest.get("products") or []:
            img = Path(str(p.get("image") or "")).name
            if img in by_name:
                products.append({"name": str(p.get("name") or name_from(img, "product_")), "image": url(img), "file": img})
    if not people:
        for f in files:
            if re.match(r"^person_.+\.(png|jpe?g|webp)$", f["name"], re.I):
                people.append({"name": name_from(f["name"], "person_"), "image": url(f["name"]), "file": f["name"]})
    if not products:
        for f in files:
            if re.match(r"^product_.+\.(png|jpe?g|webp)$", f["name"], re.I):
                products.append({"name": name_from(f["name"], "product_"), "image": url(f["name"]), "file": f["name"]})
    # attach artwork crops and match people <-> products by the name slug
    for pr in products:
        slug = Path(pr["file"]).stem[len("product_"):] if pr["file"].startswith("product_") else ""
        art = next((f["name"] for f in files if slug and re.match(rf"^artwork_{re.escape(slug)}\.", f["name"], re.I)), None)
        pr["artwork"] = url(art) if art else None
        pr["person"] = next((pe["name"] for pe in people if slug and Path(pe["file"]).stem.lower() == f"person_{slug}".lower()), None)

    clips = []
    groups: Dict[str, list] = {}
    for f in files:
        if f["kind"] == "video" and re.match(r"^clip_\d+", f["name"], re.I):
            base = re.sub(r"_v\d+(?:_[a-z0-9-]+)*$", "", Path(f["name"]).stem, flags=re.I)
            groups.setdefault(base, []).append(f)
    prompt_plan = read_json(files_dir / "prompts.json") if (files_dir / "prompts.json").exists() else None
    ref_table = {r.get("id"): r for r in (prompt_plan or {}).get("references", []) if isinstance(r, dict)} if isinstance(prompt_plan, dict) else {}
    plan_clips = {c.get("id"): c for c in (prompt_plan or {}).get("clips", []) if isinstance(c, dict)} if isinstance(prompt_plan, dict) else {}
    names = {f["name"] for f in files}
    # the agent's own record wins: clips.json entries with status "current" / "superseded"
    cj = read_json(files_dir / "clips.json") if (files_dir / "clips.json").exists() else None
    cj_list = cj.get("clips") if isinstance(cj, dict) and isinstance(cj.get("clips"), list) else \
        cj.get("takes") if isinstance(cj, dict) and isinstance(cj.get("takes"), list) else cj
    if isinstance(cj_list, dict):  # the agent often writes {clip_id: {file, status, current, superseded_by}}
        cj_list = [{"id": k, **v} for k, v in cj_list.items() if isinstance(v, dict)]
    current_files, superseded_files = set(), set()
    for m in cj_list if isinstance(cj_list, list) else []:
        if isinstance(m, dict) and (m.get("file") or m.get("id")):
            fname = Path(str(m.get("file") or f"{m.get('id')}.mp4")).name
            st = str(m.get("status", "")).lower()
            if st in ("superseded", "rejected", "archived") or m.get("superseded") is True or m.get("superseded_by") or m.get("current") is False:
                superseded_files.add(fname)
            elif st == "current" or m.get("current") is True:
                current_files.add(fname)
    cmd_inputs = command_inputs(files_dir, names)
    stills = still_jobs(files_dir, names)
    for base, takes in groups.items():
        # current take: marked current in clips.json > not marked superseded > the plain name > the newest file
        takes.sort(key=lambda x: (x["name"] in current_files, x["name"] not in superseded_files, Path(x["name"]).stem == base, x.get("mtime") or 0))
        cur = takes[-1]
        idx = re.search(r"(\d+)", base)
        pfile = next((n for n in (f"{base}.prompt.txt",) if n in names), None)
        prompt = None
        if pfile:
            try:
                prompt = (files_dir / pfile).read_text()[:6000]
            except OSError:
                prompt = None
        cur_stem = Path(cur["name"]).stem
        # retries are renamed (clip_03_couch_v4) in prompts.json: match by base, prefer the current take's id
        same_base = [k for k in plan_clips if k and re.sub(r"_v\d+(?:_[a-z0-9-]+)*$", "", k, flags=re.I) == base]
        pc = plan_clips.get(cur_stem) or plan_clips.get(base) or \
            (plan_clips[sorted(same_base, key=lambda k: int((re.search(r"_v(\d+)", k) or [0, 1])[1]))[-1]] if same_base else None) or \
            next((v for k, v in plan_clips.items() if k and base.startswith(k)), None) or {}
        if f"{cur_stem}.prompt.txt" in names and pfile != f"{cur_stem}.prompt.txt":  # the current take's own prompt
            pfile = f"{cur_stem}.prompt.txt"
            try:
                prompt = (files_dir / pfile).read_text()[:6000]
            except OSError:
                pass
        if not prompt and pc.get("prompt"):
            prompt = pc["prompt"][:6000]
        def resolve(token):
            tok = str(token).strip()
            rid = tok.split()[0] if tok else tok
            r = ref_table.get(rid) or ref_table.get(Path(rid).stem) or {}
            cand = Path(r.get("path") or r.get("url") or "").name or Path(re.split(r"\s|\(", tok)[0]).name
            fname = cand if cand in names else None
            if not fname:
                stem = Path(cand).stem
                fname = next((n for n in names if Path(n).stem == stem and file_kind(n) == "image"), None)
            return {"id": r.get("id") or rid, "kind": r.get("kind") or ("first_frame" if "first frame" in tok.lower() else None),
                    "file": fname, "url": url(fname) if fname else None,
                    "describe": r.get("describe") or (tok if tok != rid else None)}
        refs = [resolve(x) for x in (pc.get("references") or [])]
        still = pc.get("still") if isinstance(pc.get("still"), dict) else {}
        still_refs = [resolve(x) for x in (still.get("references_in_order") or [])]
        ff = pc.get("first_frame") or still.get("file")
        if ff and Path(ff).name in names and not any(r.get("file") == Path(ff).name for r in refs):
            refs.insert(0, {"id": "first_frame", "kind": "first_frame", "file": Path(ff).name, "url": url(Path(ff).name), "describe": "opening still"})
        if prompt:
            mentioned = [n for n in sorted(names, key=len, reverse=True) if file_kind(n) == "image" and re.search(rf"(?<![\w.]){re.escape(n)}", prompt)]
            m_ff = re.search(r"first[- ]frame[^\n]{0,40}?([\w.-]+\.(?:png|jpe?g|webp))", prompt, re.I)
            if m_ff and m_ff.group(1) in names:
                refs = [r for r in refs if r.get("kind") != "first_frame"]
                refs.insert(0, {"id": "first_frame", "kind": "first_frame", "file": m_ff.group(1), "url": url(m_ff.group(1)), "describe": "opening still (first frame)"})
            have = {r.get("file") for r in refs}
            for n in mentioned:
                if n not in have and not any(n != o and o.endswith(n) for o in mentioned):
                    refs.append({"id": Path(n).stem, "kind": "mentioned", "file": n, "url": url(n), "describe": "named in the prompt"})
                    have.add(n)
        # what was actually sent to Seedance (commands*.sh / tasks.json) beats the plan: first frame + @Image order
        ci = cmd_inputs.get(cur_stem) or cmd_inputs.get(base) or next((cmd_inputs[k] for k in sorted(cmd_inputs, reverse=True)
                                                                          if re.sub(r"_v\d+(?:_[a-z0-9-]+)*$", "", k, flags=re.I) == base), None)
        model = None
        if ci:
            model = ci.get("model") or ci.get("version")
            sent = []
            if ci.get("first_frame") and ci["first_frame"] in names:
                sent.append({"id": "first_frame", "kind": "first_frame", "file": ci["first_frame"], "url": url(ci["first_frame"]), "describe": "opening still (first frame)"})
            for n_img in ci.get("images") or []:
                if n_img in names:
                    known = next((r for r in refs if r.get("file") == n_img), {})
                    sent.append({"id": known.get("id") or Path(n_img).stem, "kind": "reference", "file": n_img, "url": url(n_img), "describe": known.get("describe")})
            if sent:
                refs = sent + [r for r in refs if r.get("kind") == "mentioned" and r.get("file") not in {x["file"] for x in sent}]
        # the opening still's own prompt and inputs (Seedream job files)
        ffile = next((r.get("file") for r in refs if r.get("kind") == "first_frame"), None)
        sj = stills.get(Path(ffile).stem) if ffile else None
        if ffile and not sj:
            sj = next((v for k, v in stills.items() if Path(ffile).stem.startswith(k)), None)
        if sj and not still.get("prompt"):
            still = {"prompt": sj["prompt"]}
            still_refs = [{"id": Path(n_img).stem, "kind": "reference", "file": n_img, "url": url(n_img)} for n_img in sj["images"] if n_img in names]
        clips.append({"id": base, "n": int(idx.group(1)) if idx else 0, "file": cur["name"], "url": url(cur["name"]), "size": cur["size"], "model": model,
                      "prompt": prompt, "prompt_file": pfile, "references": refs, "duration_s": pc.get("duration"),
                      "mode": pc.get("mode"), "still_prompt": (still.get("prompt") or "")[:6000] or None, "still_references": still_refs,
                      "takes": [{"file": t["name"], "url": url(t["name"]), "mtime": t.get("mtime")} for t in takes[:-1]]})
    clips.sort(key=lambda c: c["n"])
    clips_meta = read_json(files_dir / "clips.json") if (files_dir / "clips.json").exists() else None
    if isinstance(clips_meta, dict) and isinstance(clips_meta.get("clips"), list):
        clips_meta = clips_meta["clips"]
    if isinstance(clips_meta, list):
        for c in clips:
            meta = next((m for m in clips_meta if isinstance(m, dict) and (m.get("clip_id") == c["id"] or m.get("id") == c["id"])), None)
            if meta:
                c["scene"] = meta.get("scene") or meta.get("scene_index")
                c["duration_s"] = meta.get("duration_s") or meta.get("duration")
                c["summary"] = meta.get("summary") or meta.get("purpose") or meta.get("prompt_summary")

    finals = []
    for f in files:
        m = re.match(r"^final_v(\d+)\.(mp4|mov|webm)$", f["name"], re.I)
        if m:
            frames = [url(x["name"]) for x in files if re.match(rf"^final_v{m.group(1)}_frame_\d+\.(jpe?g|png)$", x["name"], re.I)]
            finals.append({"version": int(m.group(1)), "file": f["name"], "url": url(f["name"]), "size": f["size"], "frames": frames})
    finals.sort(key=lambda x: x["version"])
    final_url = None
    if "final.mp4" in by_name:
        final_url = url("final.mp4")
    elif finals:
        final_url = finals[-1]["url"]

    quality = []
    # gate reports are report_<tag>.json (tag = round_N, final_vN, ...): keep those with scores, oldest first
    cand = [f for f in files if re.match(r"^report_[\w.-]+\.json$", f["name"], re.I) or f["name"] == "report.json"]
    # numbered rounds by their number (download order scrambles file times), other tags after them by time
    jf_idx = ((read_json(files_dir.parent / "job.json") or {}).get("files_index") or {}) if (files_dir.parent / "job.json").exists() else {}

    def _rkey(f):
        # numbered rounds first by number; other tags (final_vN) by version, then by the session file's creation time
        m = re.search(r"round_(\d+)", f["name"])
        if m:
            return (0, int(m.group(1)), 0)
        v = re.search(r"_v(\d+)", f["name"])
        created = (jf_idx.get(f["name"]) or {}).get("created_at") or f.get("mtime") or 0
        return (1, int(v.group(1)) if v else 0, created)
    cand.sort(key=_rkey)
    report_files = [f["name"] for f in cand]
    rnd_counter = 0
    for rf in report_files:
        rep = read_json(files_dir / rf)
        if not isinstance(rep, dict) or not isinstance(rep.get("scores"), dict):
            continue
        rnd_counter += 1
        m = re.search(r"round_(\d+)", rf)
        rnd = int(m.group(1)) if m else rnd_counter
        tag = rf[len("report_"):-len(".json")] if rf.startswith("report_") else ""
        sheets = [url(x["name"]) for x in files if re.match(rf"^quality_(round_{rnd}|{re.escape(tag)})_sheet_\d+\.(jpe?g|png)$", x["name"], re.I)]
        scores = rep.get("scores") or {}
        quality.append({
            "round": rnd, "verdict": rep.get("verdict"), "summary": rep.get("summary"),
            "scores": {k: {"score": v.get("score"), "reason": v.get("reason"), "evidence": v.get("evidence")}
                       for k, v in scores.items() if isinstance(v, dict)},
            "hard_failures": rep.get("hard_failures") or [], "routing": rep.get("routing") or [],
            "min_score": rep.get("min_score"), "visible_text": rep.get("visible_text") or [],
            "model": rep.get("model"), "sheets": sheets, "file": rf, "md": url(Path(rf).with_suffix(".md").name) if Path(rf).with_suffix(".md").name in by_name else None,
        })
    analysis = read_json(files_dir / "analysis.json") if (files_dir / "analysis.json").exists() else None
    analysis_brief = None
    if isinstance(analysis, dict) and (visible_steps is None or 1 in visible_steps):
        analysis_brief = {
            "summary": analysis.get("summary"), "duration_s": analysis.get("duration_s"),
            "hook": analysis.get("hook"), "format": analysis.get("format"),
            "scenes": [{k: s.get(k) for k in ("index", "start", "end", "shot", "description", "purpose", "personalization_visible")}
                       for s in (analysis.get("scenes") or []) if isinstance(s, dict)],
            "on_screen_text": analysis.get("on_screen_text") or analysis.get("text"),
            "do_not_copy": analysis.get("do_not_copy"),
        }
    plan = read_json(files_dir / "plan.json") if (files_dir / "plan.json").exists() else None
    if plan is not None and visible_steps is not None and 3 not in visible_steps:
        plan = None
    product = read_json(files_dir / "product.json") if (files_dir / "product.json").exists() else None
    if product is not None and visible_steps is not None and 2 not in visible_steps:
        product = None
    keyframes = [url(f["name"]) for f in files if re.match(r"^contact_sheet_\d+\.(jpe?g|png)$", f["name"], re.I)]
    scene_frames = [url(f["name"]) for f in files if re.match(r"^scene_\d+.*\.(jpe?g|png)$", f["name"], re.I)]
    return {"people": people, "products": products, "clips": clips, "finals": finals, "final_url": final_url,
            "quality": quality, "analysis": analysis_brief, "plan": plan if isinstance(plan, dict) else None,
            "product": product if isinstance(product, dict) else None, "keyframes": keyframes,
            "scene_frames": scene_frames}


def paid_calls_of(files_dir: Path, budget: dict, visible_steps: Optional[set]) -> dict:
    counts = {"seedream": 0, "seedance": 0, "evaluator": 0}
    entries = []
    data = read_paid_calls(files_dir / "paid_calls.json")
    if isinstance(data, list):
        for c in data:
            if not isinstance(c, dict):
                continue
            try:
                step = int(c.get("step") or 0)
            except (TypeError, ValueError):
                step = 0
            if visible_steps is not None and step and step not in visible_steps:
                continue
            kind = str(c.get("kind") or "").lower()
            if kind in counts:
                counts[kind] += 1
            entries.append({"step": step, "kind": kind, "id": c.get("id"), "status": c.get("status"), "note": c.get("note")})
    b = {"seedream": int((budget or {}).get("seedream") or 0), "seedance": int((budget or {}).get("seedance") or 0),
         "evaluator": int((budget or {}).get("evaluator") or 0)}
    return {**counts, "total": sum(counts.values()), "budget": b, "entries": entries}


# ----------------------------------------------------------------------------- the whole thing
def derive_job(job: dict, events: List[dict], files_dir: Path, replay_t: Optional[float] = None,
               now_s: Optional[float] = None) -> dict:
    """Returns the full job state the UI consumes."""
    full_events = events
    events = replay_cut(full_events, replay_t)
    if now_s is None:
        if replay_t is not None and full_events and ts_seconds(full_events[0]) is not None:
            now_s = ts_seconds(full_events[0]) + replay_t
        else:
            now_s = datetime.now(timezone.utc).timestamp()
    parsed = parse_steps(events, now_s)
    inputs = job.get("inputs") or {}
    auto_approve = bool(inputs.get("auto_approve"))
    st = derive_status(events, parsed, auto_approve, bool(inputs.get("step_approve")))
    if st["status"] == "stopped" and st.get("phase") == "idle" and not _asks_user(events) and _delivered(files_dir, job):
        # the agent finished (final ad + a passing gate report) but did not send its closing STEP lines
        st = dict(st, status="done", inferred_delivery=True)
        for s in parsed["steps"]:
            if s["status"] in ("pending", "running"):
                s["status"] = "done"
                s["inferred"] = True
    if job.get("example") and not events:
        # a curated example (final ad and its real inputs, no agent event log): show it as a finished job
        st = {"status": "done", "awaiting_approval": False, "awaiting_step": None, "phase": "idle"}
        for s in parsed["steps"]:
            s["status"] = "done"
    visible_steps = None
    if replay_t is not None:
        visible_steps = {s["n"] for s in parsed["steps"] if s["status"] != "pending"}
    files = list_files(files_dir, job["id"], visible_steps)
    hidden = job.get("hidden_files") or []
    if hidden:
        files = [f for f in files if not any(fnmatch.fnmatch(f.get("name", ""), pat) for pat in hidden)]
    assets = derive_assets(files, files_dir, job["id"], visible_steps)
    paid = paid_calls_of(files_dir, inputs.get("budget") or {}, visible_steps)
    errors = plain_errors(events, parsed)
    usage = usage_of(events)
    t_first = ts_seconds(events[0]) if events else None
    t_last = ts_seconds(events[-1]) if events else None
    elapsed = None
    if t_first is not None:
        elapsed = round((now_s if st["status"] in ("running",) else (t_last or now_s)) - t_first)
    sample_url = inputs.get("sample_url")
    for cand in ("sample.mp4", "source.mp4"):
        if (files_dir / cand).exists():
            sample_url = f"/api/jobs/{job['id']}/files/{cand}"
            break
    last_agent_message = None
    for e in reversed(events):
        if e.get("type") == "agent.message":
            last_agent_message = text_of(e.get("content"))
            break
    thumbnail = None
    for cand in ("product_", "person_", "contact_sheet_"):
        hit = next((f for f in files if f["name"].startswith(cand) and f["kind"] == "image"), None)
        if hit:
            thumbnail = hit["local_url"]
            break
    if assets["finals"] and assets["finals"][-1]["frames"]:
        thumbnail = assets["finals"][-1]["frames"][0]
    out = {
        **{k: job.get(k) for k in ("id", "title", "created_at", "demo", "session_id", "inputs")},
        "read_only": bool(job.get("demo") or job.get("example") or job.get("frozen")),
        "status": st["status"], "awaiting_approval": st["awaiting_approval"], "awaiting_step": st.get("awaiting_step"), "session_phase": st["phase"],
        "steps": parsed["steps"], "current_step": parsed["current_step"], "plan_text": parsed["plan_text"],
        "paid_calls": paid, "files": files, "prompts": collect_prompts(files_dir.parent, files), "errors": errors, "usage": usage, "elapsed_s": elapsed,
        "production": _production(files_dir.parent),
        "sample_url": sample_url, "last_agent_message": last_agent_message, "thumbnail": thumbnail,
        "n_events": len(events), "n_events_total": len(full_events), "updated_at": job.get("updated_at"),
        **assets,
    }
    if replay_t is not None:
        out["replay"] = {"t": replay_t, **(replay_info(full_events) or {})}
    return out


def _production(job_dir: Path) -> Optional[dict]:
    """Production time and cost (costs.json). UI_SHOW_COST=0 hides every price and keeps the production time."""
    import os
    data = read_json(job_dir / "costs.json") if (job_dir / "costs.json").exists() else None
    if isinstance(data, dict) and os.environ.get("UI_SHOW_COST", "1") == "0":
        return {"production_s": data.get("production_s"), "steps": data.get("steps"), "waiting_s": data.get("waiting_s")}
    return data


def job_summary(job: dict, derived: dict) -> dict:
    """Compact row for the history list."""
    prod = derived.get("production") or {}
    return {
        "production_s": prod.get("production_s"), "cost_per_video_usd": prod.get("cost_per_video_usd"),
        "id": job["id"], "title": job.get("title"), "created_at": job.get("created_at"), "demo": bool(job.get("demo")),
        "read_only": bool(job.get("demo") or job.get("example") or job.get("frozen")),
        "status": derived["status"], "thumbnail": derived["thumbnail"], "current_step": derived["current_step"],
        "product_url": (job.get("inputs") or {}).get("product_url"), "elapsed_s": derived["elapsed_s"],
        "verdict": derived["quality"][-1]["verdict"] if derived["quality"] else None,
        "paid_total": derived["paid_calls"]["total"], "session_id": job.get("session_id"),
    }


def compact_event(e: dict, max_text: int = 6000) -> dict:
    """Trim bulky fields for the raw log."""
    out = {k: v for k, v in e.items() if k not in ("content", "input")}
    if "content" in e:
        txt = text_of(e["content"])
        out["text"] = txt if len(txt) <= max_text else txt[:max_text] + f"\n... [{len(txt) - max_text} more chars]"
    if "input" in e:
        inp = e["input"] if isinstance(e["input"], dict) else {"value": e["input"]}
        brief = inp.get("command") or inp.get("file_path") or inp.get("url") or inp.get("pattern") or inp.get("description")
        out["input_brief"] = str(brief)[:800] if brief else json.dumps(inp)[:800]
        out["input"] = {k: (str(v)[:max_text] if isinstance(v, str) else v) for k, v in inp.items()}
    return out
