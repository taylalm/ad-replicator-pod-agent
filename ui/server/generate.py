"""Direct still and clip generation from the web app (no agent), plus rebuilding the final from accepted takes.

Request bodies are the ones of the generate-with-seedream / generate-with-seedance skill scripts (verified there
against the ModelArk docs and real calls): Seedream POST /images/generations, Seedance POST /contents/generations/tasks
then GET /contents/generations/tasks/{id}. Every new still or take is checked with the quality gate's still_check.py /
clip_check.py and recorded in <job>/web_takes.json; billable calls go to <job>/web_paid_calls.json.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

import store
from models import IMAGE_MODELS, VIDEO_MODELS
from paths import REPO, ma_client

BASE_URL = (os.environ.get("ARK_BASE_URL") or "https://ark.ap-southeast.bytepluses.com/api/v3").rstrip("/")
SEEDREAM_IDS = {"5.0-pro": "dola-seedream-5-0-pro-260628", "5.0-flash": "dola-seedream-5-0-flash-260915"}
SEEDANCE_IDS = {"2.5": "dreamina-seedance-2-5-260628", "2.0": "dreamina-seedance-2-0-260128",
                "2.0-fast": "dreamina-seedance-2-0-fast-260128", "2.0-mini": "dreamina-seedance-2-0-mini-260615"}
SEEDANCE_SPECS = {"2.5": (4, 30, ("480p", "720p", "1080p")), "2.0": (4, 15, ("480p", "720p", "1080p")),
                  "2.0-fast": (4, 15, ("480p", "720p")), "2.0-mini": (4, 15, ("480p", "720p"))}
GATE = REPO / "skills" / "ugc-quality-gate" / "scripts"
ASSEMBLY = REPO / "skills" / "video-assembly" / "scripts"
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
RUNS: Dict[str, dict] = {}  # job id -> {state, kind, clip, file, error, n, started}


def api_key() -> str:
    key = os.environ.get("ARK_API_KEY")
    if not key:
        key = ma_client().resolve_api_key()  # local runs: the arkcli profile; never printed or stored
    return key


def _request(method: str, path: str, body: Optional[dict] = None, timeout: int = 180) -> dict:
    req = urllib.request.Request(BASE_URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:600]
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None


def data_url(path: Path) -> str:
    mime = MIME.get(path.suffix.lower())
    if not mime:
        raise ValueError(f"unsupported image type {path.suffix}")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=300) as r, open(tmp, "wb") as out:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)


def takes_path(d: Path) -> Path:
    return d / "web_takes.json"


def read_takes(d: Path) -> List[dict]:
    try:
        return json.loads(takes_path(d).read_text())
    except (OSError, ValueError):
        return []


def _write_takes(d: Path, takes: List[dict]) -> None:
    takes_path(d).write_text(json.dumps(takes, indent=1, ensure_ascii=False))


def _log_paid(d: Path, entry: dict) -> None:
    p = d / "web_paid_calls.json"
    try:
        calls = json.loads(p.read_text())
    except (OSError, ValueError):
        calls = []
    calls.append({**entry, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": "web"})
    p.write_text(json.dumps(calls, indent=1))


def _check(kind: str, d: Path, media: Path, prompt: str, products: List[Path], payoff: Optional[str]) -> dict:
    """still_check / clip_check on the new still or take (about a cent). Returns the report's verdict and findings."""
    out_dir = store.files_dir(d) / "web_checks"
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = out_dir / f"{media.stem}.prompt.txt"
    prompt_file.write_text(prompt)
    prod = [f"product|{p}|the personalized product exactly as in this image" for p in products if p.is_file()][:3]
    if not prod:
        return {"verdict": None, "summary": "no product image to check against"}
    if kind == "still":
        cmd = [sys.executable, str(GATE / "still_check.py"), "--still", str(media), "--scene", prompt[:2000], "--out", str(out_dir)]
    else:
        cmd = [sys.executable, str(GATE / "clip_check.py"), "--clip", str(media), "--prompt-file", str(prompt_file), "--frames", "8", "--out", str(out_dir)]
        if payoff:
            cmd += ["--payoff", payoff]
    for p in prod:
        cmd += ["--product", p]
    env = {**os.environ, "ARK_API_KEY": api_key()}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
    try:
        res = json.loads(r.stdout[r.stdout.find("{"):])
        report = json.loads(Path(res["report"]).read_text()) if res.get("report") else res
    except (ValueError, KeyError, OSError):
        return {"verdict": None, "summary": (r.stderr or r.stdout)[-300:]}
    issues = [i for i in report.get("issues") or [] if i.get("kind") != "minor"]
    return {"verdict": report.get("verdict"), "summary": report.get("summary"), "payoff_window": report.get("payoff_window"),
            "issues": [{"kind": i.get("kind"), "detail": str(i.get("detail", ""))[:300], "fix": str(i.get("fix", ""))[:300]} for i in issues][:8]}


def start(job_id: str, d: Path, req: dict, resolve: Callable[[str], Optional[Path]], products: List[Path],
          persist: Callable[[Path, str], None]) -> dict:
    """req: {kind: still|clip, clip, prompt, inputs: [{file|asset, role: first_frame|reference}], model, duration,
    resolution, audio, payoff}. One generation per job at a time; poll RUNS[job_id]."""
    if RUNS.get(job_id, {}).get("state") == "running":
        raise RuntimeError("a generation is already running for this video; wait for it to finish")
    kind = req.get("kind")
    if kind not in ("still", "clip"):
        raise ValueError("kind must be still or clip")
    prompt = str(req.get("prompt") or "").strip()
    if len(prompt) < 20:
        raise ValueError("the prompt is too short")
    clip = re.sub(r"[^A-Za-z0-9_-]", "", str(req.get("clip") or "clip"))[:60]
    state = {"state": "running", "kind": kind, "clip": clip, "file": None, "error": None, "started": time.time(), "step": "submitting"}
    RUNS[job_id] = state

    def work():
        try:
            files = store.files_dir(d)
            takes = read_takes(d)
            n = 1 + sum(1 for t in takes if t.get("clip") == clip and t.get("kind") == kind)
            inputs = []
            for inp in req.get("inputs") or []:
                role = "first_frame" if inp.get("role") == "first_frame" else "reference"
                if inp.get("asset"):
                    if not re.match(r"^asset://asset-[A-Za-z0-9-]+$", str(inp["asset"])):
                        raise ValueError(f"bad asset id {inp['asset']}")
                    inputs.append({"role": role, "asset": inp["asset"]})
                    continue
                path = resolve(str(inp.get("file") or ""))
                if not path:
                    raise FileNotFoundError(f"input not available: {inp.get('file')}")
                inputs.append({"role": role, "file": path.name, "path": path})
            if kind == "still":
                model_key = req.get("model") if req.get("model") in IMAGE_MODELS else "seedream-5.0-pro"
                m = IMAGE_MODELS[model_key]
                body = {"model": m.get("endpoint") or SEEDREAM_IDS[m["version"]], "prompt": prompt, "size": "1.5K",
                        "response_format": "url", "watermark": False, "output_format": "png"}
                imgs = [data_url(i["path"]) for i in inputs if i.get("path")]
                if imgs:
                    body["image"] = imgs[0] if len(imgs) == 1 else imgs
                state["step"] = "generating"
                res = _request("POST", "/images/generations", body, timeout=240)
                url = ((res.get("data") or [{}])[0]).get("url")
                if not url:
                    raise RuntimeError(f"no image returned: {json.dumps(res)[:300]}")
                name = f"web_still_{clip}_{n}.png"
                _download(url, files / name)
                _log_paid(d, {"kind": "seedream", "model": m["version"], "images": len(res.get("data") or []),
                              "size": ((res.get("data") or [{}])[0]).get("size"), "file": name})
            else:
                model_key = req.get("model") if req.get("model") in VIDEO_MODELS else "seedance-2.5"
                m = VIDEO_MODELS[model_key]
                lo, hi, resolutions = SEEDANCE_SPECS[m["version"]]
                duration = int(req.get("duration") or 5)
                if not lo <= duration <= hi:
                    raise ValueError(f"duration must be {lo}-{hi} s for {m['label']}")
                resolution = req.get("resolution") or "480p"
                if resolution not in resolutions:
                    raise ValueError(f"{m['label']} supports {', '.join(resolutions)}")
                content: List[dict] = [{"type": "text", "text": prompt}]
                first = [i for i in inputs if i["role"] == "first_frame"][:1]
                for i in first:
                    content.append({"type": "image_url", "image_url": {"url": i.get("asset") or data_url(i["path"])}, "role": "first_frame"})
                for i in [i for i in inputs if i["role"] == "reference"]:
                    content.append({"type": "image_url", "image_url": {"url": i.get("asset") or data_url(i["path"])}, "role": "reference_image"})
                body = {"model": m.get("endpoint") or SEEDANCE_IDS[m["version"]], "content": content,
                        "ratio": "adaptive" if first else "9:16", "duration": duration, "resolution": resolution,
                        "generate_audio": bool(req.get("audio", True))}
                created = _request("POST", "/contents/generations/tasks", body)
                task_id = created.get("id")
                if not task_id:
                    raise RuntimeError(f"no task id: {json.dumps(created)[:300]}")
                state.update(step="generating", task_id=task_id)
                deadline = time.time() + 1500
                while True:
                    task = _request("GET", f"/contents/generations/tasks/{task_id}")
                    if task.get("status") in ("succeeded", "failed", "cancelled", "expired"):
                        break
                    if time.time() > deadline:
                        raise RuntimeError(f"still running after 25 min; task {task_id}")
                    time.sleep(8)
                if task.get("status") != "succeeded":
                    raise RuntimeError(f"Seedance task {task.get('status')}: {json.dumps(task.get('error') or {})[:300]}")
                name = f"web_take_{clip}_{n}.mp4"
                _download(task["content"]["video_url"], files / name)
                _log_paid(d, {"kind": "seedance", "model": m["version"], "task_id": task_id,
                              "completion_tokens": (task.get("usage") or {}).get("completion_tokens"), "file": name,
                              "video_input": False})
            state.update(step="checking", file=name)
            check = _check(kind, d, files / name, prompt, products, req.get("payoff"))
            if check.get("verdict"):
                _log_paid(d, {"kind": "still_check" if kind == "still" else "clip_check", "model": "seed-2-0-lite", "file": name})
            takes = read_takes(d)
            takes.append({"n": n, "kind": kind, "clip": clip, "file": name, "model": model_key, "prompt": prompt,
                          "inputs": [{k: v for k, v in i.items() if k != "path"} for i in inputs],
                          "duration": req.get("duration"), "resolution": req.get("resolution"), "task_id": state.get("task_id"),
                          "check": check, "accepted": False, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            _write_takes(d, takes)
            state.update(state="done", check=check)
            for path, mount in ((files / name, f"web_{name}"), (takes_path(d), "web_web_takes.json"),
                                (d / "web_paid_calls.json", "web_web_paid_calls.json")):
                try:
                    persist(path, mount)
                except Exception as e:
                    state.setdefault("warnings", []).append(f"not kept in the agent session: {str(e)[:120]}")
        except Exception as e:
            state.update(state="failed", error=str(e)[:600])

    threading.Thread(target=work, daemon=True).start()
    return state


def accept(d: Path, file: str) -> dict:
    """Marks a take (or still) as the one to use for its clip; only one accepted per clip and kind."""
    takes = read_takes(d)
    hit = next((t for t in takes if t.get("file") == file), None)
    if not hit:
        raise FileNotFoundError(file)
    for t in takes:
        if t.get("clip") == hit["clip"] and t.get("kind") == hit["kind"]:
            t["accepted"] = t is hit
    _write_takes(d, takes)
    return hit


def _duration(path: Path) -> Optional[float]:
    try:
        import costs
        from costs import _read_range_local
        return costs.mp4_duration(lambda a, b: _read_range_local(path, a, b), path.stat().st_size)
    except Exception:
        return None


def _payoff(files: Path, web: Dict[str, dict], name: str):
    """The take's payoff window from its own check (site take record, or the agent's check_<stem>.json)."""
    if name in web:
        return (web[name].get("check") or {}).get("payoff_window")
    try:
        return json.loads((files / f"check_{Path(name).stem}.json").read_text()).get("payoff_window")
    except (OSError, ValueError):
        return None


def _shift(t: float, drops) -> float:
    """A time on the old timeline mapped onto the new one, with the dropped scenes cut out."""
    return t - sum(min(max(t - a, 0.0), b - a) for a, b in drops)


def rebuild(job_id: str, d: Path, resolve: Callable[[str], Optional[Path]], captions_doc: dict,
            persist: Callable[[Path, str], None], exports: Dict[str, dict], picks: Optional[Dict[str, dict]] = None) -> dict:
    """Re-assembles the agent's edit with the chosen take of every scene (picks: {clip: {file, include}}, else the
    accepted site takes), the editor's captions and the client outro: files/final_edit_v<n>.mp4 + _clean.mp4 (the new
    clean master for the caption editor). Scenes left out are cut and the captions after them move up."""
    if exports.get(job_id, {}).get("state") == "running":
        raise RuntimeError("an export is already running")
    state = {"state": "running", "started": time.time(), "file": None, "error": None, "warnings": []}
    exports[job_id] = state

    def work():
        try:
            files = store.files_dir(d)
            plans = sorted(files.glob("edit_plan*.json"), key=lambda p: p.stat().st_mtime)
            if not plans:
                raise RuntimeError("the agent's edit plan is not available")
            plan = json.loads(plans[-1].read_text())
            web = {t["file"]: t for t in read_takes(d) if t.get("kind") == "clip" and t.get("file")}
            accepted = {t["clip"]: t for t in web.values() if t.get("accepted")}
            clips, drops, timeline = [], [], 0.0
            for c in plan.get("clips") or []:
                c = dict(c)
                if c.get("path"):
                    stem = Path(c["path"]).stem
                    base = re.sub(r"_v\d+(?:_[a-z0-9-]+)*$", "", stem, flags=re.I)
                    length = float(c.get("end", 0) or 0) - float(c.get("start", 0) or 0)
                    if length <= 0:
                        whole = resolve(Path(c["path"]).name)
                        length = ((_duration(whole) if whole else None) or 3.0) - float(c.get("start", 0) or 0)
                    pick = (picks or {}).get(base) or (picks or {}).get(stem)
                    if pick and pick.get("include") is False:  # scene left out: cut it, captions move up
                        drops.append((timeline, timeline + length))
                        timeline += length
                        continue
                    chosen = (pick or {}).get("file") or (accepted.get(base) or accepted.get(stem) or {}).get("file")
                    if chosen and chosen != Path(c["path"]).name:
                        win = _payoff(files, web, chosen)
                        s0 = max(0.0, float(win[0]) - 0.3) if win else float(c.get("start", 0) or 0)
                        local_new = resolve(chosen)
                        dur = _duration(local_new) if local_new else None
                        if dur:
                            length = min(length, dur)
                            s0 = min(s0, max(0.0, dur - length))
                        c.update(path=chosen, start=round(s0, 2), end=round(s0 + length, 2))
                    local = resolve(Path(c["path"]).name)
                    if not local:
                        raise FileNotFoundError(f"clip not available: {Path(c['path']).name}")
                    c["path"] = str(local)
                    timeline += length
                elif c.get("image"):
                    local = resolve(Path(c["image"]).name)
                    if not local:
                        raise FileNotFoundError(f"still not available: {Path(c['image']).name}")
                    c["image"] = str(local)
                    timeline += float(c.get("duration") or (float(c.get("end", 0) or 0) - float(c.get("start", 0) or 0)) or 0)
                clips.append(c)
            if not any(c.get("path") or c.get("image") for c in clips):
                raise RuntimeError("every scene is left out: keep at least one")
            versions = [int(m.group(1)) for p in files.glob("final_edit_v*.mp4") if (m := re.match(r"final_edit_v(\d+)\.mp4$", p.name))]
            name = f"final_edit_v{1 + max(versions, default=0)}.mp4"
            caps = [{k: c.get(k) for k in ("text", "start", "end", "style", "position", "x", "animation", "approved_wording") if c.get(k) is not None}
                    for c in captions_doc.get("captions") or [] if c.get("enabled", True) and str(c.get("text", "")).strip()]
            insets = []
            for i in captions_doc.get("insets") or []:
                img = resolve(str(i.get("image", "")))
                if i.get("enabled", True) and img:
                    insets.append({**{k: v for k, v in i.items() if k not in ("id", "enabled")}, "image": str(img)})
            if drops:  # text that sat on a dropped scene goes with it; later text moves up
                kept = []
                for item in caps + insets:
                    a, b = _shift(float(item.get("start", 0)), drops), _shift(float(item.get("end", 0)), drops)
                    if b - a >= 0.4:
                        item.update(start=round(a, 2), end=round(b, 2))
                        kept.append(item)
                caps = [x for x in kept if x in caps]
                insets = [x for x in kept if x in insets]
            new = {"output": str(files / name), "clean_output": str(files / name.replace(".mp4", "_clean.mp4")),
                   "size": plan.get("size") or [480, 854], "fps": plan.get("fps") or 24, "clips": clips, "captions": caps, "insets": insets,
                   "reference_captions": plan.get("reference_captions") or [], "keep_clip_audio": True, "avoid_faces": False,
                   "outro": {"path": str(ASSEMBLY.parent / "assets" / "outro" / "macorner_outro.mp4")} if plan.get("outro") else False,
                   "preview_frames": 0}
            for c in new["captions"]:
                c["allow_over_subject"] = True
                c["approved_wording"] = True  # the user wrote or approved these words in the editor
            plan_file = d / "web_edit_plan.json"
            plan_file.write_text(json.dumps(new, ensure_ascii=False, indent=1))
            r = subprocess.run([sys.executable, str(ASSEMBLY / "assemble.py"), "--plan", str(plan_file)],
                               capture_output=True, text=True, timeout=1200, env={k: v for k, v in os.environ.items() if k != "ARK_API_KEY"})
            if r.returncode != 0:
                raise RuntimeError((r.stdout + r.stderr)[-500:])
            state.update(state="done", file=name)
            doc_file = d / "captions_doc.json"  # the caption editor now works on this cut's clean master
            doc = dict(captions_doc)
            doc["base"] = name.replace(".mp4", "_clean.mp4")
            if drops:  # the editor's times follow the shorter cut
                for key in ("captions", "insets"):
                    moved = []
                    for it in doc.get(key) or []:
                        a, b = _shift(float(it.get("start", 0)), drops), _shift(float(it.get("end", 0)), drops)
                        if b - a >= 0.4:
                            moved.append({**it, "start": round(a, 2), "end": round(b, 2)})
                    doc[key] = moved
                if doc.get("outro_start") is not None:
                    doc["outro_start"] = round(_shift(float(doc["outro_start"]), drops), 2)
            doc_file.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
            clean = name.replace(".mp4", "_clean.mp4")
            import captions as _cap
            thumb = _cap.make_thumb(files / name)
            keep = [(files / name, f"web_{name}"), (files / clean, f"web_{clean}"), (doc_file, "web_captions_doc.json")]
            keep += [(thumb, f"web_{thumb.name}")] if thumb else []
            for path, mount in keep:
                try:
                    persist(path, mount)
                except Exception as e:
                    state["warnings"].append(f"not kept in the agent session: {str(e)[:120]}")
        except Exception as e:
            state.update(state="failed", error=str(e)[:600])

    threading.Thread(target=work, daemon=True).start()
    return state
