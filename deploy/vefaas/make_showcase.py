#!/usr/bin/env python3
"""Read-only showcase copies of delivered jobs for a cloud deployment.

ModelArk keeps a session's files downloadable for only about a day (older ones return HTTP 403), so a fresh cloud
instance cannot rebuild older jobs from the API. This copies the local job folder into <dest>/<job-id>/ with:
  - job.json marked "frozen" (no syncing, no messages),
  - events trimmed (long tool outputs cut; step messages, prompts and usage kept),
  - costs.json / cost_cache.json as computed locally,
  - files: everything except superseded video takes and raw task videos; images over 300 KB re-encoded as 1080 px JPEG
    data under the same file name (every reference keeps working; the server sends the real image type).
  - internal check images, debug screenshots and the duplicate final left out.
Usage: python3 make_showcase.py <ui/data/jobs> <dest> <job-id> [<job-id> ...]
"""
import json
import re
import shutil
import sys
from pathlib import Path

SRC, DEST, IDS = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ui" / "server"))

from PIL import Image  # noqa: E402

import store  # noqa: E402
from derive import derive_job  # noqa: E402

MAX_TEXT = 4000
BIG = 300_000      # images above this are re-encoded as 1080 px JPEG data (same file name; the server sniffs the type)
HIDDEN = re.compile(r"^(check_|quality_round_\d+_(sheet|corners)|after_step_|probe_page|error_step|form_|wm_\d+|frame_clip_)", re.I)


def link_ok(url: str) -> bool:
    """True when the sample's public link still serves the video (links can disappear: then ship the local copy)."""
    if not url.startswith("https://"):
        return False
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-15"}), timeout=20) as r:
            return r.status in (200, 206)
    except Exception:
        return False


def trim(v):
    if isinstance(v, str):
        return v if len(v) <= MAX_TEXT else v[:MAX_TEXT] + f"\n... [{len(v) - MAX_TEXT} more chars]"
    if isinstance(v, list):
        return [trim(x) for x in v]
    if isinstance(v, dict):
        return {k: trim(x) for k, x in v.items()}
    return v


for job_id in IDS:
    src = SRC / job_id
    dst = DEST / job_id
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "files").mkdir(parents=True)
    job = json.loads((src / "job.json").read_text())
    events = store.read_events(src)
    derived = derive_job(job, events, src / "files")
    keep_video = {c["file"] for c in derived["clips"]} | {"final.mp4", "final_clean.mp4"}
    if not link_ok(str((job.get("inputs") or {}).get("sample_url", ""))):
        keep_video |= {"sample.mp4", "source.mp4"}  # otherwise the player streams the sample from its public link
    if derived.get("finals") and not (src / "files" / "final.mp4").exists():
        keep_video.add(derived["finals"][-1]["file"])
    job.update({"frozen": True, "status": derived["status"]})
    job["files_index"] = {}
    (dst / "job.json").write_text(json.dumps(job, indent=1))
    (dst / "events.json").write_text(json.dumps({"events": [trim(e) for e in events]}))
    if (src / "costs.json").exists():  # times only: no prices or amounts leave the operator's machine
        c = json.loads((src / "costs.json").read_text())
        (dst / "costs.json").write_text(json.dumps({k: c.get(k) for k in ("production_s", "steps", "waiting_s")}))
    kept = shrunk = skipped = 0
    for p in sorted((src / "files").iterdir()):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() in (".mp4", ".mov", ".webm") and p.name not in keep_video:
            skipped += 1
            continue
        if p.name.startswith("cgt-") or HIDDEN.match(p.name):
            skipped += 1
            continue
        out = dst / "files" / p.name
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and p.stat().st_size > BIG:
            try:
                im = Image.open(p)
                im.thumbnail((1080, 1080))
                if im.mode not in ("RGB", "L"):
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.convert("RGBA").split()[-1])
                    im = bg
                im.save(out, format="JPEG", quality=84, optimize=True)
                shrunk += 1
                kept += 1
                continue
            except Exception:
                pass
        if p.suffix.lower() in (".mp4", ".mov") and p.stat().st_size > 8_000_000:
            try:  # an oversized sample video: 720 px wide H.264 for the side-by-side player only
                import subprocess
                import imageio_ffmpeg
                subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(p), "-vf", "scale='min(720,iw)':-2",
                                "-c:v", "libx264", "-crf", "26", "-preset", "veryfast", "-c:a", "aac", "-b:a", "96k",
                                "-movflags", "+faststart", str(out)], check=True)
                shrunk += 1
                kept += 1
                continue
            except Exception:
                pass
        shutil.copyfile(p, out)
        kept += 1
    size = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file())
    print(f"[showcase] {job_id}: {kept} files ({shrunk} images scaled), {skipped} superseded videos left out, {size / 1e6:.0f} MB")
