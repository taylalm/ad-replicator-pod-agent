"""FastAPI backend for the DZT Video Ads Replication Agent UI (port 8787).

The ARK_API_KEY never leaves this process: it is read by tools/ma_client.py from the environment
(or arkcli's stored key) and used only for calls to the Managed Agents API.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import sys
import time
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import File, Form, UploadFile, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import store  # noqa: E402
from compose import compose_message  # noqa: E402
from derive import compact_event, derive_job, job_summary, now_iso  # noqa: E402
from paths import DATA_DIR, RUNS_DIR, TOOLS_DIR, load_module, ma_client  # noqa: E402
from sync import SYNCER  # noqa: E402
from validate import is_https_url, validate_sample  # noqa: E402

app = FastAPI(title="DZT Video Ads Replication Agent UI", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("UI_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")],
    allow_methods=["*"], allow_headers=["*"],
)

MAX_BUDGET = {"seedream": 24, "seedance": 16, "evaluator": 12}


# ----------------------------------------------------------------------------- models
class Budget(BaseModel):
    seedream: int = Field(2, ge=0, le=MAX_BUDGET["seedream"])
    seedance: int = Field(4, ge=0, le=MAX_BUDGET["seedance"])
    evaluator: int = Field(3, ge=0, le=MAX_BUDGET["evaluator"])


class Options(BaseModel):
    length_s: int = Field(20, ge=5, le=60)
    resolution: str = "480p"
    captions: str = Field("full", pattern="^(full|cta_only|none)$")  # on-screen text: all captions, only the call to action, or none
    video_model: str = Field("seedance-2.5", pattern="^seedance-(2\\.5|2\\.0|2\\.0-fast|2\\.0-mini)$")
    image_model: str = Field("seedream-5.0-pro", pattern="^seedream-5\\.0-(pro|flash)$")


class NewJob(BaseModel):
    title: Optional[str] = None
    sample_url: str = ""
    sample_upload: Optional[dict] = None  # {file_id, filename, local_name} from POST /api/uploads (an MP4 the user uploaded)
    product_url: str
    requirements: str = ""
    budget: Budget = Budget()
    options: Options = Options()
    auto_approve: bool = False
    step_approve: bool = False
    references: List[dict] = []


class UrlBody(BaseModel):
    url: str


class MessageBody(BaseModel):
    text: str


class ImportBody(BaseModel):
    session_id: str
    title: Optional[str] = None
    demo: bool = False
    dest: Optional[str] = None


# ----------------------------------------------------------------------------- helpers
def _load(job_id: str):
    d = store.job_dir(job_id)
    if d is None:
        raise HTTPException(404, f"job {job_id} not found")
    job = store.read_job(d)
    events = store.read_events(d)
    return d, job, events


def _derived(job_id: str, replay_t: Optional[float] = None) -> dict:
    d, job, events = _load(job_id)
    out = derive_job(job, events, store.files_dir(d), replay_t=replay_t)
    out["syncing"] = SYNCER.is_running(job_id)
    return out


def _client():
    try:
        return SYNCER.client()
    except RuntimeError as e:
        raise HTTPException(503, f"The backend has no API key: {e}. Set ARK_API_KEY in the environment of the backend process.")


# ----------------------------------------------------------------------------- endpoints
@app.get("/api/health")
def health():
    key_present = bool(os.environ.get("ARK_API_KEY")) or (Path.home() / ".arkcli-bp" / "config.yaml").exists()
    return {"ok": True, "time": now_iso(), "api_key_present": key_present, "data_dir": str(DATA_DIR),
            "demo_jobs": [d.name for d in store.demo_dirs()], "agent": ma_client().DEFAULT_AGENT,
            "syncing": [k for k, t in SYNCER.threads.items() if t.is_alive()]}


_LAST_DISCOVER = [0.0]


@app.get("/api/jobs")
def list_jobs(demo: Optional[bool] = None):
    if time.time() - _LAST_DISCOVER[0] > 60:  # serverless: pick up jobs started on other instances
        _LAST_DISCOVER[0] = time.time()
        try:
            if SYNCER.discover():
                threading.Thread(target=SYNCER.resume_all, daemon=True).start()
        except Exception:
            pass
    rows = []
    for d in store.all_job_dirs():
        try:
            job = store.read_job(d)
            if demo is not None and bool(job.get("demo")) != demo:
                continue
            events = store.read_events(d)
            derived = derive_job(job, events, store.files_dir(d))
            rows.append(job_summary(job, derived))
        except Exception as e:  # a broken folder must not hide the others
            rows.append({"id": d.name, "title": d.name, "created_at": None, "status": "failed", "demo": False,
                         "thumbnail": None, "error": f"{type(e).__name__}: {e}"})
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    live_running = any(r["status"] in ("running", "awaiting_approval", "queued") and not r["demo"] for r in rows)
    return {"jobs": rows, "live_running": live_running}


@app.post("/api/validate-sample")
def validate_sample_ep(body: UrlBody):
    return validate_sample(body.url)


@app.post("/api/jobs")
def create_job(body: NewJob):
    upload = body.sample_upload or None
    if upload:
        if not upload.get("file_id"):
            raise HTTPException(422, "The uploaded sample video is missing; upload it again.")
        if not re.search(r"\.(mp4|mov|m4v|webm)$", str(upload.get("filename", "")), re.I):
            raise HTTPException(422, "The sample video must be an MP4, MOV or WebM file.")
    else:
        if not is_https_url(body.sample_url):
            raise HTTPException(422, "The sample video link must be an https:// link.")
        v = validate_sample(body.sample_url)
        if not v["ok"]:
            raise HTTPException(422, v["reason"])
    if not is_https_url(body.product_url):
        raise HTTPException(422, "The product page link must be an https:// link.")
    if body.options.resolution not in ("480p", "720p"):
        raise HTTPException(422, "Resolution must be 480p or 720p.")
    client = _client()
    job_id = store.new_job_id()
    title = (body.title or "").strip() or f"New ad {time.strftime('%d %b %H:%M')}"
    sample_mount = None
    if upload:  # the agent reads the uploaded file from the session's uploads folder
        ext = (re.search(r"\.(\w+)$", upload["filename"]) or [None, "mp4"])[1].lower()
        sample_mount = f"sample_video.{ext}"
        body.sample_url = f"/mnt/session/uploads/{sample_mount}"
    text = compose_message(body.sample_url, body.product_url, body.requirements, body.budget.model_dump(),
                           body.options.model_dump(), body.auto_approve, body.step_approve, body.references)
    try:
        session = client.create_session(title=f"{title} [{job_id}]")
    except Exception as e:
        raise HTTPException(502, f"Could not create the agent session: {str(e)[:300]}")
    session_id = session.get("id")
    if not session_id:
        raise HTTPException(502, f"Unexpected session response: {json.dumps(session)[:300]}")
    if upload:
        try:
            client.add_resource(session_id, upload["file_id"], sample_mount)
        except Exception as e:
            raise HTTPException(502, f"The uploaded sample video could not be attached to the session: {str(e)[:300]}")
    for r in body.references:
        try:
            client.add_resource(session_id, r["file_id"], r.get("mount_name") or r.get("filename"))
        except Exception as e:  # a missing reference must not kill the job; the agent sees it in the message
            r["mount_error"] = str(e)[:200]
    d = store.create_job_dir(job_id)
    job = {
        "id": job_id, "title": title, "created_at": now_iso(), "status": "queued", "demo": False,
        "session_id": session_id, "inputs": {
            "sample_url": body.sample_url.strip(), "product_url": body.product_url.strip(),
            "requirements": body.requirements, "budget": body.budget.model_dump(), "options": body.options.model_dump(),
            "auto_approve": body.auto_approve, "step_approve": body.step_approve, "references": body.references, "message": text,
        }, "summary": {}, "files_index": {},
    }
    if upload and upload.get("local_name"):  # local copy for the side-by-side player
        src = DATA_DIR.parent / "uploads" / Path(upload["local_name"]).name
        if src.exists():
            fd = store.files_dir(d)
            fd.mkdir(parents=True, exist_ok=True)
            import shutil
            ext_m = re.search(r"[.](\w+)$", src.name)
            shutil.copyfile(src, fd / ("sample." + (ext_m.group(1).lower() if ext_m else "mp4")))
        job["inputs"]["sample_upload"] = {"filename": upload.get("filename"), "file_id": upload.get("file_id")}
    store.write_job(d, job)
    store.write_events(d, [])
    try:
        client.send_message(session_id, text)
    except Exception as e:
        job["status"] = "failed"
        job["start_error"] = str(e)[:500]
        store.write_job(d, job)
        raise HTTPException(502, f"The session was created but the brief could not be sent: {str(e)[:300]}")
    SYNCER.start(job_id)
    return _derived(job_id)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, replay_t: Optional[float] = None):
    if replay_t is None and not SYNCER.is_running(job_id):  # serverless: the instance may have restarted
        d = store.job_dir(job_id)
        jj = store.read_job(d) if d is not None else {}
        if d is not None and not jj.get("demo") and not jj.get("frozen") and jj.get("session_id"):
            SYNCER.start(job_id)
    return _derived(job_id, replay_t)


@app.get("/api/jobs/{job_id}/events")
def get_events(job_id: str, after: int = 0, replay_t: Optional[float] = None, limit: int = 2000):
    d, job, events = _load(job_id)
    from derive import replay_cut
    cut = replay_cut(events, replay_t) if replay_t is not None else events
    after = max(0, after)
    chunk = cut[after:after + limit]
    return {"events": [dict(compact_event(e), index=after + i) for i, e in enumerate(chunk)],
            "total": len(cut), "next": after + len(chunk), "has_more": after + len(chunk) < len(cut)}


@app.post("/api/jobs/{job_id}/message")
def post_message(job_id: str, body: MessageBody):
    d, job, events = _load(job_id)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(422, "The message is empty.")
    if job.get("demo"):
        # demo jobs have no live session: the UI handles approval locally in replay mode
        return {"ok": True, "demo": True, "text": text}
    if job.get("frozen"):
        raise HTTPException(409, "This is a read-only copy of a delivered video. Start a new video to make changes.")
    client = _client()
    try:
        r = client.send_message(job["session_id"], text)
    except Exception as e:
        raise HTTPException(502, f"The message could not be sent: {str(e)[:300]}")
    with store.lock_for(job_id):
        job = store.read_job(d)
        job.setdefault("messages", []).append({"text": text, "at": now_iso()})
        job["status"] = "running"
        store.write_job(d, job)
    SYNCER.start(job_id)
    return {"ok": True, "accepted": [e.get("id") for e in (r or {}).get("data", [])], "status": "running"}


def _range_response(path: Path, request: Request) -> Response:
    size = path.stat().st_size
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if ctype.startswith("image/"):  # showcase copies keep the name but may hold JPEG data: send the real type
        with open(path, "rb") as fh:
            head = fh.read(12)
        if head.startswith(b"\xff\xd8\xff"):
            ctype = "image/jpeg"
        elif head.startswith(b"\x89PNG"):
            ctype = "image/png"
        elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            ctype = "image/webp"
    rng = request.headers.get("range")
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    if not rng:
        return FileResponse(str(path), media_type=ctype, headers=headers)
    m = re.match(r"bytes=(\d*)-(\d*)", rng)
    if not m:
        raise HTTPException(416, "bad range")
    start = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2) or 0))
    end = int(m.group(2)) if m.group(2) and m.group(1) else size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    length = end - start + 1

    def body():
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk

    headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(length)})
    return StreamingResponse(body(), status_code=206, media_type=ctype, headers=headers)


@app.api_route("/api/jobs/{job_id}/files/{name}", methods=["GET", "HEAD"])
def get_file(job_id: str, name: str, request: Request):
    d = store.job_dir(job_id)
    if d is None:
        raise HTTPException(404, "job not found")
    if "/" in name or name.startswith(".") or ".." in name:
        raise HTTPException(400, "bad file name")
    path = store.files_dir(d) / name
    if not path.is_file():
        meta = (store.read_job(d).get("files_index") or {}).get(name) or {}
        if meta.get("remote"):
            url = _remote_url(store.read_job(d).get("session_id"), meta.get("id"))
            if url:
                from fastapi.responses import RedirectResponse
                return RedirectResponse(url, status_code=307)
        raise HTTPException(404, "file not found")
    return _range_response(path, request)


PART_GROUPS = ("final", "clips", "stills", "people", "products", "plan")


def _job_parts(job_id: str) -> List[dict]:
    """The pieces a client may want to re-edit with: final (with and without text), current clip takes, first-frame
    stills, AI people, product previews and the edit plan. Each: {group, name, url}."""
    d = store.job_dir(job_id)
    if d is None:
        raise HTTPException(404, "job not found")
    job = store.read_job(d)
    derived = derive_job(job, store.read_events(d), store.files_dir(d))
    names = {f["name"] for f in derived.get("files", [])}
    url = lambda n: f"/api/jobs/{job_id}/files/{n}"  # noqa: E731
    parts, seen = [], set()

    def add(group, name):
        if name and name in names and name not in seen:
            seen.add(name)
            parts.append({"group": group, "name": name, "url": url(name)})

    final = (derived.get("finals") or [{}])[-1].get("file") if derived.get("finals") else None
    add("final", "final.mp4" if "final.mp4" in names else final)
    if "final_clean.mp4" in names:  # the delivered text-free master; older takes' clean copies are left out
        add("final", "final_clean.mp4")
    elif final and final.replace(".mp4", "_clean.mp4") in names:
        add("final", final.replace(".mp4", "_clean.mp4"))
    for c in derived.get("clips", []):
        add("clips", c.get("file"))
        for r in c.get("references") or []:
            if r.get("kind") == "first_frame":
                add("stills", r.get("file"))
    for n in sorted(names):
        if n.startswith("still_") and n.lower().endswith((".png", ".jpg", ".jpeg")):
            add("stills", n)
    for p in derived.get("people", []):
        add("people", p.get("file") or Path(str(p.get("image") or "")).name)
    for pr in derived.get("products", []):
        add("products", pr.get("file") or Path(str(pr.get("image") or "")).name)
    for n in ("edit_plan.json",):
        add("plan", n)
    return parts


@app.get("/api/jobs/{job_id}/parts")
def job_parts(job_id: str):
    return {"parts": _job_parts(job_id)}


@app.get("/api/jobs/{job_id}/bundle.zip")
def job_bundle(job_id: str):
    """Every part in one ZIP, in folders by kind (final/, clips/, stills/, people/, products/, plan/)."""
    import tempfile
    import urllib.request
    import zipfile
    d = store.job_dir(job_id)
    job = store.read_job(d) if d else {}
    parts = _job_parts(job_id)
    tmp = tempfile.NamedTemporaryFile(prefix=f"{job_id}_", suffix=".zip", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_STORED) as zf:
        for part in parts:
            local = store.files_dir(d) / part["name"]
            arc = f"{part['group']}/{part['name']}"
            if local.is_file():
                zf.write(local, arc)
                continue
            meta = (job.get("files_index") or {}).get(part["name"]) or {}
            link = _remote_url(job.get("session_id"), meta.get("id")) if meta.get("remote") else None
            if link:
                try:
                    with urllib.request.urlopen(link, timeout=120) as r:
                        zf.writestr(arc, r.read())
                except Exception:
                    continue
    from starlette.background import BackgroundTask
    return FileResponse(tmp.name, media_type="application/zip", filename=f"{job_id}_parts.zip",
                        background=BackgroundTask(lambda: os.path.exists(tmp.name) and os.unlink(tmp.name)))


_REMOTE: Dict[str, tuple] = {}


def _remote_url(session_id: Optional[str], file_id: Optional[str]) -> Optional[str]:
    """Fresh presigned download link of a session file (links last 24 h; the listing is cached for 10 minutes)."""
    if not session_id or not file_id:
        return None
    t, urls = _REMOTE.get(session_id, (0, {}))
    if time.time() - t > 600 or file_id not in urls:
        try:
            urls = {f["id"]: f.get("download_url") for f in _client().session_files(session_id)}
            _REMOTE[session_id] = (time.time(), urls)
        except Exception:
            return None
    return urls.get(file_id)


@app.post("/api/jobs/import")
def import_job(body: ImportBody):
    client = _client()
    export = load_module("export_job", TOOLS_DIR / "export_job.py")
    sid = body.session_id.strip()
    if not re.match(r"^[A-Za-z0-9_-]+$", sid):
        raise HTTPException(422, "bad session id")
    if body.dest:
        dest = Path(body.dest)
        if not dest.is_absolute():
            dest = (RUNS_DIR.parent / dest).resolve()
    else:
        dest = (RUNS_DIR / f"case_{sid}") if body.demo else (DATA_DIR / sid)
    job = export.export_job(client, sid, dest, title=body.title, demo=body.demo)
    return {"ok": True, "job": job, "dest": str(dest)}


@app.post("/api/jobs/{job_id}/sync")
def sync_now(job_id: str):
    d, job, _ = _load(job_id)
    if job.get("demo"):
        return {"ok": True, "demo": True}
    _client()
    r = SYNCER.sync_once(job_id)
    SYNCER.start(job_id)  # make sure the job's watcher is alive and awake
    return r


@app.on_event("startup")
def _startup():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=SYNCER.resume_all, daemon=True, name="resume").start()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=os.environ.get("UI_HOST", "127.0.0.1"), port=int(os.environ.get("UI_PORT", "8787")),
                reload=False)


def _send_upload(dest: Path, safe: str, note: str, job_id: Optional[str] = None) -> dict:
    """Send a saved upload to the Files API; for an existing job, also mount it in its session under /mnt/session/uploads/."""
    client = _client()
    if job_id is None:
        try:
            up = client.upload_file(str(dest))
            info = client.wait_file_active(up["id"])
        except Exception as e:
            raise HTTPException(502, f"Upload to ModelArk failed: {str(e)[:300]}")
        return {"file_id": up["id"], "filename": safe, "mount_name": safe, "mime_type": info.get("mime_type"), "bytes": info.get("bytes"),
                "note": note, "local_name": dest.name}
    job = store.read_job(store.job_dir(job_id))
    try:
        up = client.upload_file(str(dest))
        client.wait_file_active(up["id"])
        mount = f"ref_{int(time.time())}_{safe}"
        client.add_resource(job["session_id"], up["id"], mount)
    except Exception as e:
        raise HTTPException(502, f"Upload to the agent session failed: {str(e)[:300]}")
    return {"ok": True, "path": f"/mnt/session/uploads/{mount}", "filename": safe, "note": note, "file_id": up["id"]}


def _upload_dir(job_id: Optional[str]) -> Path:
    if job_id is None:
        return DATA_DIR.parent / "uploads"
    d = store.job_dir(job_id)
    if d is None:
        raise HTTPException(404, "Job not found")
    job = store.read_job(d)
    if job.get("demo") or not job.get("session_id"):
        raise HTTPException(400, "Demo jobs cannot take new references")
    return d / "uploads"


def _safe_name(name: Optional[str], default: str = "upload") -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name or default)[:80]


@app.post("/api/uploads")
async def upload_reference(file: UploadFile = File(...), note: str = Form("")):
    """Uploads a reference image/video/audio to the Files API; the id is passed back in POST /api/jobs references."""
    if not file.filename:
        raise HTTPException(422, "No file")
    safe = _safe_name(file.filename)
    updir = _upload_dir(None)
    updir.mkdir(parents=True, exist_ok=True)
    dest = updir / f"{int(time.time())}_{safe}"
    with open(dest, "wb") as fh:
        fh.write(await file.read())
    return _send_upload(dest, safe, note)


@app.post("/api/uploads/chunk")
async def upload_chunk(chunk: UploadFile = File(...), upload_id: str = Form(...), index: int = Form(...), total: int = Form(...),
                       filename: str = Form(...), note: str = Form(""), job_id: str = Form("")):
    """One piece of a large file (gateways cap request bodies, e.g. 16 MB on API Gateway). Pieces are kept until all `total`
    have arrived; the last one joins them and sends the whole file on, answering like POST /api/uploads (or the job's
    references endpoint when job_id is set). Needs every piece to reach the same server instance."""
    if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", upload_id) or not (0 <= index < total <= 400):
        raise HTTPException(422, "Bad upload_id, index or total")
    jid = job_id or None
    parts = _upload_dir(jid) / f"parts_{upload_id}"
    parts.mkdir(parents=True, exist_ok=True)
    with open(parts / f"{index:05d}", "wb") as fh:
        fh.write(await chunk.read())
    have = sorted(parts.iterdir())
    if len(have) < total:
        return {"received": len(have), "total": total}
    safe = _safe_name(filename)
    dest = parts.parent / f"{int(time.time())}_{safe}"
    with open(dest, "wb") as out:
        for part in have:
            out.write(part.read_bytes())
    shutil.rmtree(parts, ignore_errors=True)
    return _send_upload(dest, safe, note, jid)


@app.post("/api/jobs/{job_id}/references")
async def add_job_reference(job_id: str, file: UploadFile = File(...), note: str = Form("")):
    """Upload a file for an existing job and mount it in its session under /mnt/session/uploads/ (for regenerations)."""
    safe = _safe_name(file.filename, "reference")
    updir = _upload_dir(job_id)
    updir.mkdir(parents=True, exist_ok=True)
    dest = updir / f"{int(time.time())}_{safe}"
    with open(dest, "wb") as fh:
        fh.write(await file.read())
    return _send_upload(dest, safe, note, job_id)


# ----------------------------------------------------------------------------- web pages (static export) and sign-in
STATIC_DIR = Path(os.environ.get("UI_STATIC_DIR") or (Path(__file__).resolve().parent.parent / "web" / "out"))


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Password gate for shared deployments: UI_BASIC_AUTH="user:password" (unset = open, for local use)."""
    expected = os.environ.get("UI_BASIC_AUTH")
    if not expected or request.url.path == "/api/health":
        return await call_next(request)
    import base64
    import hmac
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            given = base64.b64decode(header[6:]).decode("utf-8", "replace")
            if hmac.compare_digest(given, expected):
                return await call_next(request)
        except Exception:
            pass
    return Response("Sign-in required", status_code=401, headers={"WWW-Authenticate": 'Basic realm="Ad Replicator", charset="UTF-8"'})


@app.get("/jobs/{job_id}")
def old_job_link(job_id: str, request: Request):
    from fastapi.responses import RedirectResponse
    q = str(request.url.query)
    return RedirectResponse(f"/job?id={job_id}" + (f"&{q}" if q else ""), status_code=307)


@app.get("/{path:path}", include_in_schema=False)
def web_page(path: str):
    """Serves the exported web app: exact file, <path>.html, <path>/index.html, else the 404 page."""
    if path.startswith("api/"):
        raise HTTPException(404, "Not found")
    root = STATIC_DIR.resolve()
    clean = path.strip("/")
    for cand in ([root / "index.html"] if not clean else [root / clean, root / f"{clean}.html", root / clean / "index.html"]):
        try:
            c = cand.resolve()
        except OSError:
            continue
        if c.is_file() and root in c.parents or c == root / "index.html" and c.is_file():
            headers = {"Cache-Control": "public, max-age=31536000, immutable"} if "/_next/static/" in f"/{clean}" else {"Cache-Control": "no-cache"}
            return FileResponse(c, headers=headers)
    nf = root / "404.html"
    if nf.is_file():
        return FileResponse(nf, status_code=404)
    raise HTTPException(404, "Web app not built: run npm run build in ui/web")
