#!/usr/bin/env python3
"""Assemble a vertical ad from generated clips and stills: trim, scale, concatenate, burn in captions
(client caption presets, 1-2 lines, top band), overlay photo insets with an arrow, append the client's
fixed outro, and mix music / sound effects / the clips' own audio.

Text is rendered with Pillow as transparent PNGs and placed with ffmpeg's overlay filter,
because the imageio-ffmpeg static build has no drawtext filter.

Usage:
  python3 assemble.py --plan plan.json [--dry-run]
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = {
    "bold": os.path.join(SKILL_DIR, "assets", "fonts", "Poppins-Bold.ttf"),
    "semibold": os.path.join(SKILL_DIR, "assets", "fonts", "Poppins-SemiBold.ttf"),
    "regular": os.path.join(SKILL_DIR, "assets", "fonts", "Poppins-Regular.ttf"),
    "heavy_italic": os.path.join(SKILL_DIR, "assets", "fonts", "Poppins-ExtraBoldItalic.ttf"),
}
DEFAULT_OUTRO = os.path.join(SKILL_DIR, "assets", "outro", "macorner_outro.mp4")
POSITIONS = {"top": 0.14, "upper": 0.22, "middle": 0.50, "lower": 0.66, "bottom": 0.74}
# Caption presets measured on the client's manual ads (client_output_blanket_1.mp4 / _socks_1.mp4):
# small bold sans with a thin dark outline in the top band, 1-2 lines; yellow italic-looking bold with a
# dark outline for offers; a dark pill for feature lines; big white with a red outline for the final CTA.
PRESETS = {
    "client": {"size": 0.031, "weight": "bold", "style": "outline", "color": "#FFFFFF", "stroke_color": "#111111", "stroke": 0.12, "position": "top", "max_lines": 2},
    "offer": {"size": 0.034, "weight": "bold", "style": "outline", "color": "#FFE94A", "stroke_color": "#2A1A00", "stroke": 0.16, "position": "top", "max_lines": 2},
    "pill": {"size": 0.028, "weight": "semibold", "style": "box", "color": "#FFFFFF", "box_color": "#1F1F1FCC", "position": "top", "max_lines": 2},
    "cta": {"size": 0.050, "weight": "bold", "style": "outline", "color": "#FFFFFF", "stroke_color": "#C8102E", "stroke": 0.14, "position": "upper", "max_lines": 2},
    "outline": {"size": 0.040, "weight": "bold", "style": "outline", "color": "#FFFFFF", "stroke_color": "#000000", "stroke": 0.08, "position": "top", "max_lines": 3},
    "box": {"size": 0.040, "weight": "bold", "style": "box", "color": "#FFFFFF", "box_color": "#000000B3", "position": "top", "max_lines": 3},
    # styles seen in the client's own finished ads (expected outputs, 22 Oct 2026)
    "offer_italic": {"size": 0.036, "weight": "heavy_italic", "style": "outline", "color": "#FFE94A", "stroke_color": "#2A1A00", "stroke": 0.14, "position": "top", "max_lines": 2},
    "shop_now": {"size": 0.058, "weight": "heavy_italic", "style": "outline", "color": "#FFFFFF", "stroke_color": "#C8102E", "stroke": 0.13, "position": "upper", "max_lines": 2},
    "promo_pink": {"size": 0.029, "weight": "bold", "style": "box", "color": "#FFFFFF", "box_color": "#E2336BF2", "position": "top", "max_lines": 2},
    "pov_box": {"size": 0.029, "weight": "bold", "style": "box", "color": "#FFFFFF", "box_color": "#000000F0", "position": "top", "max_lines": 3},
}
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")


def fail(message, code=2):
    print(json.dumps({"ok": False, "error": message}))
    sys.exit(code)


def load_deps():
    try:
        import imageio_ffmpeg  # noqa: F401
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
    except ImportError:
        fail("Missing dependencies: run bash /mnt/skills/video-assembly/scripts/ensure-deps.sh first")
    import imageio_ffmpeg
    return imageio_ffmpeg


def hex_rgba(value, alpha=255):
    value = value.lstrip("#")
    if len(value) == 8:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4, 6))
    if len(value) != 6:
        fail(f"Invalid colour {value!r}; use #RRGGBB or #RRGGBBAA")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def num(value, name, minimum=None):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        fail(f"{name} must be a number")
    if minimum is not None and value < minimum:
        fail(f"{name} must be >= {minimum}")
    return float(value)


def caption_spec(cap, size):
    """Resolve a caption against its preset. Sizes in presets are fractions of the frame width."""
    width = size[0]
    preset = PRESETS.get(cap.get("style", "client"))
    if preset is None:
        fail(f"captions style must be one of {sorted(PRESETS)}")
    spec = dict(preset)
    spec.update({k: v for k, v in cap.items() if k in ("weight", "color", "stroke_color", "box_color", "position", "max_lines", "x")})
    spec["font_size"] = int(cap["size"]) if cap.get("size") else max(int(width * preset["size"]), int(width * 0.044))
    pos = spec["position"]
    spec["y"] = POSITIONS[pos] if pos in POSITIONS else float(pos)
    spec["render_style"] = "box" if spec["style"] == "box" else "outline"
    spec["stroke_px"] = max(2, int(spec["font_size"] * spec.get("stroke", 0.1))) if spec["render_style"] == "outline" else 0
    return spec


def _words(text):
    return re.findall(r"[a-z0-9%']+", str(text).lower().replace("\u2019", "'"))


def copied_from(text, refs, ratio=0.6, ngram=4):
    """(reference, reason) when a caption is too close to a reference caption: similar overall wording, or a shared run of
    4+ words (e.g. 'just arrived and my kids'). Captions must always be new wording, never the sample's."""
    import difflib
    w = _words(text)
    grams = {tuple(w[k:k + ngram]) for k in range(len(w) - ngram + 1)}
    for ref in refs:
        rw = _words(ref)
        if not rw or not w:
            continue
        r = difflib.SequenceMatcher(None, " ".join(w), " ".join(rw)).ratio()
        if r >= ratio:
            return ref, f"{int(r * 100)}% similar"
        shared = grams & {tuple(rw[k:k + ngram]) for k in range(len(rw) - ngram + 1)}
        if shared:
            return ref, "shares the words '" + " ".join(sorted(shared)[0]) + "'"
    return None


def validate(plan, dry_run):
    warnings = []
    if not isinstance(plan, dict):
        fail("Plan must be a JSON object")
    if not plan.get("output"):
        fail("plan.output is required, e.g. /mnt/session/outputs/08_assembly/final_v1.mp4")
    size = plan.get("size", [1080, 1920])
    if not (isinstance(size, list) and len(size) == 2 and all(isinstance(v, int) and v % 2 == 0 and v > 0 for v in size)):
        fail("plan.size must be [width, height] with even integers")
    plan["size"] = size
    plan["fps"] = int(plan.get("fps", 30))
    clips = plan.get("clips")
    if not isinstance(clips, list) or not clips:
        fail("plan.clips must be a non-empty list of {path, start?, end?} or {image, duration, zoom?}")
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            fail(f"clips[{i}] must be an object")
        if clip.get("image"):
            if not os.path.isfile(clip["image"]):
                (warnings.append if dry_run else fail)(f"clips[{i}].image not found: {clip['image']}")
            num(clip.get("duration", 2.5), f"clips[{i}].duration", 0.5)
            if clip.get("zoom") is not None:
                num(clip["zoom"], f"clips[{i}].zoom", 1.0)
            if clip.get("fit", "contain") not in ("contain", "cover"):
                fail(f"clips[{i}].fit must be contain or cover")
            continue
        if clip.get("path") and clip.get("zoom") is not None:
            num(clip["zoom"], f"clips[{i}].zoom", 1.0)
        if not clip.get("path"):
            fail(f"clips[{i}].path (video) or clips[{i}].image (still) is required")
        if not os.path.isfile(clip["path"]):
            (warnings.append if dry_run else fail)(f"clips[{i}].path not found: {clip['path']}")
        start = num(clip.get("start", 0), f"clips[{i}].start", 0)
        if clip.get("end") is not None and num(clip["end"], f"clips[{i}].end") <= start:
            fail(f"clips[{i}].end must be greater than start")
    refs = [str(t) for t in plan.get("reference_captions", []) if str(t).strip()]
    if plan.get("captions") and not refs:
        warnings.append("plan.reference_captions is empty: list the sample's (and any reference ad's) on-screen text so copied captions are caught")
    for i, cap in enumerate(plan.get("captions", [])):
        if not cap.get("text"):
            fail(f"captions[{i}].text is required")
        if refs and not cap.get("approved_wording"):
            hit = copied_from(str(cap["text"]), refs)
            if hit:
                fail(f"captions[{i}] copies the reference caption \"{hit[0]}\" ({hit[1]}): write the caption in new words; "
                     "only client-approved offer lines may keep their wording (mark them approved_wording: true)")
        start = num(cap.get("start"), f"captions[{i}].start", 0)
        if num(cap.get("end"), f"captions[{i}].end") <= start:
            fail(f"captions[{i}].end must be greater than start")
        spec = caption_spec(cap, plan["size"])
        if not (0.04 <= spec["y"] <= 0.80):
            fail(f"captions[{i}].position must be top, upper, middle, lower, bottom or a number between 0.04 and 0.80")
        if spec["y"] > 0.30 and not cap.get("allow_over_subject"):
            warnings.append(f"captions[{i}] sits at {spec['y']:.2f} of the frame height; the client keeps captions in the top band above faces (set allow_over_subject: true to override)")
        anim = cap.get("animation") or plan.get("caption_animation") or {}
        if anim and (anim.get("in", "none") not in ANIMATIONS_IN or anim.get("out", "cut") not in ANIMATIONS_OUT):
            fail(f"captions[{i}].animation: in must be one of {list(ANIMATIONS_IN)}, out one of {list(ANIMATIONS_OUT)}")
        if cap.get("x") is not None and not 0.15 <= float(cap["x"]) <= 0.85:
            fail(f"captions[{i}].x must be between 0.15 and 0.85 (horizontal centre of the caption)")
        if len(str(cap["text"])) > 110:
            fail(f"captions[{i}] is {len(cap['text'])} characters; keep captions to 1-2 short lines (about 70 characters)")
        try:  # same wrap as the renderer, so --dry-run catches 3-line captions
            from PIL import Image, ImageDraw, ImageFont
            draw = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
            font = ImageFont.truetype(FONTS.get(spec["weight"], FONTS["bold"]), spec["font_size"])
            n_lines = len(wrap(draw, cap["text"], font, int(plan["size"][0] * 0.84), spec["stroke_px"]))
            if n_lines > int(spec.get("max_lines", 2)):
                fail(f"captions[{i}] wraps to {n_lines} lines (max {spec.get('max_lines', 2)}): shorten it")
        except ImportError:
            pass
    for i, ins in enumerate(plan.get("insets", [])):
        if not ins.get("image"):
            fail(f"insets[{i}].image is required")
        if not os.path.isfile(ins["image"]):
            (warnings.append if dry_run else fail)(f"insets[{i}].image not found: {ins['image']}")
        start = num(ins.get("start"), f"insets[{i}].start", 0)
        if num(ins.get("end"), f"insets[{i}].end") <= start:
            fail(f"insets[{i}].end must be greater than start")
        if ins.get("arrow_to") is not None:
            if not (isinstance(ins["arrow_to"], list) and len(ins["arrow_to"]) == 2):
                fail(f"insets[{i}].arrow_to must be [x, y] fractions of the frame")
    card = plan.get("end_card")
    outro = plan.get("outro")
    if outro is True or outro == {}:
        outro = {"path": DEFAULT_OUTRO}
        plan["outro"] = outro
    if outro:
        path = outro.get("path") or DEFAULT_OUTRO
        outro["path"] = path
        if not os.path.isfile(path):
            (warnings.append if dry_run else fail)(f"outro.path not found: {path}")
        if card:
            warnings.append("Both outro and end_card set: the outro is the client's fixed ending; drop end_card unless asked.")
    if card:
        num(card.get("duration", 3), "end_card.duration", 0.5)
        if card.get("image") and not os.path.isfile(card["image"]):
            (warnings.append if dry_run else fail)(f"end_card.image not found: {card['image']}")
        if not card.get("lines") and not card.get("image"):
            fail("end_card needs lines and/or image")
    if not card and not outro:
        warnings.append("No outro and no end_card: the ad will end on the last clip.")
    music = plan.get("music")
    if music:
        if not music.get("path"):
            fail("music.path is required when music is set")
        if not os.path.isfile(music["path"]):
            (warnings.append if dry_run else fail)(f"music.path not found: {music['path']}")
    for i, sfx in enumerate(plan.get("sfx", [])):
        if not sfx.get("path") or not os.path.isfile(sfx["path"]):
            (warnings.append if dry_run else fail)(f"sfx[{i}].path not found: {sfx.get('path')}")
        num(sfx.get("start", 0), f"sfx[{i}].start", 0)
    if not music and not plan.get("sfx") and not plan.get("keep_clip_audio"):
        warnings.append("No audio source (music, sfx or keep_clip_audio): the video gets a silent track. The client's ads have music and natural sound.")
    if plan.get("disclaimer") and outro:
        warnings.append("Disclaimer set although the outro already carries the AI line; remove plan.disclaimer unless the client wants both.")
    return warnings


def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        fail(f"ffmpeg failed ({proc.returncode}): {' '.join(cmd[:6])} ... :: {proc.stderr[-1500:]}", 1)
    return proc


def wrap(draw, text, font, max_width, stroke):
    lines = []
    for paragraph in str(text).split("\n"):
        words, line = paragraph.split(), ""
        for word in words:
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) + 2 * stroke <= max_width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U0001F900-\U0001F9FF⭐⭕‼⁉™ℹ↔-↙↩↪⌚⌛⌨⏏⏩-⏳⏸-⏺Ⓜ▪▫▶◀◻-◾⤴⤵⬅-⬇⬛⬜〰〽㊗㊙❤❣♥♦♠♣️‍]+")
# bundled first (Noto Color Emoji 2.057, SIL OFL 1.1, assets/fonts/NotoColorEmoji-OFL.txt) so every machine draws the same emoji
EMOJI_FONT_PATHS = (os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fonts", "NotoColorEmoji.ttf"),
                    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", "/System/Library/Fonts/Apple Color Emoji.ttc")


def emoji_font():
    """Noto Color Emoji is a bitmap font that FreeType renders at size 109 only; glyphs are scaled afterwards."""
    from PIL import ImageFont
    for candidate in EMOJI_FONT_PATHS:
        if os.path.isfile(candidate):
            for size in (109, 160, 96):  # Noto Color Emoji: 109; Apple Color Emoji (macOS): 160 or 96
                try:
                    return ImageFont.truetype(candidate, size)
                except OSError:
                    continue
    return None


def strip_emoji(text):
    return re.sub(r"\s{2,}", " ", EMOJI_RE.sub("", text)).strip()


def split_runs(line):
    """Split a line into [(is_emoji, text)] runs so emoji can be drawn with the colour font."""
    runs, pos = [], 0
    for m in EMOJI_RE.finditer(line):
        if m.start() > pos:
            runs.append((False, line[pos:m.start()]))
        runs.append((True, m.group(0)))
        pos = m.end()
    if pos < len(line):
        runs.append((False, line[pos:]))
    return runs


def caption_units(text):
    """Number of reveal steps of a caption: letters (spaces included) with every emoji cluster counted as one."""
    return sum(len(EMOJI_RE.findall(r)) if e else len(r) for e, r in split_runs(str(text).replace("\n", " ")))


def render_caption_layer(path, size, text, spec, margin=0.08, reveal=None):
    """Render one caption with its resolved preset. Emoji are drawn with Noto Color Emoji when the font is
    installed (ensure-deps.sh), otherwise dropped. Returns the number of lines drawn.
    spec["x"] (0-1, default 0.5) is the horizontal centre. reveal=n draws only the first n letters/emoji in the
    final line layout (typewriter and word-by-word steps keep every letter where the full caption puts it)."""
    from PIL import Image, ImageDraw, ImageFont
    width, height = size
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = ImageFont.truetype(FONTS.get(spec["weight"], FONTS["bold"]), spec["font_size"])
    efont = emoji_font()
    if efont is None:
        text = strip_emoji(text)
    stroke = spec["stroke_px"]
    glyph = int(spec["font_size"] * 1.15)
    # wrap on the plain text, measuring emoji as one glyph each
    def measure(t):
        return sum(draw.textlength(r, font=font) if not e else glyph * len(EMOJI_RE.findall(r)) for e, r in split_runs(t))
    lines, cur = [], ""
    for word in str(text).replace("\n", " \n ").split(" "):
        if word == "\n":
            lines.append(cur); cur = ""; continue
        trial = f"{cur} {word}".strip()
        if measure(trial) + 2 * stroke <= int(width * (1 - 2 * margin)) or not cur:
            cur = trial
        else:
            lines.append(cur); cur = word
    lines.append(cur)
    lines = [l for l in lines if l.strip()]
    if len(lines) > int(spec.get("max_lines", 2)):
        fail(f"Caption wraps to {len(lines)} lines (max {spec.get('max_lines', 2)}): shorten it: {text!r}")
    line_h = int(spec["font_size"] * 1.22)
    y = int(spec["y"] * height - line_h * len(lines) / 2)
    centre = float(spec.get("x", 0.5)) * width

    def left(w):  # keep the block inside the frame when it is dragged sideways
        return min(max(centre - w / 2, margin * width / 2), width - margin * width / 2 - w)
    if spec["render_style"] == "box":
        pad = spec["font_size"] // 2
        block_w = max(measure(line) for line in lines)
        bx = left(block_w)
        draw.rounded_rectangle([bx - pad, y - pad // 2, bx + block_w + pad, y + line_h * len(lines) + pad // 3],
                               radius=pad, fill=hex_rgba(spec.get("box_color", "#000000B3")))
    budget = reveal if reveal is not None else 10 ** 9
    for line in lines:
        x = left(measure(line))
        for is_e, run in split_runs(line):
            if budget <= 0:
                break
            if not is_e:
                part = run[:budget]
                budget -= len(part)
                draw.text((x, y), part, font=font, fill=hex_rgba(spec["color"]),
                          stroke_width=stroke, stroke_fill=hex_rgba(spec.get("stroke_color", "#000000")))
                x += draw.textlength(run, font=font)
            else:
                for ch in EMOJI_RE.findall(run):
                    if budget <= 0:
                        break
                    budget -= 1
                    g = Image.new("RGBA", (136, 128), (0, 0, 0, 0))
                    ImageDraw.Draw(g).text((0, 0), ch, font=efont, embedded_color=True)
                    g = g.crop(g.getbbox() or (0, 0, 1, 1)).resize((glyph, glyph))
                    layer.alpha_composite(g, (int(x), int(y + (line_h - glyph) / 2)))
                    x += glyph
        budget -= 1  # the line break counts as the space it replaced
        y += line_h
    layer.save(path)
    return len(lines)


def caption_box(size, text, spec, margin=0.08):
    """Normalised (x0, y0, x1, y1) the caption block will occupy at spec['y'] (used to avoid faces)."""
    width, height = size
    n = max(1, min(int(spec.get("max_lines", 2)), 1 + len(str(text)) // 34))
    line_h = int(spec["font_size"] * 1.22)
    y0 = spec["y"] * height - line_h * n / 2
    return (margin, max(0.0, y0 / height), 1 - margin, min(1.0, (y0 + line_h * n) / height))


ANIMATIONS_IN = ("none", "fade", "pop", "slide_up", "typewriter", "word_by_word", "blink")
ANIMATIONS_OUT = ("cut", "fade")
# seen in the samples and the client's own ads (25 Oct 2026): captions cut in with the shot, type on letter by
# letter (offer lines, the blanket sample), and offer pills blink between two box colours
ANIMATION_DEFAULT_S = {"fade": 0.25, "pop": 0.3, "slide_up": 0.3, "typewriter": 0.6, "word_by_word": 0.8}


def motion_frames(tmp, key, full_png, kind, start, dur, fps, centre, direction="in"):
    """An entrance (or exit) as one still per frame, drawn with Pillow: fade (opacity), pop (85% -> ~103% -> 100%
    around the caption's own centre, with the fade) and slide_up (from 3.5% lower, with the fade). Plain stills keep
    the ffmpeg graph simple (looped image inputs deadlocked next to the outro). Returns [(png, t0, t1, None)]."""
    import math
    from PIL import Image
    base = Image.open(full_png).convert("RGBA")
    width, height = base.size
    n = max(2, int(round(dur * fps)))
    out = []
    for i in range(n):
        p = (i + 1) / n if direction == "in" else 1 - (i + 1) / n
        frame = Image.new("RGBA", base.size, (0, 0, 0, 0))
        img = base
        if kind == "pop":
            k = 0.85 + 0.15 * p + 0.08 * math.sin(math.pi * p)
            img = base.resize((max(1, int(width * k)), max(1, int(height * k))), Image.LANCZOS)
            frame.alpha_composite(img, (int(centre[0] - centre[0] * k), int(centre[1] - centre[1] * k)))
        elif kind == "slide_up":
            frame.alpha_composite(base, (0, int(height * 0.035 * (1 - p))))
        else:
            frame = base.copy()
        alpha = frame.getchannel("A").point(lambda a: int(a * min(1.0, p * 1.4 if kind != "fade" else p)))
        frame.putalpha(alpha)
        path = os.path.join(tmp, f"{key}_{direction}{i:02d}.png")
        frame.save(path)
        out.append((path, start + i / fps, start + (i + 1) / fps, None))
    return out


def caption_layers(tmp, key, size, text, spec, start, end, anim=None, fps=30):
    """The overlay layers of one caption: [(png, start, end, fx)] where fx (or None) is an ffmpeg effect on that
    layer: {"fade_in": d, "fade_out": d, "pop": d, "slide_up": d, "centre": (cx, cy)}. Typewriter and word-by-word
    become reveal steps, blink two alternating colour versions."""
    anim = anim or {}
    kind_in = anim.get("in", "none")
    kind_out = anim.get("out", "cut")
    d_in = float(anim.get("in_s") or ANIMATION_DEFAULT_S.get(kind_in, 0.0))
    d_out = float(anim.get("out_s") or (0.15 if kind_out == "fade" else 0.0))
    d_in = min(d_in, max(0.0, (end - start) * 0.6))
    full = os.path.join(tmp, f"{key}.png")
    n = render_caption_layer(full, size, text, spec)
    layers = []
    if kind_in in ("typewriter", "word_by_word") and d_in > 0:
        units = caption_units(text)
        if kind_in == "word_by_word":
            stops, count = [], 0
            for word in str(text).replace("\n", " ").split(" "):
                count += caption_units(word) + 1
                stops.append(min(units, count - 1))
        else:
            k = max(1, min(units, int(d_in * fps)))  # one step per frame at most
            stops = [round(units * (i + 1) / k) for i in range(k)]
        stops = [x for i, x in enumerate(stops) if x > 0 and (i == 0 or x != stops[i - 1])]
        step = d_in / max(1, len(stops))
        for i, upto in enumerate(stops[:-1]):
            png = os.path.join(tmp, f"{key}_r{i:03d}.png")
            render_caption_layer(png, size, text, spec, reveal=upto)
            layers.append((png, start + i * step, start + (i + 1) * step, None))
        hold_from = start + (len(stops) - 1) * step
        if d_out:
            layers.append((full, hold_from, end - d_out, None))
            layers += motion_frames(tmp, key, full, "fade", end - d_out, d_out, fps, None, "out")
        else:
            layers.append((full, hold_from, end, None))
    elif kind_in == "blink":
        alt = dict(spec)
        if spec.get("render_style") == "box":
            alt["box_color"] = anim.get("blink_color") or "#2EC4B6F2"
        else:
            alt["color"] = anim.get("blink_color") or "#FFE94A"
        alt_png = os.path.join(tmp, f"{key}_b.png")
        render_caption_layer(alt_png, size, text, alt)
        period = float(anim.get("blink_s") or 0.25)
        t, i = start, 0
        while t < end - 1e-3:
            layers.append((full if i % 2 == 0 else alt_png, t, min(end, t + period), None))
            t += period
            i += 1
    else:
        from PIL import Image
        with Image.open(full) as im:
            bb = im.getbbox() or (0, 0, size[0], size[1])
        centre = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
        t0, t1 = start, end
        if kind_in in ("fade", "pop", "slide_up") and d_in > 0:
            layers += motion_frames(tmp, key, full, kind_in, start, d_in, fps, centre, "in")
            t0 = start + max(2, int(round(d_in * fps))) / fps
        if d_out:
            t1 = end - d_out
        layers.append((full, t0, t1, None))
        if d_out:
            layers += motion_frames(tmp, key, full, "fade", t1, d_out, fps, centre, "out")
    return layers, n


def boxes_overlap(a, b, pad=0.02):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


def detect_layout(ffmpeg, video, t, cache):
    """Face boxes and personalized-design boxes (normalised) in the frame at t seconds, from the vision model
    (seed-2-0-lite): {"faces": [...], "product": [...]}; empty lists on any failure.
    Only runs when ARK_API_KEY is available and plan.avoid_faces is not false."""
    key = f"{video}@{round(t, 1)}"
    if key in cache:
        return cache[key]
    found = {"faces": [], "product": []}
    api_key = os.environ.get("ARK_API_KEY")
    if api_key:
        try:
            import base64, io, urllib.request
            from PIL import Image
            tmp = tempfile.mkdtemp(prefix="faces_")
            frame = os.path.join(tmp, "f.jpg")
            subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "4", frame], check=False)
            if os.path.isfile(frame):
                with open(frame, "rb") as fh:
                    b64 = base64.b64encode(fh.read()).decode()
                body = {"model": os.environ.get("FACE_MODEL", "seed-2-0-lite-260428"), "temperature": 0, "max_tokens": 500,
                        "messages": [{"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
                            {"type": "text", "text": "Give bounding boxes normalised to 0-1 for (a) every human face (real people and printed cartoon portraits "
                                                     "of people) and (b) the key personalized element on the product: a TIGHT box around the printed name(s) together "
                                                     "with the portrait, character or motif printed next to them (on a blanket, garment, mug, bag, socks...), or a printed pet or person "
                                                     "face worn as a mask (box the whole printed face); not the "
                                                     "whole product, not an all-over background pattern. Reply with ONLY JSON like "
                                                     "{\"faces\": [{\"x0\":0.1,\"y0\":0.2,\"x1\":0.3,\"y1\":0.4}], \"product\": [{\"x0\":0.2,\"y0\":0.4,\"x1\":0.8,\"y1\":0.7}]}; "
                                                     "use [] for a kind that is not in the image."}]}]}
                req = urllib.request.Request((os.environ.get("ARK_BASE_URL") or "https://ark.ap-southeast.bytepluses.com/api/v3") + "/chat/completions",
                                             data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=90) as resp:
                    out = json.loads(resp.read())
                txt = out["choices"][0]["message"]["content"]
                if isinstance(txt, list):
                    txt = "".join(c.get("text", "") for c in txt)
                m = re.search(r"[\[{].*[\]}]", txt, re.S)
                if m:
                    data = json.loads(m.group(0))
                    if isinstance(data, list):  # an answer with faces only
                        data = {"faces": data}
                    for kind in ("faces", "product"):
                        for b in data.get(kind) or []:
                            box = (float(b["x0"]), float(b["y0"]), float(b["x1"]), float(b["y1"]))
                            if 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1:
                                found[kind].append(box)
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception as error:  # the layout falls back to the requested position
            print(json.dumps({"warning": f"face detection skipped: {str(error)[:120]}"}), file=sys.stderr)
    cache[key] = found
    return found


def detect_faces(ffmpeg, video, t, cache):
    return detect_layout(ffmpeg, video, t, cache)["faces"]


def _overlap_area(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def caption_clear(size, text, spec, faces, product=()):
    box = caption_box(size, text, spec)
    return not any(boxes_overlap(box, f) for f in faces) and not any(boxes_overlap(box, p, pad=0.02) for p in product)


def place_caption(size, text, spec, faces, product=()):
    """Keep the caption off every face and off the personalized design. Bands in order: the requested one, top, upper,
    bottom, lower, then middle. The first band clear of both wins; if none is clear, the band with the least covered
    area (faces weigh 3, the design 2), so a caption never lands in the middle of a worn print just to dodge a face."""
    if not faces and not product:
        return spec, None
    order = [spec["y"]] + [POSITIONS[k] for k in ("top", "upper", "bottom", "lower", "middle")]
    best, best_cost = None, None
    for y in order:
        trial = dict(spec, y=y)
        box = caption_box(size, text, trial)
        if not any(boxes_overlap(box, f) for f in faces) and not any(boxes_overlap(box, p, pad=0.02) for p in product):
            return trial, (None if y == spec["y"] else y)
        cost = 3 * sum(_overlap_area(box, f) for f in faces) + 2 * sum(_overlap_area(box, p) for p in product)
        if best_cost is None or cost < best_cost - 1e-6:
            best, best_cost = y, cost
    return dict(spec, y=best), (None if best == spec["y"] else best)


def place_inset(size, ins, faces):
    """Keep the inset and its arrow tip off every face: try right/left and lower tops; aim the arrow at the chest."""
    width, height = size
    w = float(ins.get("width", 0.34))
    h = min(0.45, w * 1.6 * width / height)
    cands = [(ins.get("position", "top-right"), float(ins.get("top", 0.24)))]
    for top in (0.24, 0.40, 0.52):
        for pos in ("top-right", "top-left"):
            cands.append((pos, top))
    chosen = cands[0]
    for pos, top in cands:
        x0 = 1 - 0.04 - w if "right" in pos else 0.04
        box = (x0, top, x0 + w, top + h)
        if not any(boxes_overlap(box, f) for f in faces):
            chosen = (pos, top)
            break
    ins = dict(ins, position=chosen[0], top=chosen[1])
    if ins.get("arrow_to") and faces:
        # the arrow lands just above the head of the portrait it points at (never on the face or the body):
        # take the face nearest the requested point, e.g. the cartoon on the product
        tx, ty = ins["arrow_to"]
        f = min(faces, key=lambda b: ((b[0] + b[2]) / 2 - tx) ** 2 + ((b[1] + b[3]) / 2 - ty) ** 2)
        fh = f[3] - f[1]
        ins["arrow_to"] = [round((f[0] + f[2]) / 2, 4), round(max(0.02, f[1] - max(0.008, fh * 0.08)), 4)]
        ins["_target_face"] = list(f)
    if faces:
        ins["_avoid"] = [list(f) for f in faces]  # the arrow's path must not cross any face (real or cartoon)
    return ins


def render_inset_layer(path, size, ins):
    """Photo inset (rounded, white border) with an optional curved white arrow to a frame point."""
    from PIL import Image, ImageDraw
    width, height = size
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    img = Image.open(ins["image"]).convert("RGBA")
    w = int(width * float(ins.get("width", 0.34)))
    img.thumbnail((w, int(w * 1.6)))
    border = max(3, width // 240)
    pos = ins.get("position", "top-right")
    margin = int(width * 0.04)
    top = int(height * float(ins.get("top", 0.24)))
    x = width - img.width - margin if "right" in pos else margin
    if ins.get("left") is not None:  # dragged in the caption editor: left edge as a fraction of the width
        x = min(max(0, int(width * float(ins["left"]))), width - img.width - border * 2)
    y = top
    frame = Image.new("RGBA", (img.width + 2 * border, img.height + 2 * border), (255, 255, 255, 255))
    layer.alpha_composite(frame, (x - border, y - border))
    layer.alpha_composite(img, (x, y))
    if ins.get("arrow_to"):
        draw = ImageDraw.Draw(layer)
        tx, ty = int(ins["arrow_to"][0] * width), int(ins["arrow_to"][1] * height)
        sx, sy = (x, y + img.height // 2) if "right" in pos else (x + img.width, y + img.height // 2)
        side = -1 if "right" in pos else 1
        target_face = ins.get("_target_face")
        avoid = [(f[0] * width, f[1] * height, f[2] * width, f[3] * height) if target_face and list(f) == list(target_face) else
                 (f[0] * width - width * 0.02, f[1] * height - height * 0.015, f[2] * width + width * 0.02, f[3] * height + height * 0.015)
                 for f in ins.get("_avoid") or []]

        def curve(cx, cy):
            return [((1 - t) ** 2 * sx + 2 * (1 - t) * t * cx + t ** 2 * tx, (1 - t) ** 2 * sy + 2 * (1 - t) * t * cy + t ** 2 * ty)
                    for t in [i / 40 for i in range(41)]]

        def hits(pts):
            return any(b[0] <= px <= b[2] and b[1] <= py <= b[3] for px, py in pts for b in avoid)

        mx = (sx + tx) / 2
        options = ([(tx, min(sy, ty) - height * 0.10)] if target_face else []) + [  # from above, tip pointing down onto the head
                   (mx + side * width * 0.06, min(sy, ty) - height * 0.05),   # bow upward
                   (mx + side * width * 0.06, max(sy, ty) + height * 0.06),   # bow downward, under the face
                   (mx, (sy + ty) / 2),                                        # straight
                   (sx + side * width * 0.02, ty),                             # drop first, then across at chest height
                   (tx, sy)]                                                   # across first, then down
        pts = next((c for c in (curve(cx, cy) for cx, cy in options) if not hits(c)), None)
        if pts is None:  # no clean path: stop the arrow before it reaches a face
            full = curve(*options[1])
            cut = next((i for i, (px, py) in enumerate(full) if any(b[0] <= px <= b[2] and b[1] <= py <= b[3] for b in avoid)), len(full))
            pts = full[:max(cut - 1, 6)]
        lw = max(5, width // 120)
        ex, ey = pts[-1]
        px, py = pts[-4]
        ang = math.atan2(ey - py, ex - px)
        head = lw * 4
        tri = [(ex, ey), (ex - head * math.cos(ang - 0.5), ey - head * math.sin(ang - 0.5)),
               (ex - head * math.cos(ang + 0.5), ey - head * math.sin(ang + 0.5))]
        shadow = (30, 30, 30, 170)  # dark outline so the white arrow reads on light prints and lettering
        draw.line(pts, fill=shadow, width=lw + max(4, lw // 2), joint="curve")
        draw.polygon(tri, fill=shadow, outline=shadow, width=max(3, lw // 2))
        draw.line(pts, fill=(255, 255, 255, 255), width=lw, joint="curve")
        draw.polygon(tri, fill=(255, 255, 255, 255))
    layer.save(path)
    return (x - border, y - border, x + img.width + border, y + img.height + border)  # the framed photo, in pixels


def render_end_card(path, size, card):
    from PIL import Image, ImageDraw, ImageFont
    width, height = size
    canvas = Image.new("RGBA", (width, height), hex_rgba(card.get("background", "#FFFFFF")))
    draw = ImageDraw.Draw(canvas)
    lines = [{"text": spec} if isinstance(spec, str) else spec for spec in card.get("lines", [])]
    img = None
    if card.get("image"):
        img = Image.open(card["image"]).convert("RGBA")
        img.thumbnail((int(width * 0.85), int(height * (0.50 if lines else 0.80))))
    items, total = [], 0
    if img is not None:
        gap = int(height * 0.04) if lines else 0
        items.append(("image", img, img.height + gap))
        total += img.height + gap
    for spec in lines:
        font_size = int(spec.get("size", 64))
        font = ImageFont.truetype(FONTS.get(spec.get("weight", "bold"), FONTS["bold"]), font_size)
        wrapped = wrap(draw, spec["text"], font, width - 160, 0)
        block = int(font_size * 1.35) * len(wrapped) + int(font_size * 0.35)
        items.append(("text", (spec, font, font_size, wrapped), block))
        total += block
    y = max(int(height * 0.05), int((height - total) / 2))
    for kind, payload, block in items:
        if kind == "image":
            canvas.alpha_composite(payload, ((width - payload.width) // 2, y))
            y += block
            continue
        spec, font, font_size, wrapped = payload
        for line in wrapped:
            w = draw.textlength(line, font=font)
            x = (width - w) / 2
            if spec.get("pill"):
                pad = font_size // 2
                draw.rounded_rectangle([x - pad, y - pad // 4, x + w + pad, y + int(font_size * 1.3)],
                                       radius=font_size, fill=hex_rgba(spec["pill"]))
                draw.text((x, y), line, font=font, fill=hex_rgba(spec.get("color", "#FFFFFF")))
            else:
                draw.text((x, y), line, font=font, fill=hex_rgba(spec.get("color", "#111111")))
            y += int(font_size * 1.35)
        y += int(font_size * 0.35)
    canvas.convert("RGB").save(path)


def media_seconds(ffmpeg, path):
    proc = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True)
    for line in proc.stderr.splitlines():
        if "Duration:" in line:
            hms = line.split("Duration:")[1].split(",")[0].strip()
            if hms != "N/A":
                h, m, s = hms.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
    fail(f"Could not read duration of {path}")


def has_audio(ffmpeg, path):
    proc = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True)
    return "Audio:" in proc.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", required=True, help="Path to the edit plan JSON")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the steps; render nothing")
    parser.add_argument("--keep-temp", action="store_true", help="Keep intermediate files for debugging")
    args = parser.parse_args()

    try:
        with open(args.plan) as fh:
            plan = json.load(fh)
    except (OSError, json.JSONDecodeError) as error:
        fail(f"Cannot read plan: {error}")
    warnings = validate(plan, args.dry_run)
    width, height = plan["size"]
    fps = plan["fps"]

    if args.dry_run:
        steps = []
        for i, c in enumerate(plan["clips"]):
            if c.get("image"):
                steps.append(f"still {i + 1}: {c['image']} for {c.get('duration', 2.5)} s (zoom {c.get('zoom', 1.06)}) -> {width}x{height}")
            else:
                steps.append(f"normalize clip {i + 1}: {c['path']} [{c.get('start', 0)}s to {c.get('end', 'end')}] -> {width}x{height} @ {fps} fps")
        if plan.get("end_card"):
            steps.append(f"end card: {plan['end_card'].get('duration', 3)} s")
        if plan.get("outro"):
            steps.append(f"outro: {plan['outro']['path']}")
        steps.append("concatenate")
        steps += [f"caption {c['start']}-{c['end']} s ({c.get('style', 'client')}, {c.get('position', 'top')}): {c['text']}"
                  for c in plan.get("captions", [])]
        steps += [f"inset {c['start']}-{c['end']} s: {c['image']}" + (" with arrow" if c.get("arrow_to") else "") for c in plan.get("insets", [])]
        if plan.get("disclaimer"):
            steps.append(f"disclaimer (whole video): {plan['disclaimer'].get('text')}")
        audio = []
        if plan.get("keep_clip_audio"):
            audio.append("clip audio")
        if plan.get("music"):
            audio.append("music " + plan["music"]["path"])
        audio += [f"sfx {s['path']} at {s.get('start', 0)} s" for s in plan.get("sfx", [])]
        steps.append("audio: " + (", ".join(audio) if audio else "silent track"))
        steps.append(f"write {plan['output']}")
        print(json.dumps({"ok": True, "dry_run": True, "steps": steps, "warnings": warnings}, indent=2))
        return

    imageio_ffmpeg = load_deps()
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    tmp = tempfile.mkdtemp(prefix="assembly_")
    try:
        vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
              f"setsar=1,fps={fps},format=yuv420p")
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
        keep_audio = bool(plan.get("keep_clip_audio"))
        parts, part_times = [], []
        t_cursor = 0.0
        for i, clip in enumerate(plan["clips"]):
            out = os.path.join(tmp, f"part_{i:02d}.mp4")
            if clip.get("image"):
                dur = float(clip.get("duration", 2.5))
                zoom = float(clip.get("zoom", 1.06))
                frames = int(dur * fps)
                if clip.get("fit", "contain") == "contain":
                    # fit the whole still inside the frame over a blurred copy of itself (nothing cut off)
                    prep = (f"split[bg][fg];[bg]scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,crop={width * 2}:{height * 2},"
                            f"gblur=sigma=40,eq=brightness=-0.05[bgb];[fg]scale={width * 2}:{height * 2}:force_original_aspect_ratio=decrease[fgs];"
                            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,")
                else:
                    prep = f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,crop={width * 2}:{height * 2},"
                zf = (prep +
                      f"zoompan=z='min(1+({zoom}-1)*on/{max(frames, 1)},{zoom})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                      f":d={frames}:s={width}x{height}:fps={fps},format=yuv420p")
                cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-i", clip["image"], "-t", f"{dur:.3f}",
                       "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=44100:cl=stereo", "-vf", zf] + enc + \
                      ["-c:a", "aac", "-shortest", out]
                run(cmd)
            else:
                cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
                start = float(clip.get("start", 0))
                if start:
                    cmd += ["-ss", str(start)]
                cmd += ["-i", clip["path"]]
                if clip.get("end") is not None:
                    cmd += ["-t", str(float(clip["end"]) - start)]
                cvf = vf
                if clip.get("zoom") and float(clip["zoom"]) > 1.0:  # tighter framing: crop the centre (or zoom_anchor) before scaling
                    z = float(clip["zoom"])
                    ax, ay = (clip.get("zoom_anchor") or [0.5, 0.5])[:2]
                    cvf = f"crop=iw/{z:.4f}:ih/{z:.4f}:(iw-iw/{z:.4f})*{float(ax):.3f}:(ih-ih/{z:.4f})*{float(ay):.3f}," + vf
                if keep_audio and has_audio(ffmpeg, clip["path"]):
                    run(cmd + ["-vf", cvf] + enc + ["-c:a", "aac", "-ar", "44100", "-ac", "2", out])
                else:
                    length = float(clip["end"]) - start if clip.get("end") is not None else media_seconds(ffmpeg, clip["path"]) - start
                    run(cmd + ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=44100:cl=stereo", "-vf", cvf] + enc +
                        ["-c:a", "aac", "-shortest", "-map", "0:v", "-map", "1:a", out])
            parts.append(out)
            d = media_seconds(ffmpeg, out)
            part_times.append((t_cursor, t_cursor + d))
            t_cursor += d
        if plan.get("end_card"):
            card_png = os.path.join(tmp, "end_card.png")
            render_end_card(card_png, (width, height), plan["end_card"])
            out = os.path.join(tmp, "part_end.mp4")
            dur = float(plan["end_card"].get("duration", 3))
            run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-i", card_png, "-t", f"{dur:.3f}",
                 "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=44100:cl=stereo", "-vf", vf] + enc + ["-c:a", "aac", "-shortest", out])
            parts.append(out)
            t_cursor += dur
        content_end = t_cursor
        if plan.get("outro"):
            out = os.path.join(tmp, "part_outro.mp4")
            opath = plan["outro"]["path"]
            olen = media_seconds(ffmpeg, opath)
            if has_audio(ffmpeg, opath):
                run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", opath, "-vf", vf] + enc + ["-c:a", "aac", "-ar", "44100", "-ac", "2", out])
            else:
                run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", opath, "-f", "lavfi", "-t", f"{olen:.3f}", "-i",
                     "anullsrc=r=44100:cl=stereo", "-vf", vf] + enc + ["-c:a", "aac", "-shortest", "-map", "0:v", "-map", "1:a", out])
            parts.append(out)
        listing = os.path.join(tmp, "parts.txt")
        with open(listing, "w") as fh:
            fh.writelines(f"file '{p}'\n" for p in parts)
        base = os.path.join(tmp, "base.mp4")
        run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", base])
        duration = media_seconds(ffmpeg, base)

        layers, caption_lines, moved = [], [], []
        avoid = plan.get("avoid_faces", True)
        face_cache = {}
        for i, cap in enumerate(plan.get("captions", [])):
            spec = caption_spec(cap, (width, height))
            c0, c1 = float(cap["start"]), min(float(cap["end"]), duration)
            pieces = [(c0, c1, spec)]
            if avoid:
                # a caption that runs over several clips must stay clear in every one of them: look at each clip it
                # spans (30% and 70% into the overlap). One position clear of everything wins; when none is, the
                # caption is split at the cuts and each piece is placed on its own (adjacent pieces at the same
                # height are merged), so a head at the top of one shot never ends up under the text.
                wins = []
                for a, b in part_times:
                    lo, hi = max(a, c0), min(b, c1)
                    if hi - lo > 0.2:
                        found = {"faces": [], "product": []}
                        for t in (lo + 0.3 * (hi - lo), lo + 0.7 * (hi - lo)):
                            f = detect_layout(ffmpeg, base, t, face_cache)
                            found["faces"] += f["faces"]
                            found["product"] += f["product"]
                        wins.append((lo, hi, found))
                if not wins:
                    wins = [(c0, c1, detect_layout(ffmpeg, base, (c0 + c1) / 2, face_cache))]
                faces = [x for w in wins for x in w[2]["faces"]]
                product = [x for w in wins for x in w[2]["product"]]
                placed, new_y = place_caption((width, height), cap["text"], spec, faces, product)
                if len(wins) > 1 and not caption_clear((width, height), cap["text"], placed, faces, product):
                    pieces = []
                    for lo, hi, found in wins:
                        sp, _ = place_caption((width, height), cap["text"], spec, found["faces"], found["product"])
                        if pieces and abs(pieces[-1][2]["y"] - sp["y"]) < 1e-6:
                            pieces[-1] = (pieces[-1][0], hi, pieces[-1][2])
                        else:
                            pieces.append((lo, hi, sp))
                    pieces[0] = (c0, pieces[0][1], pieces[0][2])
                    pieces[-1] = (pieces[-1][0], c1, pieces[-1][2])
                    moved.append({"caption": cap["text"][:40], "split_at_cuts": [[round(p[0], 2), round(p[1], 2), round(p[2]["y"], 2)] for p in pieces],
                                  "faces": len(faces), "product_areas": len(product)})
                else:
                    pieces = [(c0, c1, placed)]
                    if new_y is not None:
                        moved.append({"caption": cap["text"][:40], "moved_to": round(new_y, 2), "faces": len(faces), "product_areas": len(product)})
            anim = cap.get("animation") or plan.get("caption_animation") or {}
            for k, (p0, p1, sp) in enumerate(pieces):
                # a caption split at the cuts animates in once (first piece) and out once (last piece)
                a_k = {"in": anim.get("in", "none") if k == 0 else "none", "in_s": anim.get("in_s"),
                       "out": anim.get("out", "cut") if k == len(pieces) - 1 else "cut", "out_s": anim.get("out_s"),
                       "blink_color": anim.get("blink_color"), "blink_s": anim.get("blink_s")}
                if anim.get("in") == "blink":
                    a_k["in"] = "blink"
                new_layers, n = caption_layers(tmp, f"caption_{i:02d}_{k:02d}", (width, height), cap["text"], sp, p0, p1, a_k, fps)
                layers += new_layers
            caption_lines.append(n)
        for i, ins in enumerate(plan.get("insets", [])):
            png = os.path.join(tmp, f"inset_{i:02d}.png")
            if avoid:
                mid = (float(ins["start"]) + min(float(ins["end"]), duration)) / 2
                faces = detect_faces(ffmpeg, base, mid, face_cache)
                placed = place_inset((width, height), ins, faces)
                if placed.get("position") != ins.get("position", "top-right") or placed.get("top") != ins.get("top", 0.24) or placed.get("arrow_to") != ins.get("arrow_to"):
                    moved.append({"inset": os.path.basename(ins["image"]), "position": placed.get("position"), "top": placed.get("top"), "arrow_to": placed.get("arrow_to"), "faces": len(faces)})
                ins = placed
            render_inset_layer(png, (width, height), ins)
            i0, i1 = float(ins["start"]), min(float(ins["end"]), duration)
            if ins.get("animate", True):  # the client's ads bring the photo inset in a few frames after the cut
                from PIL import Image
                with Image.open(png) as im:
                    bb = im.getbbox() or (0, 0, width, height)
                pops = motion_frames(tmp, f"inset_{i:02d}", png, "pop", i0, 0.25, fps, ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2), "in")
                layers += pops
                i0 = pops[-1][2]
            layers.append((png, i0, i1, None))
        if plan.get("disclaimer"):
            disc = plan["disclaimer"]
            png = os.path.join(tmp, "disclaimer.png")
            spec = caption_spec({"style": "pill", "position": disc.get("position", 0.06), "size": disc.get("size", int(width * 0.026))}, (width, height))
            render_caption_layer(png, (width, height), disc["text"], spec)
            layers.append((png, 0.0, content_end if plan.get("outro") else duration, None))

        def render(layers, out_path):
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", base]
            for png, _, end, fx in layers:
                # animated layers are looped stills so per-frame filters (fade, scale) see the running time
                cmd += (["-loop", "1", "-framerate", str(fps), "-t", f"{end + 0.1:.3f}", "-i", png] if fx else ["-i", png])
            music = plan.get("music")
            inputs = 1 + len(layers)
            music_index = None
            if music:
                cmd += ["-stream_loop", "-1", "-i", music["path"]]
                music_index = inputs
                inputs += 1
            sfx_indexes = []
            for sfx in plan.get("sfx", []):
                cmd += ["-i", sfx["path"]]
                sfx_indexes.append((inputs, sfx))
                inputs += 1
            chains, label = [], "0:v"
            for n, (_, start, end, fx) in enumerate(layers, start=1):
                out_label = f"v{n}"
                src, x, y = f"[{n}:v]", "0", "0"
                if fx:
                    f = [f"[{n}:v]format=rgba"]
                    if fx.get("fade_in"):
                        f.append(f"fade=t=in:st={start:.3f}:d={fx['fade_in']:.3f}:alpha=1")
                    if fx.get("fade_out"):
                        f.append(f"fade=t=out:st={max(start, end - fx['fade_out']):.3f}:d={fx['fade_out']:.3f}:alpha=1")
                    cx, cy = fx.get("centre", (width / 2, height / 2))
                    if fx.get("pop"):  # grow from 85% with a small overshoot, around the caption's own centre
                        d = fx["pop"]
                        k = f"if(lt(t,{start:.3f}),0.85,if(lt(t,{start + d:.3f}),0.85+0.15*(t-{start:.3f})/{d:.3f}+0.08*sin(PI*(t-{start:.3f})/{d:.3f}),1))"
                        f.append(f"scale=w='trunc(iw*{k}/2)*2':h='trunc(ih*{k}/2)*2':eval=frame")
                        x, y = f"{cx:.1f}-{cx:.1f}*w/{width}", f"{cy:.1f}-{cy:.1f}*h/{height}"
                    if fx.get("slide_up"):
                        d = fx["slide_up"]
                        y = f"if(lt(t,{start + d:.3f}),{height * 0.035:.1f}*(1-max(0,(t-{start:.3f}))/{d:.3f}),0)"
                    chains.append(",".join(f) + f"[l{n}]")
                    src = f"[l{n}]"
                pos = f"x='{x}':y='{y}':eval=frame" if fx else "0:0"
                chains.append(f"[{label}]{src}overlay={pos}:enable='between(t,{start:.3f},{end:.3f})'[{out_label}]")
                label = out_label
            audio_labels = ["[0:a]"] if (keep_audio or not music and not sfx_indexes) else []
            if music:
                fade = float(music.get("fade_out", 1.0))
                fade_at = (content_end if plan.get("outro") and music.get("fade_before_outro", True) else duration)
                chains.append(f"[{music_index}:a]volume={float(music.get('volume', 0.8))},"
                              f"afade=t=out:st={max(0.0, fade_at - fade):.3f}:d={fade:.3f}[music]")
                audio_labels.append("[music]")
            for k, (idx, sfx) in enumerate(sfx_indexes):
                delay = int(float(sfx.get("start", 0)) * 1000)
                chains.append(f"[{idx}:a]volume={float(sfx.get('volume', 1.0))},adelay={delay}|{delay}[sfx{k}]")
                audio_labels.append(f"[sfx{k}]")
            if len(audio_labels) > 1:
                chains.append("".join(audio_labels) + f"amix=inputs={len(audio_labels)}:duration=first:dropout_transition=0:normalize=0[aout]")
                audio_map = "[aout]"
            else:
                audio_map = audio_labels[0] if audio_labels[0] != "[0:a]" else "0:a"
            video_map = f"[{label}]" if layers else "0:v"
            if chains:
                cmd += ["-filter_complex", ";".join(chains)]
            os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
            cmd += ["-map", video_map, "-map", audio_map, "-t", f"{duration:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_path]
            run(cmd)
            return music, sfx_indexes

        music, sfx_indexes = render(layers, plan["output"])
        clean = plan.get("clean_output", os.path.splitext(plan["output"])[0] + "_clean.mp4")
        if clean:  # the same cut without any text or inset, for re-editing with the client's own footage and text
            render([], clean)

        previews = []
        count = int(plan.get("preview_frames", 0))
        if count > 0:
            stem = os.path.splitext(plan["output"])[0]
            for k in range(count):
                t = duration * (k + 0.5) / count
                frame = f"{stem}_frame_{k + 1:02d}.jpg"
                run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", plan["output"],
                     "-frames:v", "1", "-q:v", "3", frame])
                previews.append(frame)
        print(json.dumps({"ok": True, "output": plan["output"], "clean_output": clean or None, "duration_s": round(duration, 2),
                          "size": f"{width}x{height}", "fps": fps, "clips": len(plan["clips"]),
                          "captions": len(plan.get("captions", [])), "caption_lines": caption_lines, "face_avoidance": moved,
                          "insets": len(plan.get("insets", [])), "end_card": bool(plan.get("end_card")),
                          "outro": bool(plan.get("outro")), "audio": {"music": bool(music), "sfx": len(sfx_indexes), "clip_audio": keep_audio},
                          "preview_frames": previews, "warnings": warnings}, indent=2))
    finally:
        if args.keep_temp:
            print(json.dumps({"temp_dir": tmp}), file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
