#!/usr/bin/env python3
"""Run several clip checks side by side (clip_check.py, about 40-60 s each).

A tool call in the sandbox ends after about 2 minutes, so checking a dozen clips one after another costs 10-15 minutes.
This starts the checks as detached processes, a few at a time, and collects their verdicts.

  python3 /mnt/skills/ugc-quality-gate/scripts/check_batch.py run --jobs check_jobs.json \
      --state /mnt/session/outputs/07_clips/check_state.json [--parallel 4]

check_jobs.json is a list of {"name": "clip_03", "args": ["--clip", "/mnt/session/outputs/07_clips/clip_03.mp4",
"--prompt-file", "...", "--product", "label|image|expected", "--person", "name|image", "--out", "/mnt/session/outputs/07_clips/checks"]}:
the arguments of one clip_check.py call. `run` starts what is not started yet, waits up to --max-wait seconds (default
100) and prints each verdict; call it again until "pending" is 0. Do not sleep before calling it: it waits by itself.
Standard library only.
"""
import argparse
import contextlib
import fcntl
import json
import os
import subprocess
import sys
import time

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clip_check.py")


def out(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    sys.exit(code)


def alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a finished child that was never reaped still answers kill(0): reap it if it is ours
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True


@contextlib.contextmanager
def locked(path):
    """One process at a time starts or collects jobs (the foreground `run` and its background runner)."""
    with open(path + ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def start_background(args):
    """Leave a detached runner behind that keeps starting queued jobs and updating the state file until all are done,
    so the state file is current even if nobody calls `run` again."""
    pidfile = args.state + ".runner"
    try:
        os.kill(int(open(pidfile).read().strip()), 0)
        return
    except (OSError, ValueError):
        pass
    proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "run", "--jobs", os.path.abspath(args.jobs), "--state", os.path.abspath(args.state),
                             "--parallel", str(args.parallel), "--max-wait", "2400", "--background"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    with open(pidfile, "w") as fh:
        fh.write(str(proc.pid))


def run(args):
    with open(args.jobs) as fh:
        jobs = json.load(fh)
    if not isinstance(jobs, list) or not all(isinstance(j, dict) and j.get("name") and isinstance(j.get("args"), list) for j in jobs):
        out({"ok": False, "error": "jobs.json must be a list of {name, args}"}, 2)
    if len({j["name"] for j in jobs}) != len(jobs):
        out({"ok": False, "error": "job names must be unique"}, 2)
    state = {"jobs": {}}
    if os.path.isfile(args.state):
        with open(args.state) as fh:
            state = json.load(fh)
    logdir = os.path.join(os.path.dirname(os.path.abspath(args.state)), "check_logs")
    os.makedirs(logdir, exist_ok=True)

    def save():
        tmp = args.state + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(state, fh, indent=1)
        os.replace(tmp, args.state)

    def collect():
        for name, s in state["jobs"].items():
            if s.get("status") != "running" or alive(s["pid"]):
                continue
            text = open(s["log"]).read() if os.path.isfile(s["log"]) else ""
            try:
                data = json.loads(text[text.find("{"):]) if "{" in text else {}
            except ValueError:
                data = {}
            if data.get("verdict"):
                s.update(status="checked", verdict=data.get("verdict"), report=data.get("report") or data.get("json"),
                         issues=[f"{i.get('kind')}: {str(i.get('detail', ''))[:140]} -> {str(i.get('fix', ''))[:120]}" for i in (data.get("hard_failures") or data.get("issues") or [])][:6])
            else:
                s.update(status="error", error=(data.get("error") or text[-300:]).strip()[:300])
        save()

    deadline = time.time() + args.max_wait
    while True:
        lock = locked(args.state)
        lock.__enter__()
        if os.path.isfile(args.state):  # another process may have started or finished jobs
            with open(args.state) as fh:
                state.update(json.load(fh))
        collect()
        running = [n for n, s in state["jobs"].items() if s.get("status") == "running"]
        for j in jobs:
            if len(running) >= args.parallel:
                break
            if j["name"] in state["jobs"]:
                continue
            log = os.path.join(logdir, f"{j['name']}.json")
            cmd = [sys.executable, SCRIPT] + [str(a) for a in j["args"]]
            with open(log, "w") as fh:
                proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
            state["jobs"][j["name"]] = {"status": "running", "pid": proc.pid, "log": log, "started": time.time()}
            running.append(j["name"])
            save()
        lock.__exit__(None, None, None)
        pending = [j["name"] for j in jobs if state["jobs"].get(j["name"], {}).get("status") in (None, "running")]
        if not pending or time.time() + 3 > deadline:
            break
        time.sleep(3)
    if getattr(args, "background", False):
        return
    if pending:
        start_background(args)
    table = [{"name": j["name"], **{k: v for k, v in state["jobs"].get(j["name"], {"status": "not started"}).items() if k in ("status", "verdict", "issues", "error")}}
             for j in jobs]
    out({"ok": not any(t["status"] == "error" for t in table), "pending": len(pending), "jobs": table,
         "next": "call run again with the same --jobs and --state" if pending else "all checks finished: regenerate the FAIL clips with the reported fixes; log each check (kind clip_check) in paid_calls.json"})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--jobs", required=True)
    r.add_argument("--state", required=True)
    r.add_argument("--parallel", type=int, default=4)
    r.add_argument("--max-wait", type=float, default=100)
    r.add_argument("--background", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    run(a)


if __name__ == "__main__":
    main()
