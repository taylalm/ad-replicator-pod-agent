#!/usr/bin/env python3
"""Independent C1-C8 quality gate for generated UGC ads.

Samples frames from the final video (and optional clips), builds timestamped contact sheets,
sends them with the AI person references and product previews to a vision model via the
ModelArk Chat API (POST /chat/completions, image_url content blocks per the image-understanding
tutorial), and writes report.json / report.md with scores, hard failures and retry routing.

Usage:
  python3 gate.py --video final.mp4 --context context.json --out DIR [--clip clip.mp4 ...]
                  [--model seed-2-0-lite-260428] [--max-frames 10] [--dry-run]
"""
import argparse
import base64
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

DEFAULT_MODEL = "seed-2-0-lite-260428"
DEFAULT_BASE = "https://ark.ap-southeast.bytepluses.com/api/v3"
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRITERIA = {
    "C1": "Character: the AI people look natural and friendly (everyday look, no glamour, no AI artefacts such as extra fingers, melted faces, glowing eyes), the same person stays consistent across shots and matches the reference image, and faces are visible: a product or caption covering a face in a shot where the sample shows the face caps this score at 3.",
    "C2": "Personalisation: the personalized elements (name spelling, photo/avatar, chosen options) are correct, legible and match the product preview exactly. When several personalized items appear together, EACH item must carry only its own person's portrait and name as in that person's preview: a portrait or name from another person, two different names on one item, or a misspelled or invented name (e.g. 'Rula' for 'Mila') is wrong_personalization or misspelled_name, a hard failure. Same LAYOUT rule (the same side/area carries the same element; a mirrored or swapped layout, e.g. the animal on the left sole when the preview has it on the right, is wrong_personalization). If the preview shows a photo, cartoon or avatar of the person, that portrait must be visible on the product in the video at the same scale as in the preview (a full-body figure in the preview must be a full-body figure in the video; a bust or a name-only product is wrong_personalization, a hard failure).",
    "C3": "Setting: the environment matches the sample's mood brief (home, lighting, authenticity); nothing luxurious, surreal or inconsistent.",
    "C4": "Hook: the first 2-3 seconds stop the scroll (clear subject, relatable moment, product or reveal appears early) and the hook caption is readable. Captions throughout must be short (1-2 lines), in the top band, and never cover a face or the personalized area; captions over faces or longer than 2 lines cap this score at 3.",
    "C5": "Hook-product link: the hook leads naturally to the product; the product answers the hook's situation; no mismatch of emotion or subject.",
    "C6": "Product visuals: the product is accurate and not deformed (right type, colours, shape); its SIZE relative to people matches the real product (a 50x60 inch blanket held up by a child is taller than the child; a towel-sized or doll-sized product is deformed_product, a hard failure); the design stays the same across shots, text on it is not garbled or mirrored, and the material and all-over pattern match the product-page gallery images (e.g. the bookshelf leg pattern of the socks, the sherpa lining of the blanket); a generic or different pattern caps this score at 3.",
    "C7": "Highlight customisation: the personalized area is shown clearly and long enough (a close, focused shot) so a viewer understands what was customised.",
    "C8": "CTA: a clear call to action with the right wording (product name + where to personalize), no prices unless provided, disclaimer present if required.",
}
ROUTING = {"C1": "04_people (regenerate the AI person image)", "C2": "05_personalize or the clip prompt (wrong/illegible personalization)",
           "C3": "06_prompts (setting in the failing clip prompt)", "C4": "06_prompts (hook clip) or 08_assembly (hook caption)",
           "C5": "06_prompts (hook clip)", "C6": "06_prompts (product description / reference in the failing clip)",
           "C7": "06_prompts (add a close-up of the personalized area) or 05_personalize", "C8": "08_assembly (end card / captions / disclaimer)"}
HARD_FAIL_KINDS = ["misspelled_name", "other_brand", "profanity", "rude_gesture", "deformed_product", "wrong_personalization",
                   "platform_ui", "watermark", "unsafe_content", "cast_count_mismatch", "no_audio", "copied_caption",
                   "caption_covers_personalization", "caption_covers_face"]


def out(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    sys.exit(code)


def fail(message, code=2, **extra):
    out({"ok": False, "error": message, **extra}, code)


def deps():
    try:
        import imageio_ffmpeg
        from PIL import Image  # noqa: F401
    except ImportError:
        fail("Missing dependencies: run bash /mnt/skills/ugc-quality-gate/scripts/ensure-deps.sh first")
    return imageio_ffmpeg.get_ffmpeg_exe()


def audio_level(ff, path):
    """Mean volume in dB of the audio track, or None when there is no audio stream."""
    proc = subprocess.run([ff, "-hide_banner", "-i", path, "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", proc.stderr)
    if not m:
        return None
    return float(m.group(1))


def probe(ff, path):
    proc = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True)
    text = proc.stderr
    info = {"path": path, "duration_s": None, "width": None, "height": None, "has_audio": bool(re.search(r"Audio:", text))}
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", text)
    if m:
        info["duration_s"] = round(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 2)
    m = re.search(r"Video: .*?(\d{2,5})x(\d{2,5})", text)
    if m:
        info["width"], info["height"] = int(m.group(1)), int(m.group(2))
    if not info["duration_s"] or not info["width"]:
        fail(f"Not a readable video: {path}")
    return info


def sample_frames(ff, path, duration, n, tmp, label):
    frames = []
    times = [0.4] + [duration * (k + 0.5) / n for k in range(n)] + [max(0.2, duration - 0.6)]
    times = sorted(set(round(t, 2) for t in times if 0 <= t < duration))
    for i, t in enumerate(times):
        dest = os.path.join(tmp, f"{label}_{i:02d}.jpg")
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", path,
                        "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "4", dest], check=False)
        if os.path.isfile(dest):
            frames.append((t, dest))
    return frames


def contact_sheet(frames, dest, cols=4, title=""):
    from PIL import Image, ImageDraw, ImageFont
    if not frames:
        return None
    first = Image.open(frames[0][1])
    fw, fh = first.size
    rows = math.ceil(len(frames) / cols)
    pad = 6
    sheet = Image.new("RGB", (cols * fw + (cols + 1) * pad, rows * fh + (rows + 1) * pad + 30), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except OSError:
        font = ImageFont.load_default()
    draw.text((pad, 4), title, fill="black", font=font)
    for i, (t, p) in enumerate(frames):
        r, c = divmod(i, cols)
        x, y = pad + c * (fw + pad), 30 + pad + r * (fh + pad)
        sheet.paste(Image.open(p), (x, y))
        draw.rectangle([x, y, x + 78, y + 26], fill=(0, 0, 0))
        draw.text((x + 4, y + 3), f"t={t:.1f}s", fill="yellow", font=font)
    sheet.save(dest, quality=85)
    return dest


def corner_zoom_sheet(ff, path, duration, dest, tmp):
    """Full-resolution corner crops of three late frames, contrast-boosted: faint watermarks and
    small logos are invisible on downscaled contact sheets (lesson from the sample analysis)."""
    from PIL import Image, ImageOps, ImageDraw
    times = sorted(set(max(0.1, t) for t in (duration * 0.5, duration - 1.5, duration - 0.3)))
    tiles = []
    for i, t in enumerate(times):
        full = os.path.join(tmp, f"corner_{i}.png")
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", full], check=False)
        if not os.path.isfile(full):
            continue
        im = Image.open(full).convert("RGB")
        w, h = im.size
        cw, ch = int(w * 0.32), int(h * 0.14)
        for name, box in (("TL", (0, 0, cw, ch)), ("TR", (w - cw, 0, w, ch)), ("BL", (0, h - ch, cw, h)), ("BR", (w - cw, h - ch, w, h))):
            crop = ImageOps.autocontrast(im.crop(box), cutoff=2).resize((360, int(360 * ch / cw)))
            ImageDraw.Draw(crop).text((4, 2), f"{name} t={t:.1f}s", fill="red")
            tiles.append(crop)
    if not tiles:
        return None
    tw, th = tiles[0].size
    cols = 4
    rows = math.ceil(len(tiles) / cols)
    sheet = Image.new("RGB", (cols * (tw + 4), rows * (th + 4)), "white")
    for i, tile in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet.paste(tile, (c * (tw + 4), r * (th + 4)))
    sheet.save(dest, quality=88)
    return dest


def data_url(path, max_side=768):
    from PIL import Image
    import io
    with Image.open(path) as im:
        im = im.convert("RGB")
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def build_messages(ctx, sheets, clip_sheets, video_info, deterministic):
    rubric = "\n".join(f"{k}: {v}" for k, v in CRITERIA.items())
    system = (
        "You are a strict advertising quality reviewer for a print-on-demand personalized gifts brand. "
        "You judge AI-generated vertical (9:16) UGC-style ads frame by frame. Be concrete, cite frame timestamps as evidence, "
        "never give the benefit of the doubt on text spelling, product deformation or anything unsafe for an ad. "
        "Score each criterion 1-5 (5 = flawless, 4 = minor cosmetic issue, 3 = noticeable problem, 2 = clearly wrong, 1 = unusable).\n\n"
        "Criteria:\n" + rubric + "\n\n"
        "Hard failures (any one makes the ad unusable regardless of scores): " + ", ".join(HARD_FAIL_KINDS) + ".\n"
        "If the context lists accepted_risks (product-art details the client has explicitly accepted for this ad), do not report those "
        "specific details as hard failures; list what you observe about them under accepted_risk_observations instead. accepted_risks never "
        "cover names or portraits: a wrong, swapped, mixed or misspelled name or portrait is always a hard failure.\n"
        "Respond with ONLY a JSON object, no prose, with this shape:\n"
        '{"scores": {"C1": {"score": 1-5, "reason": "...", "evidence": "t=..s"}, ... "C8": {...}},\n'
        ' "hard_failures": [{"kind": "<one of the hard failure kinds>", "detail": "...", "evidence": "t=..s"}],\n'
        ' "visible_text": ["every piece of text you can read on the product or in the frames"],\n'
        ' "people_count": <number of distinct people seen in the ad, excluding hands-only shots>,\n'
        ' "caption_issues": ["captions covering faces, more than 2 lines, too large, unreadable"],\n'
        ' "accepted_risk_observations": ["..."],\n'
        ' "people_consistent": true/false, "product_matches_preview": true/false,\n'
        ' "summary": "two sentences"}'
    )
    lines = [f"Product: {ctx.get('product_name', '?')}",
             f"Expected personalization: {json.dumps(ctx.get('product_previews', []), ensure_ascii=False)}",
             f"Expected text that must appear exactly: {ctx.get('expected_text', [])}",
             f"Captions burned into the video (expected): {ctx.get('captions', [])}",
             f"CTA expected: {ctx.get('cta_text', '')} | Disclaimer expected: {ctx.get('disclaimer_text', '')} "
             "(the disclaimer is a small text pill burned in by our own editor, usually near the top; it is expected and is NOT a watermark or logo)",
             f"Client brand: {ctx.get('client_brand', 'macorner')}. The closing outro card with this brand's logo, service badges and AI-performer note is the client's own fixed outro, appended on purpose: it is correct and never other_brand, and it counts as part of the CTA together with any approved offer lines {ctx.get('offer_lines', [])}.",
             f"Setting brief: {ctx.get('setting_brief', '')}", f"Hook brief: {ctx.get('hook_brief', '')}",
             f"Product layout from the website preview (must match, not mirrored): {ctx.get('product_layout', '')}",
             f"Expected number of people (same as the sample): {ctx.get('cast_count_expected', 'n/a')}",
             f"Must NOT appear: {ctx.get('do_not_copy', [])} and {ctx.get('forbidden', [])}",
             f"Accepted risks (client decision, not hard failures): {ctx.get('accepted_risks', [])}",
             f"Video facts: {video_info}", f"Deterministic checks: {deterministic}",
             "Images follow: first the AI person reference(s), then the product preview(s), then timestamped contact sheets of the ad"
             + (" and of individual clips" if clip_sheets else "") + ". Compare faces with the references and the product with the previews."]
    content = [{"type": "text", "text": "\n".join(lines)}]
    for p in ctx.get("people", []):
        if p.get("image") and os.path.isfile(p["image"]):
            content.append({"type": "text", "text": f"AI person reference for {p.get('name', '?')} ({p.get('role', '')}):"})
            content.append({"type": "image_url", "image_url": {"url": data_url(p["image"], 512)}})
    for pv in ctx.get("product_previews", []):
        if pv.get("image") and os.path.isfile(pv["image"]):
            content.append({"type": "text", "text": f"Product preview for {pv.get('for', '?')}: {pv.get('expected', '')}"})
            content.append({"type": "image_url", "image_url": {"url": data_url(pv["image"], 768)}})
    for g in ctx.get("gallery_images", [])[:3]:
        if g and os.path.isfile(g):
            content.append({"type": "text", "text": f"Product-page gallery image (material / pattern reference): {os.path.basename(g)}"})
            content.append({"type": "image_url", "image_url": {"url": data_url(g, 640)}})
    for title, sheet in sheets:
        content.append({"type": "text", "text": title})
        content.append({"type": "image_url", "image_url": {"url": data_url(sheet, 1400)}})
    for title, sheet in clip_sheets:
        content.append({"type": "text", "text": title})
        content.append({"type": "image_url", "image_url": {"url": data_url(sheet, 1200)}})
    content.append({"type": "text", "text": "Now return the JSON object."})
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


def call_model(base, key, model, messages, max_tokens=4000):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.1}
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                last = f"HTTP {e.code}: {txt[:300]}"
                time.sleep(8 * (attempt + 1))
                continue
            fail(f"Evaluator call failed: HTTP {e.code}: {txt[:600]}", 1)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = str(e)
            time.sleep(8 * (attempt + 1))
    fail(f"Evaluator call failed after retries: {last}", 1)


def parse_json(text):
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def verify_text_claims(hard, ctx, ff, video, base, key, model, tmp):
    """Second opinion on name/text hard failures (misspelled, mirrored, reversed). The whole-ad evaluator reads small
    brush lettering from contact sheets and sometimes reports a correct name as mirrored or misspelled. Each such claim
    is re-read on full-size frames at its evidence timestamps next to the product previews; a claim that no frame
    supports becomes a disputed observation instead of a hard failure. Returns (kept, disputed, extra_calls)."""
    claim_re = re.compile(r"mirror|revers|backward|flipp|misspel|spell|letter", re.I)
    previews = [pv for pv in ctx.get("product_previews", []) if pv.get("image") and os.path.isfile(pv["image"])]
    expected = [t for t in ctx.get("expected_text", []) if t]
    kept, disputed, calls = [], [], 0
    for h in hard:
        if h.get("kind") not in ("wrong_personalization", "misspelled_name") or not claim_re.search(str(h.get("detail", ""))) or not previews:
            kept.append(h)
            continue
        times = [float(t) for t in re.findall(r"t\s*=\s*(\d+(?:\.\d+)?)", str(h.get("evidence", "")))][:3]
        if not times:
            kept.append(h)
            continue
        content = [{"type": "text", "text": "Image 1 (and the following preview images) show the product exactly as the client's website renders it. "
                                             f"The text that must appear on it: {expected}. Then come frames from the ad. For EACH frame, read the "
                                             "personalized text printed on the product letter by letter, left to right, and say whether it is mirrored "
                                             "(reads right-to-left / letters flipped) or misspelled compared with the website preview. Stylized "
                                             "handwriting, script fonts and perspective are NOT mirroring. Reply with ONLY JSON: "
                                             '{"frames": [{"t": 3.6, "reads": "...", "mirrored": false, "misspelled": false}]}'}]
        for pv in previews[:3]:
            content.append({"type": "image_url", "image_url": {"url": data_url(pv["image"], 768)}})
        for t in times:
            frame = os.path.join(tmp, f"verify_{t:.2f}.jpg")
            subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-q:v", "3", frame], check=False)
            if os.path.isfile(frame):
                content.append({"type": "text", "text": f"Ad frame at t={t}s:"})
                content.append({"type": "image_url", "image_url": {"url": data_url(frame, 1024)}})
        try:
            resp = call_model(base, key, model, [{"role": "user", "content": content}], max_tokens=800)
            calls += 1
            data = parse_json(resp["choices"][0]["message"]["content"] if isinstance(resp["choices"][0]["message"]["content"], str)
                              else "".join(c.get("text", "") for c in resp["choices"][0]["message"]["content"])) or {}
        except SystemExit:
            data = {}
        frames = data.get("frames") or []
        # A real mirror or misspelling is printed the same way in every frame of the shot it is in, so most evidence frames show
        # it; a misreading (stylized letters, rotated or folded fabric) usually hits one frame. Tested 23 Oct 2026 on a correct
        # ad (1 of 3 frames flagged) and on the same ad flipped left-right (3 of 3 flagged).
        flagged = [f for f in frames if f.get("mirrored") or f.get("misspelled")]
        confirmed = flagged if len(flagged) * 2 >= max(1, len(frames)) else []
        if frames and not confirmed:
            disputed.append({**h, "second_opinion": frames})
        else:
            kept.append({**h, **({"second_opinion": frames} if frames else {})})
    return kept, disputed, calls


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True, help="final video (mp4)")
    ap.add_argument("--clip", action="append", default=[], help="individual clip(s) to score as well")
    ap.add_argument("--context", required=True, help="context.json (see SKILL.md)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=os.environ.get("QUALITY_GATE_MODEL", DEFAULT_MODEL))
    ap.add_argument("--max-frames", type=int, default=10)
    ap.add_argument("--pass-threshold", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tag", help="file name tag (default: the --out folder's basename, e.g. round_1); output files are report_<tag>.json/.md")
    args = ap.parse_args()
    tag = re.sub(r"[^A-Za-z0-9_-]+", "_", args.tag or os.path.basename(os.path.normpath(args.out)) or "round_1")

    try:
        with open(args.context) as fh:
            ctx = json.load(fh)
    except (OSError, json.JSONDecodeError) as error:
        fail(f"Cannot read context: {error}")
    if not os.path.isfile(args.video):
        fail(f"Video not found: {args.video}")
    ff = deps()
    os.makedirs(args.out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="gate_frames_")  # outside outputs/, so sampled frames are not synced as outputs

    info = probe(ff, args.video)
    deterministic = []
    ratio = info["width"] / info["height"]
    if abs(ratio - 9 / 16) > 0.02:
        deterministic.append(f"aspect ratio {info['width']}x{info['height']} is not 9:16")
    if info["duration_s"] < 6:
        deterministic.append(f"video is only {info['duration_s']} s")
    if info["duration_s"] > 60:
        deterministic.append(f"video is {info['duration_s']} s (long for a UGC ad)")
    for p in ctx.get("people", []):
        if p.get("image") and not os.path.isfile(p["image"]):
            deterministic.append(f"person reference missing: {p['image']}")
    for pv in ctx.get("product_previews", []):
        if pv.get("image") and not os.path.isfile(pv["image"]):
            deterministic.append(f"product preview missing: {pv['image']}")

    n = max(4, min(args.max_frames, int(math.ceil(info["duration_s"]))))
    frames = sample_frames(ff, args.video, info["duration_s"], n, tmp, "final")
    sheets = []
    for i in range(0, len(frames), 8):
        chunk = frames[i:i + 8]
        dest = os.path.join(args.out, f"quality_{tag}_sheet_{i // 8 + 1:02d}.jpg")
        contact_sheet(chunk, dest, cols=4, title=f"final video frames {chunk[0][0]:.1f}s-{chunk[-1][0]:.1f}s")
        sheets.append((f"Final video contact sheet {i // 8 + 1} (frames {chunk[0][0]:.1f}s to {chunk[-1][0]:.1f}s):", dest))
    corners = corner_zoom_sheet(ff, args.video, info["duration_s"], os.path.join(args.out, f"quality_{tag}_corners.jpg"), tmp)
    if corners:
        sheets.append(("Corner zooms (contrast-boosted) of late frames: check for watermarks, AI-model marks, logos or platform UI. "
                       "Our own burned-in disclaimer pill and captions may appear here; they are expected:", corners))
    clip_sheets, clip_infos = [], []
    for ci, clip in enumerate(args.clip, 1):
        if not os.path.isfile(clip):
            deterministic.append(f"clip missing: {clip}")
            continue
        cinfo = probe(ff, clip)
        clip_infos.append(cinfo)
        cframes = sample_frames(ff, clip, cinfo["duration_s"], 4, tmp, f"clip{ci}")
        dest = os.path.join(args.out, f"quality_{tag}_clip_{ci:02d}.jpg")
        contact_sheet(cframes, dest, cols=3, title=os.path.basename(clip))
        clip_sheets.append((f"Clip {ci} ({os.path.basename(clip)}, {cinfo['duration_s']} s):", dest))

    messages = build_messages(ctx, sheets, clip_sheets, {**info, "clips": clip_infos}, deterministic)
    n_images = sum(1 for c in messages[1]["content"] if c.get("type") == "image_url")
    if args.dry_run:
        shown = json.loads(json.dumps(messages))
        for c in shown[1]["content"]:
            if c.get("type") == "image_url":
                c["image_url"]["url"] = c["image_url"]["url"][:40] + "...(base64)"
        out({"ok": True, "dry_run": True, "model": args.model, "images": n_images, "contact_sheets": [s[1] for s in sheets + clip_sheets],
             "deterministic": deterministic, "request_preview": shown})

    key = os.environ.get("ARK_API_KEY")
    if not key:
        fail("ARK_API_KEY is not available in the environment")
    base = os.environ.get("ARK_BASE_URL", DEFAULT_BASE)
    t0 = time.time()
    resp = call_model(base, key, args.model, messages)
    text = ""
    try:
        text = resp["choices"][0]["message"]["content"]
        if isinstance(text, list):
            text = "".join(c.get("text", "") for c in text)
    except (KeyError, IndexError, TypeError):
        fail("Unexpected evaluator response shape", 1, response=str(resp)[:800])
    parsed = parse_json(text)
    if not parsed or "scores" not in parsed:
        fail("Evaluator did not return the expected JSON", 1, raw=text[:1500])

    scores = {}
    for k in CRITERIA:
        s = parsed["scores"].get(k) or {}
        try:
            val = int(round(float(s.get("score", 0))))
        except (TypeError, ValueError):
            val = 0
        scores[k] = {"score": max(0, min(5, val)), "reason": str(s.get("reason", ""))[:400], "evidence": str(s.get("evidence", ""))[:120]}
    hard = [h for h in parsed.get("hard_failures", []) if isinstance(h, dict) and h.get("kind")]
    # captions must be new wording, never the sample's (or a reference ad's): deterministic check on the planned captions
    import difflib
    refs = [str(t) for t in ctx.get("reference_captions", []) if str(t).strip()]
    approved = {str(t).strip().lower() for t in ctx.get("offer_lines", [])}
    words = lambda t: re.findall(r"[a-z0-9%']+", str(t).lower())  # noqa: E731
    for cap in ctx.get("captions", []):
        if str(cap).strip().lower() in approved:
            continue
        cw = words(cap)
        grams = {tuple(cw[k:k + 4]) for k in range(len(cw) - 3)}
        for ref in refs:
            rw = words(ref)
            ratio = difflib.SequenceMatcher(None, " ".join(cw), " ".join(rw)).ratio() if cw and rw else 0
            if ratio >= 0.6 or grams & {tuple(rw[k:k + 4]) for k in range(len(rw) - 3)}:
                hard.append({"kind": "copied_caption", "detail": f"caption '{cap}' copies the reference caption '{ref}'", "evidence": "edit plan"})
                break
    # deterministic name check on what the evaluator read
    visible = [str(t) for t in parsed.get("visible_text", [])]
    expected = [t for t in ctx.get("expected_text", []) if t]
    vis_norm = re.sub(r"[^a-z0-9 ]+", " ", " ".join(visible).lower())
    vis_norm = re.sub(r"\s+", " ", vis_norm)

    def _seen(t):
        """Fuzzy: the evaluator's OCR of brush lettering drops or swaps a letter now and then; accept >= 85% similarity."""
        import difflib
        tt = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t.lower())).strip()
        if not tt or tt in vis_norm:
            return True
        words = vis_norm.split()
        n = max(1, len(tt.split()))
        for i in range(0, max(1, len(words) - n + 1)):
            window = " ".join(words[i:i + n])
            if difflib.SequenceMatcher(None, tt, window).ratio() >= 0.85:
                return True
        return False

    missing = [t for t in expected[:2] if not _seen(t)]  # the first entries are the main design; variants may fall between samples
    if expected and visible and missing and scores["C2"]["score"] >= args.pass_threshold:
        scores["C2"]["score"] = min(scores["C2"]["score"], 3)
        scores["C2"]["reason"] += f" | script: expected text {missing} not among the text the evaluator read {visible[:6]}"
    if ctx.get("audio_required", True):
        mean_db = audio_level(ff, args.video)
        if mean_db is None or mean_db < -60:
            hard.append({"kind": "no_audio", "detail": f"the video has no audible track (mean {mean_db} dB); the client's ads carry music and natural sound", "evidence": "audio stream"})
    expected_people = ctx.get("cast_count_expected")
    seen_people = parsed.get("people_count")
    if isinstance(expected_people, int) and isinstance(seen_people, int) and seen_people != expected_people \
            and not any(h.get("kind") == "cast_count_mismatch" for h in hard):
        hard.append({"kind": "cast_count_mismatch", "detail": f"the ad shows {seen_people} people but the sample has {expected_people}", "evidence": "evaluator count"})
    caption_issues = [str(c) for c in parsed.get("caption_issues", []) if c]
    if caption_issues and scores["C4"]["score"] > 3:
        scores["C4"]["score"] = 3
        scores["C4"]["reason"] += " | caption issues: " + "; ".join(caption_issues)[:200]
    hard, disputed, verify_calls = verify_text_claims(hard, ctx, ff, args.video, base, key, args.model, tmp)
    if disputed and scores["C2"]["score"] < args.pass_threshold and not any(h.get("kind") in ("wrong_personalization", "misspelled_name") for h in hard) \
            and re.search(r"mirror|revers|backward|flipp|misspel|spell|letter", scores["C2"]["reason"], re.I):
        # the low C2 rested on the same text claim the second reading disproved
        scores["C2"]["score"] = args.pass_threshold
        scores["C2"]["reason"] += " | raised: the text claim was disputed by a second reading of full-size frames (" + "; ".join(d.get("detail", "")[:80] for d in disputed) + ")"
    failing = [k for k, v in scores.items() if v["score"] < args.pass_threshold]
    verdict = "PASS" if not failing and not hard and not [d for d in deterministic if "not 9:16" in d] else "FAIL"
    routing = [{"criterion": k, "score": scores[k]["score"], "redo": ROUTING[k], "reason": scores[k]["reason"]} for k in failing]
    for h in hard:
        kind = h.get("kind")
        step = {"misspelled_name": "05_personalize / 06_prompts", "wrong_personalization": "05_personalize or 06_prompts (layout / portrait scale)", "deformed_product": "06_prompts",
                "cast_count_mismatch": "03_plan (cast must equal the sample's cast_count) then 04_people / 06_prompts", "no_audio": "08_assembly (music / sfx / keep_clip_audio)",
                "other_brand": "06_prompts or 08_assembly", "copied_caption": "08_assembly (rewrite the caption in new words)",
                "caption_covers_personalization": "08_assembly (move the caption to a band clear of the printed name/design)",
                "caption_covers_face": "08_assembly (move the caption to a band clear of faces)", "profanity": "05_personalize (choose another option) or 08_assembly",
                "rude_gesture": "05_personalize (choose another artwork)", "platform_ui": "06_prompts", "watermark": "06_prompts",
                "unsafe_content": "04_people / 06_prompts"}.get(kind, "review")
        routing.append({"hard_failure": kind, "redo": step, "reason": h.get("detail", ""), "evidence": h.get("evidence", "")})
    usage = resp.get("usage", {})
    report = {"ok": True, "verdict": verdict, "tag": tag, "model": args.model, "video": info, "clips": clip_infos, "scores": scores,
              "hard_failures": hard, "disputed_failures": disputed, "second_opinion_calls": verify_calls,
              "deterministic_checks": deterministic, "visible_text": visible,
              "accepted_risks": ctx.get("accepted_risks", []), "accepted_risk_observations": parsed.get("accepted_risk_observations", []),
              "people_count": seen_people, "cast_count_expected": expected_people, "caption_issues": caption_issues,
              "people_consistent": parsed.get("people_consistent"), "product_matches_preview": parsed.get("product_matches_preview"),
              "summary": parsed.get("summary", ""), "routing": routing, "min_score": min(v["score"] for v in scores.values()),
              "contact_sheets": [s[1] for s in sheets + clip_sheets], "evaluator_usage": usage, "elapsed_s": round(time.time() - t0, 1)}
    with open(os.path.join(args.out, f"report_{tag}.json"), "w") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    md = [f"# Quality gate: {verdict}", "", report["summary"], "", "| Criterion | Score | Reason | Evidence |", "|---|---|---|---|"]
    md += [f"| {k} | {v['score']}/5 | {v['reason']} | {v['evidence']} |" for k, v in scores.items()]
    if hard:
        md += ["", "## Hard failures"] + [f"- **{h.get('kind')}**: {h.get('detail', '')} ({h.get('evidence', '')})" for h in hard]
    if routing:
        md += ["", "## Routing"] + [f"- {json.dumps(r, ensure_ascii=False)}" for r in routing]
    if deterministic:
        md += ["", "## Deterministic checks"] + [f"- {d}" for d in deterministic]
    md += ["", f"Visible text read by the evaluator: {visible}", f"Model: {args.model}; usage: {usage}"]
    with open(os.path.join(args.out, f"report_{tag}.md"), "w") as fh:
        fh.write("\n".join(md) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("video", "clips")}, indent=2, ensure_ascii=False))
    sys.exit(0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
