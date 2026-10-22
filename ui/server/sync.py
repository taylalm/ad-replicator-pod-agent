"""Background sync of live jobs: new events + new session files every few seconds."""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import store
from derive import derive_job
from paths import ma_client

POLL_S = float(os.environ.get("UI_SYNC_POLL_S", "5"))
FINISHED = {"done", "failed", "stopped", "awaiting_approval"}
SLOW_POLL_S = 20
# serverless: keep only small files on the instance disk; bigger media are served from ModelArk's presigned links
MAX_DOWNLOAD = int(os.environ.get("UI_DOWNLOAD_MAX_BYTES") or 0)
JOB_TITLE_RE = re.compile(r"\s*\[(job-[\w-]+)\]\s*$")
DONE_POLL_S = 180  # delivered jobs: a revision can be sent from outside the UI (operator, API), so keep a slow check


def log(msg: str) -> None:
    print(f"[sync {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def sync_files(client, session_id: str, dest: Path, index: Dict[str, dict]) -> List[str]:
    """Downloads session files that are new or changed. `index` maps local name -> {id, bytes}.
    The API lists newest first; the newest copy of a repeated file name keeps the plain name,
    older copies get a short id suffix (same convention as tools/ma_client.py)."""
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    claimed: Dict[str, str] = {}
    for f in client.session_files(session_id):
        raw_name = f.get("filename") or f["id"]
        name = Path(raw_name).name
        if f.get("status") not in (None, "active"):
            continue
        if name in claimed and claimed[name] != f["id"]:
            stem, ext = os.path.splitext(name)
            name = f"{stem}__{f['id'][-5:]}{ext}"
        claimed[name] = f["id"]
        known = index.get(name)
        if known and known.get("id") == f["id"] and known.get("bytes") == f.get("bytes") and (dest / name).exists():
            continue
        if known and known.get("id") == f["id"] and known.get("gone"):
            continue  # an overwritten older copy: its object no longer exists
        url = f.get("download_url")
        if not url:
            continue
        if MAX_DOWNLOAD and (f.get("bytes") or 0) > MAX_DOWNLOAD:
            index[name] = {"id": f["id"], "bytes": f.get("bytes"), "created_at": f.get("created_at"),
                           "mime_type": f.get("mime_type"), "remote": True}
            continue
        tmp = dest / (name + ".part")
        try:
            with urllib.request.urlopen(url, timeout=300) as r, open(tmp, "wb") as out:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            os.replace(tmp, dest / name)
        except Exception as e:  # keep going with the other files
            if getattr(e, "code", None) in (403, 404):
                index[name] = {"id": f["id"], "bytes": f.get("bytes"), "gone": True}
            log(f"download failed for {name}: {type(e).__name__}: {str(e)[:120]}")
            if tmp.exists():
                tmp.unlink()
            continue
        index[name] = {"id": f["id"], "bytes": f.get("bytes"), "created_at": f.get("created_at"),
                       "mime_type": f.get("mime_type")}
        saved.append(name)
    return saved


class JobSyncer:
    def __init__(self):
        self.threads: Dict[str, threading.Thread] = {}
        self.wake: Dict[str, threading.Event] = {}
        self._client = None
        self.client_error: Optional[str] = None

    def client(self):
        if self._client is None:
            try:
                self._client = ma_client().Client()
            except SystemExit as e:
                self.client_error = str(e)
                raise RuntimeError(str(e))
        return self._client

    def start(self, job_id: str) -> None:
        t = self.threads.get(job_id)
        if t and t.is_alive():
            self.wake[job_id].set()
            return
        ev = threading.Event()
        self.wake[job_id] = ev
        t = threading.Thread(target=self._run, args=(job_id, ev), name=f"sync-{job_id}", daemon=True)
        self.threads[job_id] = t
        t.start()

    def is_running(self, job_id: str) -> bool:
        t = self.threads.get(job_id)
        return bool(t and t.is_alive())

    def resume_all(self) -> None:
        try:
            self.discover()
        except Exception as e:
            log(f"discover: {type(e).__name__}: {str(e)[:160]}")
        for d in store.all_job_dirs():
            try:
                job = store.read_job(d)
            except Exception:
                continue
            if job.get("demo") or job.get("frozen") or not job.get("session_id"):
                continue
            events = store.read_events(d)
            derived = derive_job(job, events, store.files_dir(d))
            log(f"resuming {job['id']} ({derived['status']})")
            self.start(job["id"])  # delivered jobs too, at the slow pace

    def discover(self) -> int:
        """Creates a job folder for every agent session started by this UI (title ends with [job-...]) that is not on
        disk yet: on a fresh serverless instance the job list is rebuilt from ModelArk itself."""
        client = self.client()
        page, added, seen = None, 0, 0
        while True:
            q = "/sessions?limit=50" + (f"&page={page}" if page else "")
            r = client.get(q)
            for sess in r.get("data", []):
                seen += 1
                m = JOB_TITLE_RE.search(sess.get("title") or "")
                if not m or store.job_dir(m.group(1)) is not None:
                    continue
                after = os.environ.get("UI_DISCOVER_AFTER")  # ISO time: older sessions' files are no longer downloadable
                if after and (sess.get("created_at") or "") < after:
                    continue
                job_id = m.group(1)
                d = store.create_job_dir(job_id)
                store.write_job(d, {"id": job_id, "title": JOB_TITLE_RE.sub("", sess.get("title") or job_id), "created_at": sess.get("created_at"),
                                    "status": "queued", "demo": False, "session_id": sess["id"], "inputs": {}, "summary": {},
                                    "files_index": {}, "discovered": True})
                store.write_events(d, [])
                added += 1
            page = r.get("next_page")
            if not page or seen > 1000:
                break
        if added:
            log(f"discovered {added} job(s) from agent sessions")
        return added

    def sync_once(self, job_id: str) -> dict:
        d = store.job_dir(job_id)
        if d is None:
            raise FileNotFoundError(job_id)
        with store.lock_for(job_id):
            job = store.read_job(d)
            events = store.read_events(d)
            seen = {e.get("id") for e in events}
            cursor = events[-1].get("processed_at") if events else None
            # the list endpoint is `created_at[gt]`; re-fetch the last second to be safe about ties
            new = [e for e in self.client().all_events(job["session_id"], created_after=cursor) if e.get("id") not in seen]
            if new:
                events.extend(new)
                store.write_events(d, events)
            if not job.get("inputs"):  # discovered job: read the brief back from its first message
                first = next((e for e in events if e.get("type") == "user.message"), None)
                if first:
                    txt = "".join(c.get("text", "") for c in first.get("content", []) if isinstance(c, dict))
                    keys = {"SAMPLE_VIDEO": "sample_url", "PRODUCT_URL": "product_url", "REQUIREMENTS": "requirements"}
                    inp = {"message": txt}
                    for line in txt.splitlines():
                        k, _, v = line.partition(":")
                        if k.strip() in keys:
                            inp[keys[k.strip()]] = v.strip()
                        elif k.strip() in ("AUTO_APPROVE", "STEP_APPROVE"):
                            inp[k.strip().lower()] = v.strip().lower().startswith("y")
                    job["inputs"] = inp
            index = job.get("files_index") or {}
            saved = sync_files(self.client(), job["session_id"], store.files_dir(d), index)
            job["files_index"] = index
            if new or saved or not (d / "costs.json").exists():
                try:  # production time and cost of one video (official list prices), see costs.py
                    import costs
                    costs.fetch_seedance_usage(self.client(), d, store.files_dir(d))
                    (d / "costs.json").write_text(json.dumps(costs.compute(d, store.files_dir(d), events), indent=1))
                except Exception as e:
                    log(f"{job_id}: costs: {type(e).__name__}: {str(e)[:160]}")
            derived = derive_job(job, events, store.files_dir(d))
            job["status"] = derived["status"]
            job["summary"] = {"current_step": derived["current_step"], "n_events": len(events),
                              "paid_total": derived["paid_calls"]["total"], "elapsed_s": derived["elapsed_s"],
                              "verdict": derived["quality"][-1]["verdict"] if derived["quality"] else None}
            store.write_job(d, job)
            return {"new_events": len(new), "new_files": saved, "status": derived["status"]}

    def _run(self, job_id: str, wake: threading.Event) -> None:
        idle_polls = 0
        while True:
            try:
                r = self.sync_once(job_id)
                if r["status"] == "done":
                    idle_polls += 1
                    # two quiet polls after delivery: files land slightly after the idle event
                    if idle_polls >= 2:
                        if idle_polls == 2:
                            log(f"{job_id}: {r['status']}, slow polling every {DONE_POLL_S} s")
                        if wake.wait(DONE_POLL_S):  # woken at once by start() after a user message (revision)
                            wake.clear()
                            idle_polls = 0
                        continue
                elif r["status"] in FINISHED:
                    # paused, stopped or failed: the user (or an operator message) may resume the session
                    # outside the UI, so keep polling at a slower pace instead of stopping
                    idle_polls = 0
                    if wake.wait(SLOW_POLL_S):
                        wake.clear()
                    continue
                else:
                    idle_polls = 0
            except Exception as e:
                log(f"{job_id}: {type(e).__name__}: {str(e)[:200]}")
                traceback.print_exc(file=sys.stderr)
            if wake.wait(POLL_S):
                wake.clear()


SYNCER = JobSyncer()
