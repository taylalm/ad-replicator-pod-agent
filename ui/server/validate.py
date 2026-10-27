"""Server-side check of a sample-video link without downloading the whole file."""
from __future__ import annotations

import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

SOCIAL = {
    "tiktok.com": "TikTok", "vm.tiktok.com": "TikTok", "instagram.com": "Instagram", "youtube.com": "YouTube",
    "youtu.be": "YouTube", "facebook.com": "Facebook", "fb.watch": "Facebook", "fb.com": "Facebook", "x.com": "X", "twitter.com": "X",
}
UPLOAD_ONLY = {"TikTok"}  # tested 26 Oct 2026: HTTP 403 from the veFaaS function, fine from a home connection
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm")


def _host_matches(host: str, pattern: str) -> bool:
    return host == pattern or host.endswith("." + pattern)


def social_platform(url: str) -> Optional[str]:
    """'TikTok', 'YouTube', ... when the link is a post on a social site (the web server downloads those), else None."""
    try:
        p = urllib.parse.urlparse((url or "").strip())
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https"):
        return None
    return next((label for pat, label in SOCIAL.items() if _host_matches(host, pat)), None)


def validate_sample(url: str, timeout: float = 10.0) -> dict:
    url = (url or "").strip()
    out = {"ok": False, "reason": None, "content_type": None, "size_bytes": None, "status": None}
    if not url:
        out["reason"] = "Paste the link to your sample video."
        return out
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        out["reason"] = "This does not look like a web link."
        return out
    host = (p.hostname or "").lower()
    label = social_platform(url)
    if label in UPLOAD_ONLY:  # the site refuses these from the cloud (TikTok answers 403 to datacenter addresses)
        out["reason"] = (f"{label} does not allow our server to download its videos. Save the video from {label} "
                         "(Save video / Download) and upload the MP4 file instead.")
        return out
    if label:  # the site downloads it (social.py); the agent gets the file, never the link
        out.update(ok=True, social=label)
        return out
    if p.scheme != "https":
        out["reason"] = "The link must start with https:// (plain http links cannot be fetched by the agent)."
        return out
    if not host:
        out["reason"] = "The link has no host name."
        return out
    path_lower = p.path.lower()
    has_video_ext = path_lower.endswith(VIDEO_EXT)

    def request(method: str, headers: dict):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, **headers})
        return urllib.request.urlopen(req, timeout=timeout)

    resp = None
    err: Optional[str] = None
    try:
        resp = request("HEAD", {})
    except urllib.error.HTTPError as e:
        if e.code in (403, 405, 501):
            try:
                resp = request("GET", {"Range": "bytes=0-0"})
            except urllib.error.HTTPError as e2:
                err = f"HTTP {e2.code}"
                out["status"] = e2.code
        else:
            err = f"HTTP {e.code}"
            out["status"] = e.code
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        err = str(getattr(e, "reason", e))[:120]
    if resp is None:
        if out["status"] in (401, 403):
            out["reason"] = "The file needs a login or is private. Make it readable without credentials (a public or presigned link)."
        elif out["status"] == 404:
            out["reason"] = "Nothing was found at this link (404). Check the address."
        elif out["status"] == 429:
            out["reason"] = "The host is rate-limiting requests right now. Try again in a minute."
        else:
            out["reason"] = f"The link could not be reached ({err or 'unknown error'})."
        return out
    with resp:
        out["status"] = resp.status
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        out["content_type"] = ctype or None
        size = resp.headers.get("Content-Length")
        crange = resp.headers.get("Content-Range")
        if crange and "/" in crange:
            tail = crange.split("/")[-1].strip()
            if tail.isdigit():
                size = tail
        if size and str(size).isdigit():
            out["size_bytes"] = int(size)
            if resp.status == 206 and not crange:
                out["size_bytes"] = None
    is_video = ctype.startswith("video/") or (ctype in ("application/octet-stream", "binary/octet-stream", "") and has_video_ext) or has_video_ext
    if ctype.startswith("text/html"):
        out["reason"] = "This link opens a web page, not a video file. Paste the direct link to the MP4 file."
        return out
    if not is_video:
        out["reason"] = f"This link does not point to a video (content type {ctype or 'unknown'}). Paste a direct MP4 or MOV link."
        return out
    if out["size_bytes"] and out["size_bytes"] > 500 * 1024 * 1024:
        out["reason"] = "The file is larger than 500 MB. Use a shorter or compressed sample."
        return out
    out["ok"] = True
    out["reason"] = "Looks good: a direct video link that opens without a login."
    return out


def is_https_url(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(url.strip())
    except ValueError:
        return False
    return p.scheme == "https" and bool(p.hostname) and re.match(r"^[A-Za-z0-9.-]+$", p.hostname or "") is not None
