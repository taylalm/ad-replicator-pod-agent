"""Caption and inset editor for delivered ads: the document the editor works on (built from the agent's edit plan),
layer previews drawn with the same code as the agent's assembly, and exports onto the clean master.

The document lives in <job>/captions_doc.json. Exports are files/final_edit_v<n>.mp4. Both are also mounted in the
job's agent session (web_*), so a fresh serverless instance restores them (see sync.restore_web_files).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Dict, Optional

import store
from paths import REPO, load_module

ASSEMBLY = REPO / "skills" / "video-assembly" / "scripts"
_A = None
EXPORTS: Dict[str, dict] = {}  # job id -> {state: running|done|failed, file, error, warnings, started}


def assemble():
    global _A
    if _A is None:
        _A = load_module("assemble", ASSEMBLY / "assemble.py")
    return _A


def _local(d: Path, name: str, remote_url: Callable[[str], Optional[str]]) -> Optional[Path]:
    """A job file on this instance's disk, fetched from its presigned link first when it is only listed remotely."""
    path = store.files_dir(d) / Path(name).name
    if path.is_file():
        return path
    link = remote_url(Path(name).name)
    if not link:
        return None
    tmp = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(link, timeout=300) as r, open(tmp, "wb") as out:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(path)
    return path


def _plan(files_dir: Path) -> Optional[dict]:
    plans = sorted(files_dir.glob("edit_plan*.json"), key=lambda p: p.stat().st_mtime)
    for p in reversed(plans):
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            continue
    return None


def base_name(files_dir: Path, names: set, final_file: Optional[str]) -> Optional[str]:
    """The clean master of the delivered cut: final_clean.mp4, else <final>_clean.mp4."""
    if "final_clean.mp4" in names:
        return "final_clean.mp4"
    if final_file and final_file.replace(".mp4", "_clean.mp4") in names:
        return final_file.replace(".mp4", "_clean.mp4")
    cands = sorted(n for n in names if re.match(r"^final_v\d+_clean\.mp4$", n))
    return cands[-1] if cands else None


def build_doc(d: Path, names: set, final_file: Optional[str]) -> dict:
    """The editor document from the newest edit plan: captions with numeric positions, insets with local images."""
    files_dir = store.files_dir(d)
    plan = _plan(files_dir) or {}
    A = assemble()
    size = plan.get("size") or [480, 854]
    caps = []
    for i, c in enumerate(plan.get("captions") or []):
        pos = c.get("position") or A.PRESETS.get(c.get("style", "client"), A.PRESETS["client"]).get("position", "top")
        y = A.POSITIONS[pos] if pos in A.POSITIONS else float(pos)
        caps.append({"id": f"c{i + 1}", "text": c.get("text", ""), "start": float(c.get("start", 0)), "end": float(c.get("end", 0)),
                     "style": c.get("style", "client"), "position": round(y, 3), "x": float(c.get("x", 0.5)), "enabled": True,
                     "animation": c.get("animation") or plan.get("caption_animation") or {"in": "none", "out": "cut"},
                     **({"approved_wording": True} if c.get("approved_wording") else {})})
    insets = []
    for i, ins in enumerate(plan.get("insets") or []):
        img = Path(str(ins.get("image", ""))).name
        insets.append({"id": f"i{i + 1}", "image": img, "start": float(ins.get("start", 0)), "end": float(ins.get("end", 0)),
                       "position": ins.get("position", "top-right"), "top": float(ins.get("top", 0.24)), "left": ins.get("left"),
                       "width": float(ins.get("width", 0.34)), "arrow_to": ins.get("arrow_to"), "enabled": True})
    outro_start = None
    try:  # the editor keeps captions off the client outro
        clips_len = sum(float(c.get("end", 0)) - float(c.get("start", 0)) for c in plan.get("clips") or [] if c.get("end") is not None)
        outro_start = round(clips_len, 2) if plan.get("outro") and clips_len else None
    except (TypeError, ValueError):
        pass
    return {"version": 1, "size": size, "fps": int(plan.get("fps") or 24), "base": base_name(files_dir, names, final_file),
            "captions": caps, "insets": insets, "reference_captions": plan.get("reference_captions") or [], "outro_start": outro_start,
            "styles": sorted(A.PRESETS), "animations_in": list(A.ANIMATIONS_IN), "animations_out": list(A.ANIMATIONS_OUT)}


def doc_path(d: Path) -> Path:
    return d / "captions_doc.json"


def load_doc(d: Path, names: set, final_file: Optional[str]) -> dict:
    p = doc_path(d)
    if p.exists():
        try:
            doc = json.loads(p.read_text())
            doc.setdefault("base", base_name(store.files_dir(d), names, final_file))
            A = assemble()
            doc.update({"styles": sorted(A.PRESETS), "animations_in": list(A.ANIMATIONS_IN), "animations_out": list(A.ANIMATIONS_OUT)})
            return doc
        except (OSError, ValueError):
            pass
    return build_doc(d, names, final_file)


def save_doc(d: Path, doc: dict) -> dict:
    keep = {k: doc.get(k) for k in ("version", "size", "fps", "base", "captions", "insets", "reference_captions", "outro_start")}
    for c in keep.get("captions") or []:
        c["text"] = str(c.get("text", ""))[:110]
        c["x"] = min(0.85, max(0.15, float(c.get("x", 0.5))))
        c["position"] = min(0.92, max(0.04, float(c.get("position", 0.14))))
        if float(c.get("end", 0)) <= float(c.get("start", 0)):
            c["end"] = float(c.get("start", 0)) + 0.5
    doc_path(d).write_text(json.dumps(keep, indent=1, ensure_ascii=False))
    return keep


def _spec_item(item: dict, size) -> dict:
    A = assemble()
    cap = {k: item.get(k) for k in ("style", "x") if item.get(k) is not None}
    cap["position"] = float(item.get("position", 0.14))
    cap["text"] = str(item.get("text", ""))
    return A.caption_spec(cap, tuple(size))


def preview_png(d: Path, doc: dict, kind: str, item: dict, out_path: Path, remote_url) -> Path:
    """One caption or inset as a full-frame transparent PNG at the video size (what the export will draw)."""
    A = assemble()
    size = tuple(doc.get("size") or (480, 854))
    if kind == "inset":
        img = _local(d, item.get("image", ""), remote_url)
        if not img:
            raise FileNotFoundError(item.get("image"))
        box = A.render_inset_layer(str(out_path), size, {**item, "image": str(img)})
    else:
        A.render_caption_layer(str(out_path), size, str(item.get("text", "")), _spec_item(item, size))
        from PIL import Image
        with Image.open(out_path) as im:
            box = im.getbbox()
    box = box or (0, 0, 0, 0)
    # the grab area for the editor, as fractions of the frame (the inset's photo, not its arrow)
    (out_path.with_suffix(".box")).write_text(",".join(f"{v / (size[0] if k % 2 == 0 else size[1]):.4f}" for k, v in enumerate(box)))
    return out_path


def make_thumb(video: Path) -> Optional[Path]:
    """A frame of a new version for the History card (final_edit_vN_thumb.jpg)."""
    try:
        import imageio_ffmpeg
        out = video.with_name(video.stem + "_thumb.jpg")
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-ss", "1.0", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=360:-2,format=yuvj420p", "-q:v", "4", str(out)], check=False, timeout=60)
        return out if out.exists() else None
    except Exception:
        return None


def next_version(files_dir: Path) -> int:
    nums = [int(m.group(1)) for p in files_dir.glob("final_edit_v*.mp4") if (m := re.match(r"final_edit_v(\d+)\.mp4$", p.name))]
    return max(nums, default=0) + 1


def start_export(job_id: str, d: Path, doc: dict, remote_url, persist: Callable[[Path, str], None]) -> dict:
    """Renders files/final_edit_v<n>.mp4 in a background thread; poll EXPORTS[job_id]."""
    if EXPORTS.get(job_id, {}).get("state") == "running":
        return EXPORTS[job_id]
    state = {"state": "running", "started": time.time(), "file": None, "error": None, "warnings": []}
    EXPORTS[job_id] = state

    def work():
        try:
            files_dir = store.files_dir(d)
            base = _local(d, doc.get("base") or "", remote_url)
            if not base:
                raise RuntimeError("the clean master (final without text) is not available for this job")
            run_doc = json.loads(json.dumps(doc))
            for ins in run_doc.get("insets") or []:
                img = _local(d, ins.get("image", ""), remote_url)
                ins["image"] = str(img) if img else ""
            tmp_doc = d / "captions_doc.render.json"
            tmp_doc.write_text(json.dumps(run_doc, ensure_ascii=False))
            name = f"final_edit_v{next_version(files_dir)}.mp4"
            r = subprocess.run([sys.executable, str(ASSEMBLY / "overlay.py"), "--base", str(base), "--doc", str(tmp_doc),
                                "--output", str(files_dir / name)], capture_output=True, text=True, timeout=900)
            res = json.loads(r.stdout[r.stdout.find("{"):]) if "{" in r.stdout else {}
            if r.returncode != 0 or not res.get("ok"):
                raise RuntimeError((res.get("error") or r.stderr or r.stdout)[-400:])
            state.update(state="done", file=name, warnings=res.get("warnings") or [])
            thumb = make_thumb(files_dir / name)
            keep = [(files_dir / name, f"web_{name}"), (doc_path(d), "web_captions_doc.json")] + ([(thumb, f"web_{thumb.name}")] if thumb else [])
            for path, mount in keep:
                try:
                    persist(path, mount)
                except Exception as e:  # the export exists here; only the copy in the agent session failed
                    state["warnings"].append(f"not kept in the agent session ({mount}): {str(e)[:120]}")
        except Exception as e:
            state.update(state="failed", error=str(e)[:500])

    threading.Thread(target=work, daemon=True).start()
    return state
