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
AUTO_RESUMES = int(os.environ.get("UI_AUTO_RESUMES", "3"))  # "continue" messages after model rate limits, per job
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
        if known and known.get("tos") and known.get("bytes") == f.get("bytes") and (known.get("id") in (None, f["id"])):
            continue  # already kept in the bucket (storage.py)
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
            if getattr(e, "code", None) in (403, 404) and not (known or {}).get("tos"):  # a bucket copy stays valid
                index[name] = {"id": f["id"], "bytes": f.get("bytes"), "gone": True}
            log(f"download failed for {name}: {type(e).__name__}: {str(e)[:120]}")
            if tmp.exists():
                tmp.unlink()
            continue
        index[name] = {"id": f["id"], "bytes": f.get("bytes"), "created_at": f.get("created_at"),
                       "mime_type": f.get("mime_type")}
        saved.append(name)
    return saved


RECORDS = ("job.json", "events.json", "costs.json", "cost_cache.json", "captions_doc.json", "web_takes.json",
           "web_paid_calls.json", "web_scene_picks.json", "web_edit_plan.json")
_RECORDS_AT: Dict[str, float] = {}  # job id -> last upload of its records
_RECORD_MTIME: Dict[str, float] = {}  # job id/name -> mtime uploaded


def mirror_files(client, job: dict, d: Path, limit: int = 40) -> int:
    """Copies the job's files into the bucket (storage.py) while their session links still work: local files as they
    are, files that stay on ModelArk (bigger media) streamed from their link. Bounded per pass; the rest next pass."""
    import storage
    if not storage.enabled() or job.get("frozen") or job.get("demo") or job.get("example"):
        return 0
    jid, idx = job["id"], job.setdefault("files_index", {})
    kept = job.setdefault("tos_files", {})  # name -> bytes stored in the bucket
    fd = store.files_dir(d)
    local = {p.name for p in fd.iterdir() if p.is_file() and not p.name.endswith(".part")} if fd.exists() else set()
    links, copied = None, 0
    for name in sorted(local | set(idx)):
        meta = idx.get(name) or {}
        if meta.get("gone") or name.startswith("."):
            continue
        path = fd / name
        size = path.stat().st_size if path.is_file() else meta.get("bytes")
        if size is not None and kept.get(name) == size:
            continue
        ok = False
        if path.is_file():
            ok = storage.put_file(jid, f"files/{name}", path)
        elif meta.get("id") and not meta.get("tos") and job.get("session_id"):
            if links is None:
                links = {f["id"]: f.get("download_url") for f in client.session_files(job["session_id"])}
            link = links.get(meta["id"])
            ok = bool(link) and storage.copy_url(jid, f"files/{name}", link)
        if ok:
            kept[name] = size
            if name in idx:
                idx[name]["tos"] = True
            copied += 1
            if copied >= limit:
                break
    return copied


def mirror_records(job: dict, d: Path, force: bool = False) -> int:
    """Uploads the job's records (job.json, events, costs, the site's own records) that changed, at most once a minute
    per job unless forced (a finished step, a deletion of the session...)."""
    import storage
    if not storage.enabled() or job.get("frozen") or job.get("demo") or job.get("example"):
        return 0
    jid = job["id"]
    if not force and time.time() - _RECORDS_AT.get(jid, 0) < 60:
        return 0
    n = 0
    for name in RECORDS:
        p = d / name
        if not p.is_file():
            continue
        m = p.stat().st_mtime
        if _RECORD_MTIME.get(f"{jid}/{name}") == m:
            continue
        if storage.put_file(jid, name, p):
            _RECORD_MTIME[f"{jid}/{name}"] = m
            n += 1
    _RECORDS_AT[jid] = time.time()
    return n


def restore_from_bucket(job_id: str) -> Optional[Path]:
    """Recreates a job folder from the bucket (records now; small files later, in fill_from_bucket). Files that stay
    in the bucket are listed in files_index as remote + tos, so they are served with signed links."""
    import shutil
    import storage
    if store.job_dir(job_id) is not None or not storage.enabled():
        return store.job_dir(job_id)
    d = store.create_job_dir(job_id)
    if not storage.download(job_id, "job.json", d / "job.json"):
        shutil.rmtree(d, ignore_errors=True)
        return None
    for name in ("events.json", "costs.json"):  # what the job list needs; the other records come with the files
        storage.download(job_id, name, d / name)
    if not (d / "events.json").exists():
        store.write_events(d, [])
    job = store.read_job(d)
    idx, kept = job.setdefault("files_index", {}), job.setdefault("tos_files", {})
    for o in storage.list_keys(storage.key(job_id, "files/")):
        name = o["key"].rsplit("/", 1)[-1]
        idx[name] = {**(idx.get(name) or {}), "bytes": o["size"], "remote": True, "tos": True}
        idx[name].pop("gone", None)
        kept[name] = o["size"]
    job["restored_from_bucket"] = True
    job["fill_pending"] = True
    store.write_job(d, job)
    for name in RECORDS:  # what is on disk now is what the bucket holds
        if (d / name).exists():
            _RECORD_MTIME[f"{job_id}/{name}"] = (d / name).stat().st_mtime
    log(f"{job_id}: restored from the bucket ({len(idx)} files)")
    return d


def fill_from_bucket(job: dict, d: Path, limit: int = 60) -> bool:
    """Brings the small files of a restored job back to the instance disk (the page reads plans, prompts and checks
    from disk); media stay in the bucket. Returns True when nothing is left to fetch."""
    import storage
    fd = store.files_dir(d)
    fd.mkdir(parents=True, exist_ok=True)
    for name in RECORDS[3:]:  # cost cache and the site's own records
        if not (d / name).exists() and storage.download(job["id"], name, d / name):
            _RECORD_MTIME[f"{job['id']}/{name}"] = (d / name).stat().st_mtime
    got = 0
    for name, meta in sorted((job.get("files_index") or {}).items()):
        if not meta.get("tos") or (fd / name).exists():
            continue
        small = (meta.get("bytes") or 0) <= max(MAX_DOWNLOAD, 600_000) or name.endswith((".json", ".txt", ".md", ".sh"))
        if not small:
            continue
        if storage.download(job["id"], f"files/{name}", fd / name):
            meta["remote"] = False
            got += 1
            if got >= limit:
                return False
    return True


def restore_sample(client, job: dict, dest: Path) -> Optional[str]:
    """An uploaded sample video lives only in the session's uploads folder, not in its outputs: a fresh serverless
    instance has lost the local copy made at job creation. Fetch it back from the file mounted in the session
    (its Files API record carries a download link while the file is active, about a week). At most 3 tries per job."""
    sample = str((job.get("inputs") or {}).get("sample_url") or "")
    if not sample.startswith("/mnt/session/uploads/") or job.get("sample_restored") or job.get("sample_tries", 0) >= 3:
        return None
    if any((dest / f"sample.{x}").exists() for x in ("mp4", "mov", "webm")):
        return None
    job["sample_tries"] = job.get("sample_tries", 0) + 1
    try:
        res = next((r for r in client.get_session(job["session_id"]).get("resources") or []
                    if r.get("type") == "file" and r.get("mount_path") == sample), None)
        meta = client.get(f"/files/{res['file_id']}") if res else {}
        url = meta.get("download_url")
        if not url or (meta.get("bytes") or 0) > 200_000_000:
            return None
        ext = (re.search(r"\.(\w+)$", sample) or [None, "mp4"])[1].lower()
        name = f"sample.{ext}"
        dest.mkdir(parents=True, exist_ok=True)
        tmp = dest / (name + ".part")
        with urllib.request.urlopen(url, timeout=300) as r, open(tmp, "wb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        os.replace(tmp, dest / name)
        job["sample_restored"] = True
        return name
    except Exception as e:
        log(f"{job.get('id')}: sample restore: {type(e).__name__}: {str(e)[:120]}")
        return None


_WEB_CHECKED: set = set()


def restore_web_files(client, job: dict, d: Path) -> List[str]:
    """Caption edits and exports made in the web app are mounted in the job's session as web_<name>; a fresh
    serverless instance copies them back (captions_doc.json into the job folder, exports into files/). Once per job
    and process."""
    if job.get("id") in _WEB_CHECKED or not job.get("session_id"):
        return []
    _WEB_CHECKED.add(job.get("id"))
    got = []
    import webfiles
    try:
        resources = client.get_session(job["session_id"]).get("resources") or []
        newest = {}  # packed JSON records: the latest version of each
        for r in resources:
            pk = webfiles.parse(Path(str(r.get("mount_path") or "")).name) if r.get("type") == "file" else None
            if pk and pk[1] > newest.get(pk[0], (0, None))[0]:
                newest[pk[0]] = (pk[1], r)
        for name, (_, r) in newest.items():
            dest = d / name if name in ("captions_doc.json", "web_takes.json", "web_paid_calls.json", "web_scene_picks.json") else store.files_dir(d) / name
            if dest.exists():
                continue
            url = (client.get(f"/files/{r['file_id']}") or {}).get("download_url")
            if url:
                with urllib.request.urlopen(url, timeout=120) as resp:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(webfiles.unpack(resp.read()))
                got.append(name)
        for r in resources:
            mount = str(r.get("mount_path") or "")
            if r.get("type") != "file" or not mount.startswith("/mnt/session/uploads/web_") or webfiles.parse(Path(mount).name):
                continue
            name = Path(mount).name[len("web_"):]
            dest = d / name if name in ("captions_doc.json", "web_takes.json", "web_paid_calls.json", "web_scene_picks.json") else store.files_dir(d) / name
            if dest.exists():
                continue
            url = (client.get(f"/files/{r['file_id']}") or {}).get("download_url")
            if not url:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            with urllib.request.urlopen(url, timeout=300) as resp, open(tmp, "wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            os.replace(tmp, dest)
            got.append(name)
    except Exception as e:
        log(f"{job.get('id')}: web files restore: {type(e).__name__}: {str(e)[:120]}")
    return got


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
        d = store.job_dir(job_id)
        if d is not None and store.read_job(d).get("session_gone"):  # kept in the bucket, nothing left to sync
            t = threading.Thread(target=self._fill_only, args=(job_id,), name=f"fill-{job_id}", daemon=True)
            self.threads[job_id] = t
            t.start()
            return
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
        try:  # jobs kept in the bucket come back with their files, even after their session links expired
            import storage
            for jid in storage.list_jobs():
                if store.job_dir(jid) is None and restore_from_bucket(jid) is not None:
                    added += 1
        except Exception as e:
            log(f"bucket discovery: {type(e).__name__}: {str(e)[:160]}")
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
            if job.get("fill_pending"):
                job["fill_pending"] = not fill_from_bucket(job, d)
            index = job.get("files_index") or {}
            saved = sync_files(self.client(), job["session_id"], store.files_dir(d), index)
            job["files_index"] = index
            try:
                mirror_files(self.client(), job, d)
            except Exception as e:
                log(f"{job_id}: bucket copy: {type(e).__name__}: {str(e)[:160]}")
            restore_sample(self.client(), job, store.files_dir(d))
            restore_web_files(self.client(), job, d)
            web_paid = d / "web_paid_calls.json"  # a regeneration made on the site changes the cost too
            stale = web_paid.exists() and (d / "costs.json").exists() and web_paid.stat().st_mtime > (d / "costs.json").stat().st_mtime
            if new or saved or stale or not (d / "costs.json").exists():
                try:  # production time and cost of one video (official list prices), see costs.py
                    import costs
                    costs.fetch_seedance_usage(self.client(), d, store.files_dir(d))
                    data = costs.compute(d, store.files_dir(d), events)
                    data["breakdown"] = costs.breakdown(d, store.files_dir(d), events)
                    (d / "costs.json").write_text(json.dumps(data, indent=1))
                except Exception as e:
                    log(f"{job_id}: costs: {type(e).__name__}: {str(e)[:160]}")
            if self._auto_resume(job, events):
                store.write_job(d, job)
            derived = derive_job(job, events, store.files_dir(d))
            job["status"] = derived["status"]
            job["summary"] = {"current_step": derived["current_step"], "n_events": len(events),
                              "paid_total": derived["paid_calls"]["total"], "elapsed_s": derived["elapsed_s"],
                              "verdict": derived["quality"][-1]["verdict"] if derived["quality"] else None}
            store.write_job(d, job)
            try:
                mirror_records(job, d, force=derived["status"] in FINISHED)
            except Exception as e:
                log(f"{job_id}: bucket records: {type(e).__name__}: {str(e)[:160]}")
            return {"new_events": len(new), "new_files": saved, "status": derived["status"]}

    def _fill_only(self, job_id: str) -> None:
        d = store.job_dir(job_id)
        if d is None:
            return
        with store.lock_for(job_id):
            job = store.read_job(d)
            if job.get("fill_pending"):
                while not fill_from_bucket(job, d):
                    pass
                job["fill_pending"] = False
                store.write_job(d, job)

    def _auto_resume(self, job: dict, events: list) -> bool:
        """A session that went idle because the model provider stayed busy (retries exhausted on a rate limit or
        model error) is not waiting for anyone: after a minute, tell it to continue. At most AUTO_RESUMES times per job,
        never when a person has written since. Returns True when a message was sent."""
        idle_i = next((i for i in range(len(events) - 1, -1, -1) if events[i].get("type") in ("session.status_idle", "session.status_running")), None)
        if idle_i is None or events[idle_i].get("type") != "session.status_idle":
            return False
        if (events[idle_i].get("stop_reason") or {}).get("type") != "retries_exhausted":
            return False
        err = next((e for e in reversed(events[:idle_i + 1]) if e.get("type") == "session.error"), None)
        kind = str(((err or {}).get("error") or {}).get("type") or "")
        if not kind.startswith("model_"):
            return False
        if any(e.get("type") == "user.message" for e in events[idle_i:]) or job.get("auto_resumes", 0) >= AUTO_RESUMES:
            return False
        from derive import parse_ts
        at = parse_ts(events[idle_i].get("processed_at"))
        if at is None or time.time() - at.timestamp() < 60:
            return False
        try:
            self.client().send_message(job["session_id"], "The model was busy for a moment (rate limit). Continue exactly where you left off.")
        except Exception as e:
            log(f"{job['id']}: auto-resume failed: {type(e).__name__}: {str(e)[:160]}")
            return False
        job["auto_resumes"] = job.get("auto_resumes", 0) + 1
        log(f"{job['id']}: auto-resumed after {kind} ({job['auto_resumes']}/{AUTO_RESUMES})")
        return True

    def _run(self, job_id: str, wake: threading.Event) -> None:
        idle_polls = 0
        while True:
            if store.job_dir(job_id) is None:  # deleted from the site
                log(f"{job_id}: removed, sync stopped")
                return
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
                if getattr(e, "status", None) == 404 and "/sessions/" in str(getattr(e, "url", "")):
                    # the agent session was deleted on ModelArk: a job kept in the bucket stays (read-only from now on);
                    # otherwise drop it from this instance. Either way, stop syncing it.
                    d = store.job_dir(job_id)
                    if d is not None:
                        job = store.read_job(d)
                        if job.get("tos_files"):
                            job["session_gone"] = True
                            store.write_job(d, job)
                            mirror_records(job, d, force=True)
                            log(f"{job_id}: session deleted on ModelArk, job kept from the bucket")
                            return
                        import shutil
                        shutil.rmtree(d, ignore_errors=True)
                    log(f"{job_id}: session deleted on ModelArk, job removed")
                    return
                log(f"{job_id}: {type(e).__name__}: {str(e)[:200]}")
                traceback.print_exc(file=sys.stderr)
            if wake.wait(POLL_S):
                wake.clear()


SYNCER = JobSyncer()
