"""Job folders on disk. Live jobs live in ui/data/jobs/<id>/, demo jobs in runs/case*/ and runs/demo_*/.

Folder format (identical for live, imported and demo jobs):
  job.json     {id, title, created_at, status, demo, session_id, inputs, summary, updated_at}
  events.json  {"events": [...]}       raw Managed Agents events, oldest first
  files/       every session output file, flat, newest copy of a repeated name wins
"""
from __future__ import annotations

import json
import os
import random
import string
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from paths import DATA_DIR, RUNS_DIR

_LOCKS: Dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def lock_for(job_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        if job_id not in _LOCKS:
            _LOCKS[job_id] = threading.RLock()
        return _LOCKS[job_id]


def new_job_id() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return time.strftime("job-%Y%m%d-%H%M%S-") + suffix


def demo_dirs() -> List[Path]:
    out = []
    if RUNS_DIR.exists():
        for p in sorted(RUNS_DIR.iterdir()):
            if p.is_dir() and (p.name.startswith("case") or p.name.startswith("demo_")) and (p / "job.json").exists():
                out.append(p)
    return out


def showcase_dirs() -> List[Path]:
    """Read-only copies of delivered jobs shipped with a deployment (runs/showcase/<job-id>/, job.json "frozen": true).
    ModelArk keeps session files only for about a day, so a cloud instance cannot rebuild older jobs from the API."""
    root = RUNS_DIR / "showcase"
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "job.json").exists()) if root.exists() else []


def job_dir(job_id: str) -> Optional[Path]:
    if not job_id or "/" in job_id or job_id.startswith("."):
        return None
    local = DATA_DIR / job_id
    if (local / "job.json").exists():
        return local
    for d in showcase_dirs():
        if d.name == job_id:
            return d
    for d in demo_dirs():
        if d.name == job_id:
            return d
    return None


def all_job_dirs() -> List[Path]:
    out = []
    if DATA_DIR.exists():
        for p in DATA_DIR.iterdir():
            if p.is_dir() and (p / "job.json").exists():
                out.append(p)
    names = {p.name for p in out}
    out.extend(d for d in showcase_dirs() if d.name not in names)
    out.extend(demo_dirs())
    return out


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def read_job(d: Path) -> dict:
    job = json.loads((d / "job.json").read_text())
    job.setdefault("id", d.name)
    job.setdefault("demo", False)
    job.setdefault("inputs", {})
    return job


def write_job(d: Path, job: dict) -> None:
    job["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _atomic_write(d / "job.json", json.dumps(job, indent=1, ensure_ascii=False))


def read_events(d: Path) -> List[dict]:
    p = d / "events.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        return data.get("events") or data.get("data") or []
    return data if isinstance(data, list) else []


def write_events(d: Path, events: List[dict]) -> None:
    _atomic_write(d / "events.json", json.dumps({"events": events}, ensure_ascii=False))


def files_dir(d: Path) -> Path:
    f = d / "files"
    f.mkdir(parents=True, exist_ok=True)
    return f


def create_job_dir(job_id: str) -> Path:
    d = DATA_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "files").mkdir(exist_ok=True)
    return d
