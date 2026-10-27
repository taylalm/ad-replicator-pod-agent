"""Sample videos from social links (TikTok, Facebook Reels, YouTube, Instagram, X): the web server downloads the public
video with yt-dlp and hands it on like an uploaded file, so the agent gets an ordinary MP4 in its session uploads.

The agent's sandbox cannot do this (bot protection on those sites), the web server can. One download per request, no
login, public posts only. The result is H.264/AAC MP4 (what browsers, the analyzer and ffmpeg all read): yt-dlp prefers
H.264 formats and anything else (H.265, AV1, VP9) is converted with the bundled ffmpeg.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, Optional

from validate import social_platform

MAX_SECONDS = 180          # sample ads are short; longer posts are refused before downloading
MAX_BYTES = 300 * 1024 * 1024
JOBS: Dict[str, dict] = {}  # id -> {state, progress, platform, url, title, duration, size, ref, error, started}
_LOCK = threading.Lock()


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _video_codec(path: Path) -> str:
    """The first video stream's codec name from ffmpeg's stream listing (no ffprobe in the bundle)."""
    r = subprocess.run([_ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=60)
    m = re.search(r"Stream #\S+.*?Video: (\w+)", r.stderr)
    return m.group(1) if m else ""


def _to_h264(src: Path) -> Path:
    out = src.with_name(src.stem + "_h264.mp4")
    subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)],
                   check=True, timeout=600)
    src.unlink(missing_ok=True)
    return out


def _short_title(info: dict) -> Optional[str]:
    """A readable name for the post: its title (Facebook puts the whole caption there), first line, at most 70 characters."""
    t = str(info.get("title") or info.get("description") or "").strip()
    t = re.sub(r"^[\d.,]+[KM]? (reactions|views|likes)[^|]*\|\s*", "", t)  # Facebook prefixes "35K reactions · 5.5K shares |"
    t = t.splitlines()[0] if t else ""
    return (t[:67].rstrip() + "…") if len(t) > 70 else (t or None)


def _friendly(err: str, platform: str) -> str:
    e = err.lower()
    if "private" in e or "login" in e or "log in" in e or "sign in" in e or "cookies" in e:
        return f"{platform} wants a login for this video. Use a public post, or download the video yourself and upload the file."
    if "429" in e or "rate" in e:
        return f"{platform} is limiting requests right now. Try again in a few minutes, or upload the file."
    if "unavailable" in e or "removed" in e or "not found" in e or "404" in e:
        return f"This {platform} video is not available (removed, private or region-locked)."
    if "unsupported url" in e:
        return "This link is not a single video post. Open the video itself and copy its link."
    return f"The video could not be downloaded from {platform}. Try again, or download it yourself and upload the file. ({err[:160]})"


def start(url: str, workdir: Path, send: Callable[[Path, str, str], dict]) -> dict:
    """Starts a download; poll get(id). send(path, safe_name, note) uploads the finished file (main._send_upload)."""
    platform = social_platform(url)
    from validate import UPLOAD_ONLY
    if platform in UPLOAD_ONLY:
        raise ValueError(f"{platform} videos must be uploaded as a file.")
    if not platform:
        raise ValueError("Not a TikTok, Facebook, Instagram, YouTube or X video link.")
    jid = uuid.uuid4().hex[:12]
    state = {"id": jid, "state": "starting", "progress": 0.0, "platform": platform, "url": url, "title": None, "duration": None,
             "size": None, "ref": None, "error": None, "started": time.time()}
    with _LOCK:
        JOBS[jid] = state

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                state["progress"] = round(min(0.99, d.get("downloaded_bytes", 0) / total), 3)

    def work():
        try:
            import yt_dlp
            workdir.mkdir(parents=True, exist_ok=True)
            base = {"noplaylist": True, "quiet": True, "no_warnings": True, "noprogress": True, "socket_timeout": 30}
            state["state"] = "reading"
            with yt_dlp.YoutubeDL(base) as y:
                info = y.extract_info(url, download=False)
            if info.get("_type") == "playlist":
                raise RuntimeError("unsupported url: a playlist or profile, not one video")
            dur = info.get("duration")
            state.update(title=_short_title(info), duration=dur)
            if dur and dur > MAX_SECONDS:
                raise RuntimeError(f"too long: {dur:.0f} s (samples up to {MAX_SECONDS} s)")
            state["state"] = "downloading"
            vid = re.sub(r"[^A-Za-z0-9]", "", str(info.get("id") or jid))[:40]
            stem = f"{int(time.time())}_{platform.lower()}_{vid}"
            opts = {**base, "outtmpl": str(workdir / f"{stem}.%(ext)s"), "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
                    "format_sort": ["vcodec:h264", "res:1080", "acodec:aac", "ext:mp4:m4a"], "merge_output_format": "mp4",
                    "ffmpeg_location": _ffmpeg(), "max_filesize": MAX_BYTES, "progress_hooks": [hook]}
            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(url, download=True)
                path = Path((info.get("requested_downloads") or [{}])[0].get("filepath") or y.prepare_filename(info))
            if not path.exists():
                raise RuntimeError("the download finished without a file (it may be larger than the limit)")
            state.update(state="converting", progress=1.0)
            if _video_codec(path) != "h264" or path.suffix.lower() != ".mp4":
                path = _to_h264(path)
            state.update(state="uploading", size=path.stat().st_size)
            safe = f"{platform.lower()}_{vid}.mp4"
            try:
                ref = send(path, safe, f"sample video from {platform}: {url}")
            except Exception as e:  # downloaded fine; only the hand-off to ModelArk failed
                detail = getattr(e, "detail", None) or str(e)
                state.update(state="failed", error=f"The video was downloaded but could not be sent to ModelArk: {str(detail)[:200]}")
                return
            ref["source_url"] = url
            state.update(state="done", ref=ref)
        except Exception as e:
            state.update(state="failed", error=_friendly(str(e), platform))

    threading.Thread(target=work, daemon=True).start()
    return state


def get(jid: str) -> Optional[dict]:
    return JOBS.get(jid)
