#!/usr/bin/env python3
"""Run several Seedance tasks in parallel from a commands.sh written by ugc-seedance-prompt-craft.

The sandbox stops a tool call after about 2 minutes, while one Seedance clip takes 3-5 minutes. Running the clips one
after another therefore costs the sum of all clips; submitting them together costs about the slowest one.

  submit  Submit every clip in commands.sh (or only --clips) without waiting; task ids go to the state file.
  wait    Poll every pending task for up to --max-wait seconds (default 100, under the tool limit), download finished
          videos, print a table. Call it again until "pending" is 0.
  status  Print the state file.
  (submit also starts a background poller that keeps the state file current, so the file never goes stale.)

  python3 batch.py submit --commands /mnt/session/outputs/06_prompts/commands.sh [--clips clip_01,clip_03] \
      --state /mnt/session/outputs/07_clips/tasks.json
  python3 batch.py wait --state /mnt/session/outputs/07_clips/tasks.json

Billing rules from SKILL.md still hold: one submission per clip and attempt; a submission whose result is uncertain
(timeout, 5xx, no id) is recorded as "uncertain" and never retried automatically. A clip already in the state file with
a task id is not submitted again; to make a new attempt, give it a new clip id (clip_02_v2) in prompts.json.
Standard library only. Reads ARK_API_KEY from the environment and never prints it.
"""
import argparse
import contextlib
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request

BASE = (os.environ.get("ARK_BASE_URL") or "https://ark.ap-southeast.bytepluses.com/api/v3").rstrip("/")
TERMINAL = ("succeeded", "failed", "cancelled", "expired")


def out(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    sys.exit(code)


@contextlib.contextmanager
def locked(path):
    """Serialises state updates between `wait` calls and the background poller."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path + ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def load_state(path):
    if os.path.isfile(path):
        with open(path) as fh:
            return json.load(fh)
    return {"tasks": {}}


def save_state(path, state):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=1)
    os.replace(tmp, path)


def parse_commands(path):
    """[(clip_id, command line)] from commands.sh: a '# <clip_id> (...)' comment followed by the node command."""
    clips, current = [], None
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            m = re.match(r"#\s*([A-Za-z0-9_.-]+)\s*\(", line)
            if m:
                current = m.group(1)
            elif line.startswith("node ") and current:
                clips.append((current, line))
                current = None
    return clips


def command_inputs(parts):
    """What the clip is generated from, kept in the state file so the web app can show and reuse it later
    (commands.sh is re-rendered for every retry): first frame, @Image references in order, videos, model, prompt."""
    def vals(flag):
        return [parts[i + 1] for i, a in enumerate(parts[:-1]) if a == flag]
    prompt = (vals("--prompt") or [""])[0]
    return {"first_frame": (vals("--first-frame") or [None])[0], "images": vals("--reference-image") + vals("--image"),
            "videos": vals("--reference-video"), "version": (vals("--version") or [None])[0], "model": (vals("--model") or [None])[0],
            "duration": (vals("--duration") or [None])[0], "resolution": (vals("--resolution") or [None])[0],
            "audio": "--generate-audio" in parts, "prompt": prompt[:8000]}


def submit(args):
    if not os.environ.get("ARK_API_KEY"):
        out({"ok": False, "error": "ARK_API_KEY is not available in the sandbox environment"}, 2)
    state = load_state(args.state)
    wanted = set(c.strip() for c in args.clips.split(",")) if args.clips else None
    clips = [(cid, cmd) for cid, cmd in parse_commands(args.commands) if wanted is None or cid in wanted]
    if wanted and len(clips) != len(wanted):
        missing = sorted(wanted - {c for c, _ in clips})
        out({"ok": False, "error": f"not in {args.commands}: {missing}"}, 2)
    results = []
    for cid, cmd in clips:
        if state["tasks"].get(cid, {}).get("task_id") or state["tasks"].get(cid, {}).get("status") == "uncertain":
            results.append({"clip": cid, "skipped": "already submitted", **state["tasks"][cid]})
            continue
        parts = shlex.split(cmd)
        download = parts[parts.index("--download") + 1] if "--download" in parts else os.path.dirname(os.path.abspath(args.state))
        if "--no-wait" not in parts:
            parts.append("--no-wait")
        try:
            proc = subprocess.run(parts, capture_output=True, text=True, timeout=90)
            data = json.loads(proc.stdout[proc.stdout.find("{"):]) if "{" in proc.stdout else {}
        except (subprocess.TimeoutExpired, ValueError) as error:
            proc, data = None, {"error": str(error)[:200]}
        entry = {"download": download, "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "inputs": command_inputs(parts)}
        if data.get("task_id"):
            entry.update(task_id=data["task_id"], status="submitted")
        else:
            err = (data.get("error") or (proc.stderr if proc else "") or (proc.stdout if proc else ""))[-400:]
            # a refusal before submission (validation, missing file) is safe to fix and resubmit; anything else is uncertain
            certain_refusal = proc is not None and ("Task submission failed" not in err and "uncertain" not in err)
            entry.update(status="refused" if certain_refusal else "uncertain", error=err)
        with locked(args.state):
            cur = load_state(args.state)
            cur["tasks"][cid] = entry
            save_state(args.state, cur)
            state = cur
        results.append({"clip": cid, **entry})
        if "HTTP 429" in entry.get("error", ""):
            break  # rate limited: submit the rest later with --clips
    submitted = [r for r in results if r.get("status") == "submitted"]
    if submitted:
        start_poller(args.state)
    out({"ok": all(r.get("status") in ("submitted", None) or r.get("skipped") for r in results), "submitted": len(submitted),
         "results": results, "state": args.state,
         "next": f"python3 {os.path.abspath(__file__)} wait --state {args.state}  (repeat until pending is 0); log each task id in paid_calls.json"})


def get_task(task_id):
    req = urllib.request.Request(f"{BASE}/contents/generations/tasks/{task_id}", headers={"Authorization": f"Bearer {os.environ['ARK_API_KEY']}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch(url, path):
    tmp = path + ".part"
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    os.replace(tmp, path)


def poll_once(state_path):
    """One pass over every pending task: status, download when finished. Returns the state and the pending clip ids."""
    with locked(state_path):
        state = load_state(state_path)
        pending = [cid for cid, t in state["tasks"].items() if t.get("task_id") and t.get("status") not in TERMINAL]
        for cid in pending:
            t = state["tasks"][cid]
            try:
                task = get_task(t["task_id"])
            except Exception as error:
                t["last_error"] = str(error)[:160]
                continue
            t["status"] = task.get("status", t["status"])
            if t["status"] == "succeeded":
                url = (task.get("content") or {}).get("video_url")
                usage = task.get("usage") or {}
                t["completion_tokens"] = usage.get("completion_tokens")
                if url:
                    os.makedirs(t["download"], exist_ok=True)
                    path = os.path.join(t["download"], f"{t['task_id']}.mp4")
                    try:
                        fetch(url, path)
                        t["file"] = path
                    except Exception as error:
                        t["download_error"] = str(error)[:160]
            elif t["status"] in ("failed", "cancelled", "expired"):
                t["error"] = json.dumps(task.get("error") or {})[:400]
        save_state(state_path, state)
        pending = [cid for cid, t in state["tasks"].items() if t.get("task_id") and t.get("status") not in TERMINAL]
    return state, pending


def poller(args):
    """Background loop started by `submit`: keeps the state file current until every task has finished (max 40 min),
    so reading tasks.json or calling `wait` always shows fresh statuses."""
    end = time.time() + 2400
    while time.time() < end:
        try:
            _, pending = poll_once(args.state)
        except Exception:
            pending = [1]
        if not pending:
            break
        time.sleep(15)


def start_poller(state_path):
    pidfile = state_path + ".poller"
    try:
        pid = int(open(pidfile).read().strip())
        os.kill(pid, 0)
        return  # already running
    except (OSError, ValueError):
        pass
    proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "poll", "--state", state_path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    with open(pidfile, "w") as fh:
        fh.write(str(proc.pid))


def wait(args):
    if not os.environ.get("ARK_API_KEY"):
        out({"ok": False, "error": "ARK_API_KEY is not available in the sandbox environment"}, 2)
    deadline = time.time() + args.max_wait
    while True:
        state, pending = poll_once(args.state)
        if not pending or time.time() + args.interval > deadline:
            break
        time.sleep(args.interval)
    table = [{"clip": cid, "status": t.get("status"), "task_id": t.get("task_id"), "file": t.get("file"),
              **({"error": t["error"]} if t.get("error") else {})} for cid, t in state["tasks"].items()]
    out({"ok": True, "pending": len(pending), "tasks": table,
         "next": "call wait again" if pending else "every task finished: copy each file to its clip name, run clip_check.py on it"})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--commands", required=True)
    s.add_argument("--clips", help="comma-separated clip ids (default: every clip in the file)")
    s.add_argument("--state", required=True)
    w = sub.add_parser("wait")
    w.add_argument("--state", required=True)
    w.add_argument("--max-wait", type=float, default=100)
    w.add_argument("--interval", type=float, default=10)
    pl = sub.add_parser("poll")
    pl.add_argument("--state", required=True)
    st = sub.add_parser("status")
    st.add_argument("--state", required=True)
    a = ap.parse_args()
    if a.cmd == "submit":
        submit(a)
    elif a.cmd == "wait":
        wait(a)
    elif a.cmd == "poll":
        poller(a)
    else:
        out(load_state(a.state))


if __name__ == "__main__":
    main()
