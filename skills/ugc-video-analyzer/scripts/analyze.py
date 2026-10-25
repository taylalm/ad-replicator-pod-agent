#!/usr/bin/env python3
"""Prepare a sample UGC video for analysis: fetch it, probe it, split it into scenes,
save keyframes and timestamped contact sheets, and measure audio.

The script does the deterministic extraction only. The agent then looks at the
contact sheets and keyframes and writes analysis.json (see references/analysis_schema.md).

Usage:
  python3 analyze.py --source URL_OR_PATH [--out DIR] [--scene-threshold 0.3]
  python3 analyze.py --check /mnt/session/outputs/analysis/analysis.json
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

MAX_BYTES = 300 * 1024 * 1024
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm")


def out(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    sys.exit(code)


def fail(message, code=2):
    out({"ok": False, "error": message}, code)


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        from PIL import Image  # noqa: F401
    except ImportError:
        fail("Missing dependencies: run bash /mnt/skills/ugc-video-analyzer/scripts/ensure-deps.sh first")
    return imageio_ffmpeg.get_ffmpeg_exe()


def fetch(source, dest_dir):
    if os.path.isfile(source):
        if not source.lower().endswith(VIDEO_EXT):
            fail(f"Unsupported file type: {source}")
        return os.path.abspath(source), None
    if not source.startswith("https://"):
        fail("--source must be an existing local video file or an https:// URL to a video file")
    if re.search(r"(tiktok\.com|youtube\.com|youtu\.be|instagram\.com|facebook\.com)", source, re.I):
        fail("Social media page links cannot be downloaded from the sandbox (blocked by the platforms). "
             "Ask the user for a direct HTTPS link to the MP4 file (for example on TOS) or to upload the file.")
    dest = os.path.join(dest_dir, "source.mp4")
    request = urllib.request.Request(source, headers={"User-Agent": "Mozilla/5.0 (ugc-video-analyzer)"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(dest, "wb") as fh:
            ctype = response.headers.get("Content-Type", "")
            if "text/html" in ctype:
                fail(f"The URL returned a web page ({ctype}), not a video file. Use a direct link to the MP4.")
            total = 0
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BYTES:
                    fail("Video is larger than 300 MB; use a shorter or compressed file")
                fh.write(chunk)
    except SystemExit:
        raise
    except Exception as error:  # network or HTTP error
        fail(f"Download failed: {error}", 1)
    return dest, source


def probe(ff, path):
    proc = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True)
    text = proc.stderr
    info = {"duration_s": None, "width": None, "height": None, "fps": None, "has_audio": False}
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", text)
    if m:
        info["duration_s"] = round(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 3)
    m = re.search(r"Video: .*?(\d{2,5})x(\d{2,5})", text)
    if m:
        info["width"], info["height"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+(?:\.\d+)?) fps", text)
    if m:
        info["fps"] = float(m.group(1))
    info["has_audio"] = bool(re.search(r"Stream #\S+.*Audio:", text))
    if not info["duration_s"] or not info["width"]:
        fail(f"Not a readable video: {path}")
    w, h = info["width"], info["height"]
    info["orientation"] = "vertical" if h > w else ("horizontal" if w > h else "square")
    return info


def detect_scenes(ff, path, duration, threshold, min_len):
    proc = subprocess.run([ff, "-hide_banner", "-i", path, "-an", "-vf",
                           f"scale=270:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
                          capture_output=True, text=True)
    cuts = [float(t) for t in re.findall(r"pts_time:([\d.]+)", proc.stderr)]
    bounds = [0.0]
    for t in cuts:
        if t - bounds[-1] >= min_len and duration - t >= min_len:
            bounds.append(round(t, 3))
    bounds.append(round(duration, 3))
    return [{"index": i + 1, "start": bounds[i], "end": bounds[i + 1],
             "duration": round(bounds[i + 1] - bounds[i], 3)} for i in range(len(bounds) - 1)]


def grab(ff, path, t, dest, width=540):
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", path,
                    "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", dest], check=False)
    return os.path.isfile(dest)


def contact_sheets(ff, path, duration, out_dir, step, per_sheet=15, cols=5):
    from PIL import Image, ImageDraw, ImageFont
    tmp = os.path.join(out_dir, "_frames")
    os.makedirs(tmp, exist_ok=True)
    # One decoding pass: sample a frame every `step` seconds, already downscaled.
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", path, "-an",
                    "-vf", f"fps=1/{step},scale=320:-2", "-q:v", "4", os.path.join(tmp, "f_%03d.jpg")], check=False)
    files = sorted(f for f in os.listdir(tmp) if f.endswith(".jpg"))
    if not files:
        fail("Could not extract frames for the contact sheets")
    frames = [(round(i * step, 2), os.path.join(tmp, f)) for i, f in enumerate(files) if i * step < duration]
    sheets = []
    try:
        font = ImageFont.truetype(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                               "assets", "Poppins-Bold.ttf"), 22)
    except OSError:
        font = ImageFont.load_default()
    for s in range(0, len(frames), per_sheet):
        chunk = frames[s:s + per_sheet]
        first = Image.open(chunk[0][1])
        fw, fh = first.size
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * fw + (cols + 1) * 6, rows * fh + (rows + 1) * 6), "white")
        draw = ImageDraw.Draw(sheet)
        for k, (ts, f) in enumerate(chunk):
            img = Image.open(f).resize((fw, fh))
            x, y = 6 + (k % cols) * (fw + 6), 6 + (k // cols) * (fh + 6)
            sheet.paste(img, (x, y))
            label = f"{ts:.1f}s"
            draw.rectangle([x, y, x + 12 * len(label) + 12, y + 30], fill=(0, 0, 0))
            draw.text((x + 6, y + 3), label, fill=(255, 255, 255), font=font)
        name = os.path.join(out_dir, f"contact_sheet_{len(sheets) + 1:02d}.jpg")
        sheet.save(name, quality=85)
        sheets.append({"path": name, "from_s": chunk[0][0], "to_s": chunk[-1][0]})
    shutil.rmtree(tmp, ignore_errors=True)
    return sheets


def motion_scores(ff, path, scene, fps=5, w=64, h=114):
    """Measured movement in one scene: mean absolute change between consecutive small grey frames, in the outer ring
    of the frame (background: camera or vehicle moving) and in the centre (subject). Numbers, not judgement: a scene can
    look static on a contact sheet while the street behind a car window slides past."""
    t0, dur = scene["start"] + 0.15, max(0.3, scene["duration"] - 0.3)
    cmd = [ff, "-v", "error", "-ss", f"{t0:.2f}", "-t", f"{dur:.2f}", "-i", path, "-vf", f"fps={fps},scale={w}:{h},format=gray",
           "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (w * h)
    if n < 2:
        return None
    frames = [raw[i * w * h:(i + 1) * w * h] for i in range(n)]
    ring = [(x, y) for y in range(h) for x in range(w) if x < w * 0.2 or x >= w * 0.8 or y < h * 0.15 or y >= h * 0.85]
    centre = [(x, y) for y in range(int(h * 0.3), int(h * 0.7)) for x in range(int(w * 0.3), int(w * 0.7))]
    def diff(a, b, pts):
        return sum(abs(a[y * w + x] - b[y * w + x]) for x, y in pts) / len(pts)
    bg = sum(diff(a, b, ring) for a, b in zip(frames, frames[1:])) / (n - 1)
    fg = sum(diff(a, b, centre) for a, b in zip(frames, frames[1:])) / (n - 1)
    # calibrated on the balaclava sample (25 Oct 2026): driving-car selfie 26.9, walking camera 20.8, handheld
    # selfies and close-ups 11-16, locked-off cafe shot 5.3
    label = "static" if bg < 6 else ("handheld" if bg < 18 else "moving")
    return {"background": round(bg, 1), "subject": round(fg, 1), "background_label": label}


def watermark_sheet(ff, path, scenes, duration, out_dir):
    """Full-resolution, contrast-boosted corner crops: faint watermarks (AI-model marks such as
    'Veo', platform logos) are unreadable on the downscaled contact sheets."""
    from PIL import Image, ImageOps
    tmp = os.path.join(out_dir, "_wm")
    os.makedirs(tmp, exist_ok=True)
    times = sorted({round(s["start"] + s["duration"] / 2, 2) for s in scenes} | {round(max(0.0, duration - 0.3), 2)})
    rows = []
    for k, t in enumerate(times):
        f = os.path.join(tmp, f"wm_{k:02d}.png")
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", path,
                        "-frames:v", "1", f], check=False)
        if not os.path.isfile(f):
            continue
        im = Image.open(f).convert("L")
        w, h = im.size
        cw, ch = int(w * 0.30), int(h * 0.09)
        boxes = [(0, 0, cw, ch), (w - cw, 0, w, ch), (0, h - ch, cw, h), (w - cw, h - ch, w, h)]
        crops = [ImageOps.autocontrast(im.crop(b), cutoff=1).resize((cw * 2, ch * 2)) for b in boxes]
        rows.append((t, crops))
    if not rows:
        return None
    cw2, ch2 = rows[0][1][0].size
    sheet = Image.new("L", (cw2 * 4 + 50, (ch2 + 10) * len(rows)), 255)
    for r, (t, crops) in enumerate(rows):
        for c, crop in enumerate(crops):
            sheet.paste(crop.resize((cw2, ch2)), (c * (cw2 + 10), r * (ch2 + 10)))
    name = os.path.join(out_dir, "watermark_check.jpg")
    sheet.save(name, quality=90)
    shutil.rmtree(tmp, ignore_errors=True)
    return {"path": name, "times_s": [t for t, _ in rows],
            "layout": "one row per time; columns = top-left, top-right, bottom-left, bottom-right corner, zoomed 2x with boosted contrast"}


def audio_stats(ff, path):
    proc = subprocess.run([ff, "-hide_banner", "-i", path, "-vn", "-af",
                           "volumedetect,silencedetect=noise=-40dB:d=0.4", "-f", "null", "-"],
                          capture_output=True, text=True)
    text = proc.stderr
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", text)
    peak = re.search(r"max_volume: (-?[\d.]+) dB", text)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", text)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", text)]
    silences = [{"start": round(max(0.0, s), 2), "end": round(e, 2)} for s, e in zip(starts, ends)]
    return {"mean_volume_db": float(mean.group(1)) if mean else None,
            "max_volume_db": float(peak.group(1)) if peak else None,
            "silent_segments": silences,
            "note": "Volume and silence only. Whether the sound is speech, music or effects must be judged separately."}


REQUIRED = {
    "summary": str, "format": str, "hook": dict, "scenes": list, "on_screen_text": list,
    "product": dict, "people": list, "cast_count": int, "caption_style": dict, "shot_arc": list, "keep": list,
    "cta": dict, "style": dict, "do_not_copy": list, "replication_notes": list,
}


def check(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as error:
        fail(f"Cannot read {path}: {error}")
    problems = []
    for key, kind in REQUIRED.items():
        if key not in data:
            problems.append(f"missing '{key}'")
        elif not isinstance(data[key], kind):
            problems.append(f"'{key}' must be a {kind.__name__}")
    for i, scene in enumerate(data.get("scenes", []) if isinstance(data.get("scenes"), list) else []):
        for key in ("index", "start", "end", "description", "shot", "purpose", "camera_position", "pose", "motion", "product_state", "beats", "reactions", "staging_frame", "real_face_visible"):
            if key not in scene:
                problems.append(f"scenes[{i}] missing '{key}'")
        beats = scene.get("beats")
        if "beats" in scene and (not isinstance(beats, list) or not beats or not all(isinstance(b, dict) and "t" in b and "what" in b for b in beats)):
            problems.append(f"scenes[{i}].beats must be a non-empty list of {{t, what}}")
        elif isinstance(beats, list) and beats:
            try:
                if any(not (float(scene["start"]) - 0.3 <= float(b["t"]) <= float(scene["end"]) + 0.3) for b in beats):
                    problems.append(f"scenes[{i}].beats: every t must lie inside the scene ({scene['start']}-{scene['end']} s, video time)")
            except (TypeError, ValueError, KeyError):
                problems.append(f"scenes[{i}].beats: t must be a number")
        if "reactions" in scene and not isinstance(scene.get("reactions"), list):
            problems.append(f"scenes[{i}].reactions must be a list ([] when nobody reacts)")
    hook = data.get("hook") if isinstance(data.get("hook"), dict) else {}
    for key in ("start", "end", "type", "description"):
        if key not in hook:
            problems.append(f"hook missing '{key}'")
    cs = data.get("caption_style") if isinstance(data.get("caption_style"), dict) else {}
    for key in ("lines_max", "position", "size", "weight", "outline", "emoji"):
        if key not in cs:
            problems.append(f"caption_style missing '{key}'")
    if isinstance(data.get("cast_count"), int) and isinstance(data.get("people"), list):
        on_camera = [p for p in data["people"] if "hands only" not in str(p.get("description", "")).lower()]
        if data["cast_count"] != len(on_camera):
            problems.append(f"cast_count {data['cast_count']} does not match the {len(on_camera)} on-camera people listed")
    for i, item in enumerate(data.get("keep", []) if isinstance(data.get("keep"), list) else []):
        if not isinstance(item, str) or len(item) < 8:
            problems.append(f"keep[{i}] must be a descriptive sentence")
    if problems:
        out({"ok": False, "problems": problems}, 1)
    out({"ok": True, "scenes": len(data["scenes"]), "on_screen_text": len(data["on_screen_text"]), "cast_count": data["cast_count"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", help="https:// URL of a video file, or a local video path")
    parser.add_argument("--out", default="/mnt/session/outputs/analysis", help="Output folder")
    parser.add_argument("--scene-threshold", type=float, default=0.3, help="0-1, lower = more cuts (default 0.3)")
    parser.add_argument("--min-scene", type=float, default=0.6, help="Minimum scene length in seconds")
    parser.add_argument("--sheet-step", type=float, default=0.0,
                        help="Seconds between contact-sheet frames (default: 0.5 s if under 30 s, else 1 s)")
    parser.add_argument("--check", metavar="ANALYSIS_JSON", help="Validate an analysis.json written by the agent")
    args = parser.parse_args()
    if args.check:
        check(args.check)
    if not args.source:
        fail("--source is required")

    ff = ffmpeg_exe()
    os.makedirs(args.out, exist_ok=True)
    path, url = fetch(args.source, args.out)
    info = probe(ff, path)
    duration = info["duration_s"]
    scenes = detect_scenes(ff, path, duration, args.scene_threshold, args.min_scene)
    kf_dir = os.path.join(args.out, "keyframes")
    os.makedirs(kf_dir, exist_ok=True)
    for scene in scenes:
        mid = scene["start"] + scene["duration"] / 2
        kf = os.path.join(kf_dir, f"scene_{scene['index']:02d}_{mid:.1f}s.jpg")
        scene["keyframe"] = kf if grab(ff, path, mid, kf) else None
        first = os.path.join(kf_dir, f"scene_{scene['index']:02d}_start.jpg")
        scene["first_frame"] = first if grab(ff, path, scene["start"] + 0.05, first) else None
        scene["motion"] = motion_scores(ff, path, scene)
    step = args.sheet_step or (0.5 if duration <= 30 else 1.0)
    sheets = contact_sheets(ff, path, duration, args.out, step)
    audio = audio_stats(ff, path) if info["has_audio"] else None
    watermark = watermark_sheet(ff, path, scenes, duration, args.out)

    warnings = []
    if duration < 4 or duration > 30:
        warnings.append(f"Duration {duration:.1f} s is outside 4-30 s: Seedance 2.5 reference/edit videos must be 4-30 s; trim before using it as @Video1.")
    if info["orientation"] != "vertical":
        warnings.append("Source is not vertical 9:16; the replica will still be produced at 9:16.")
    if not url:
        warnings.append("Source is a local file: Seedance reference/edit mode needs a public HTTPS URL of the video.")
    if len(scenes) == 1:
        warnings.append("Only one scene detected: the video may be a single continuous shot, or try --scene-threshold 0.2.")

    raw = {"source": args.source, "source_url": url, "local_path": path, "video": info,
           "scene_threshold": args.scene_threshold, "scenes": scenes,
           "contact_sheets": sheets, "watermark_check": watermark, "audio": audio, "warnings": warnings}
    raw_path = os.path.join(args.out, "extraction.json")
    with open(raw_path, "w") as fh:
        json.dump(raw, fh, indent=2)
    out({"ok": True, "extraction": raw_path, "video": info, "scenes": len(scenes),
         "contact_sheets": [s["path"] for s in sheets],
         "keyframes": [s["keyframe"] for s in scenes],
         "watermark_check": watermark["path"] if watermark else None, "audio": audio, "warnings": warnings,
         "next": "View the contact sheets, keyframes and watermark_check.jpg, then write analysis.json per references/analysis_schema.md "
                 "and validate it with --check."})


if __name__ == "__main__":
    main()
