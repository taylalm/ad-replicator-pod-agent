#!/usr/bin/env python3
"""Deterministic helpers for writing Seedance 2.5 prompts for UGC ad replicas.

  template  Build a prompts.json skeleton from analysis.json (scenes grouped into 5-10 s clips).
  validate  Check prompts.json against the Seedance 2.5 rules (references/seedance25_rules.md)
            and the ad brief (do_not_copy terms, personalization names, subtitles ban).
  render    Write clip_XX.prompt.txt and commands.sh (one generate-with-seedance call per clip);
            --dry-run also executes each command with --dry-run (no API call).

No model or network calls are made here.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys

SEEDANCE_SCRIPT = "/mnt/skills/generate-with-seedance/scripts/seedance-generate.mjs"
RATIOS = {"21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "adaptive"}
RESOLUTIONS = {"480p", "720p", "1080p"}
MODES = {"reference", "edit", "extend"}
MAX_IMAGES, MAX_VIDEOS = 30, 10          # Seedance 2.5 tutorial: 30 images + 10 videos + 10 audio
DURATION_RANGE = (4, 30)                 # Seedance 2.5
# per version, from generate-with-seedance (Seedance 2.5 tutorial capability table): durations and resolutions
VERSION_RULES = {"2.5": {"duration": (4, 30), "resolutions": ("480p", "720p", "1080p")},
                 "2.0": {"duration": (4, 15), "resolutions": ("480p", "720p", "1080p")},
                 "2.0-fast": {"duration": (4, 15), "resolutions": ("480p", "720p")},
                 "2.0-mini": {"duration": (4, 15), "resolutions": ("480p", "720p")}}
EDIT_TRIGGERS = re.compile(r"\b(edit( the)? video|add|insert|remove|delete|modify|replace|change to)\b", re.I)
EXTEND_TRIGGERS = re.compile(r"\b(extend (forward|backward)|extend|continue( from| the story)?)\b", re.I)
NO_SUBTITLES = re.compile(r"no subtitles", re.I)
NO_TEXT = re.compile(r"no (on-screen )?text|no captions", re.I)
INTENSE = re.compile(r"\b(fanatical|extremely shocked|shocked|ecstatic|hysterical|glowing eyes|screaming)\b", re.I)
BUILTIN_FORBIDDEN = ["tiktok", "instagram", "reels", "veo", "giftsoul", "gift soul", "@gift", "watermark logo",
                     "follow button", "like count"]
TIMESTAMP = re.compile(r"(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?\s*[-–to]+\s*(\d+(?:\.\d+)?)\s*s\b", re.I)


def out(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    sys.exit(code)


def load(path, what):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as error:
        out({"ok": False, "error": f"Cannot read {what}: {error}"}, 2)


# ----------------------------------------------------------------------------- template
def group_scenes(scenes, min_len=5.0, max_len=10.0, max_scenes=3):
    clips, current = [], []
    for sc in scenes:
        current.append(sc)
        length = sum(s["end"] - s["start"] for s in current)
        if length >= min_len or len(current) >= max_scenes:
            clips.append(current)
            current = []
    if current:
        if clips and sum(s["end"] - s["start"] for s in clips[-1] + current) <= max_len:
            clips[-1].extend(current)
        else:
            clips.append(current)
    return clips


def template(args):
    analysis = load(args.analysis, "analysis.json")
    scenes = analysis.get("scenes") or []
    if not scenes:
        out({"ok": False, "error": "analysis.json has no scenes"}, 2)
    groups = group_scenes(scenes)
    clips = []
    for i, grp in enumerate(groups, 1):
        length = sum(s["end"] - s["start"] for s in grp)
        lo, hi = VERSION_RULES.get(args.version, VERSION_RULES["2.5"])["duration"]
        duration = int(min(max(lo, round(length + 1)), hi))
        shots, t = [], 0
        for s in grp:
            seg = max(1, round(s["end"] - s["start"]))
            shots.append(f"{t}-{min(t + seg, duration)}s: [{s.get('shot', '')}; {s.get('camera', '')}; {s.get('setting', '')}] "
                         f"{s.get('description', '')} Purpose: {s.get('purpose', '')}.")
            t = min(t + seg, duration)
        if t < duration:
            shots[-1] = shots[-1].replace(f"-{t}s:", f"-{duration}s:", 1)
        clips.append({
            "id": f"clip_{i:02d}", "mode": "reference", "duration": duration, "attempt": 1,
            "scenes": [s["index"] for s in grp],
            "references": ["<person_ref_id>", "<product_ref_id>"],
            "prompt": "REPLACE ME. Bind references first (@Image1 is ..., @Image2 is ...), then shots:\n" + "\n".join(shots)
                      + "\nRealistic handheld phone footage, natural light, vertical 9:16. No subtitles, no on-screen text, no captions, no logos, no watermarks.",
        })
    plan = {
        "source_video_url": (analysis.get("source_url") or ""),
        "product": {"name": "<product name from the product page>", "names": ["<NAME>"],
                    "personalization": "<what is personalized, e.g. animal + quote + name on the sole>",
                    "layout": "<exact layout from the website preview, e.g. left sole: quote text + books; right sole: owl artwork + name; leg: bookshelf pattern; cuff/heel/toe teal>",
                    "size_statement": "<chosen size with a scale cue, e.g. 50 x 60 inches (127 x 152 cm): held up by an 8-year-old it is taller than the child and wider than their arm span; leave empty for products without a size>"},
        "cast_count": "<number of people in the sample analysis; the replica uses the same number>",
        "do_not_copy": analysis.get("do_not_copy", []),
        "defaults": {"version": args.version, **({"model": args.model} if args.model else {}), "ratio": "9:16", "resolution": "480p",
                     "download": "/mnt/session/outputs/07_clips"},
        "references": [
            {"id": "<person_ref_id>", "kind": "person", "path": "/mnt/session/outputs/04_people/person_<name>.png", "describe": "<age, look, outfit>"},
            {"id": "<product_ref_id>", "kind": "product", "path": "/mnt/session/outputs/05_personalize/product_<name>.png", "describe": "<the personalized preview: options, name>"},
            {"id": "texture_1", "kind": "texture", "path": "/mnt/session/outputs/02_product/gallery_01.jpg", "describe": "<product-page photo showing the material / pattern>"},
        ],
        "clips": clips,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(plan, fh, indent=2, ensure_ascii=False)
    out({"ok": True, "plan": args.out, "clips": len(clips), "scene_groups": [[s["index"] for s in g] for g in groups],
         "next": "Fill references and every clip prompt, then run validate."})


# ----------------------------------------------------------------------------- validate
def validate_plan(plan, analysis=None):
    errors, warnings = [], []
    refs = {r.get("id"): r for r in plan.get("references", []) if isinstance(r, dict)}
    defaults = plan.get("defaults", {})
    forbidden = [t.lower() for t in BUILTIN_FORBIDDEN]
    for term in (plan.get("do_not_copy") or []) + ((analysis or {}).get("do_not_copy") or []):
        # keep short distinctive tokens from each do_not_copy entry (brand/account names, marks)
        for tok in re.findall(r"'([^']{3,40})'|\"([^\"]{3,40})\"", term):
            forbidden.append((tok[0] or tok[1]).lower())
    forbidden = sorted(set(forbidden))
    names = [n for n in plan.get("product", {}).get("names", []) if n and not n.startswith("<")]

    for rid, r in refs.items():
        if rid.startswith("<"):
            errors.append(f"references: placeholder id {rid!r} not replaced")
        if r.get("kind") not in ("person", "product", "setting", "style", "video", "texture", "photo", "staging"):
            errors.append(f"references[{rid}].kind must be person, product, texture, photo, staging, setting, style or video")
        path = r.get("path") or r.get("url") or ""
        if r.get("kind") == "video":
            if not path.startswith("https://"):
                errors.append(f"references[{rid}]: video references must be public https URLs")
        elif path.startswith("https://"):
            pass
        elif not os.path.isfile(path):
            errors.append(f"references[{rid}].path not found: {path}")
        elif os.path.getsize(path) > 10 * 1024 * 1024:
            errors.append(f"references[{rid}]: image larger than 10 MB")
        elif not path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            errors.append(f"references[{rid}]: image must be png, jpg, jpeg or webp")
        else:
            try:
                from PIL import Image
                with Image.open(path) as im:
                    if max(im.size) > 2500:
                        warnings.append(f"references[{rid}]: {im.size[0]}x{im.size[1]} is large; high-res references can cause fingerprint-like textures (official guide); 1K-2K is enough")
            except Exception:
                pass

    clips = plan.get("clips") or []
    if not clips:
        errors.append("clips is empty")
    ids = [c.get("id") for c in clips]
    if len(set(ids)) != len(ids):
        errors.append("clip ids must be unique")
    total_tasks = 0
    for c in clips:
        cid = c.get("id", "?")
        mode = c.get("mode", "reference")
        ratio = c.get("ratio", defaults.get("ratio", "9:16"))
        resolution = c.get("resolution", defaults.get("resolution", "480p"))
        duration = c.get("duration", -1)
        prompt = c.get("prompt") or ""
        total_tasks += 1
        if mode not in MODES:
            errors.append(f"{cid}: mode must be one of {sorted(MODES)}")
        if ratio not in RATIOS:
            errors.append(f"{cid}: ratio {ratio!r} invalid")
        version = str(c.get("version", defaults.get("version", "2.5")))
        rules = VERSION_RULES.get(version)
        if rules is None:
            errors.append(f"{cid}: version {version!r} must be one of {sorted(VERSION_RULES)}")
            rules = VERSION_RULES["2.5"]
        lo, hi = rules["duration"]
        if resolution not in RESOLUTIONS or resolution not in rules["resolutions"]:
            errors.append(f"{cid}: resolution {resolution!r} invalid for Seedance {version}")
        if not (duration == -1 or (isinstance(duration, int) and lo <= duration <= hi)):
            errors.append(f"{cid}: duration must be -1 or an integer {lo}-{hi} s for Seedance {version}")
        if "REPLACE ME" in prompt or len(prompt.strip()) < 80:
            errors.append(f"{cid}: prompt is missing or too short")
            continue
        cref = c.get("references") or []
        images = [r for r in cref if refs.get(r, {}).get("kind") != "video"]
        videos = [r for r in cref if refs.get(r, {}).get("kind") == "video"]
        for r in cref:
            if r not in refs:
                errors.append(f"{cid}: reference {r!r} is not defined in references")
        if len(images) > MAX_IMAGES or len(videos) > MAX_VIDEOS:
            errors.append(f"{cid}: too many references (max {MAX_IMAGES} images, {MAX_VIDEOS} videos)")
        # @ImageN / @VideoN binding: numbers follow the order of the clip's references list
        used_img = {int(n) for n in re.findall(r"@Image\s?(\d+)", prompt)}
        used_vid = {int(n) for n in re.findall(r"@Video\s?(\d+)", prompt)}
        for n in used_img:
            if n < 1 or n > len(images):
                errors.append(f"{cid}: prompt mentions @Image{n} but the clip has {len(images)} image reference(s)")
        for n in used_vid:
            if n < 1 or n > len(videos):
                errors.append(f"{cid}: prompt mentions @Video{n} but the clip has {len(videos)} video reference(s)")
        for i in range(1, len(images) + 1):
            if i not in used_img:
                errors.append(f"{cid}: image reference #{i} ({images[i - 1]}) is never bound as @Image{i} in the prompt")
        for i in range(1, len(videos) + 1):
            if i not in used_vid:
                errors.append(f"{cid}: video reference #{i} ({videos[i - 1]}) is never bound as @Video{i} in the prompt")
        n_products = sum(1 for r in cref if refs.get(r, {}).get("kind") == "product")
        if mode == "reference" and n_products > 1:
            warnings.append(f"{cid}: {n_products} personalized products in one clip can swap portraits or names; bind each product to its owner by @Image number in the prompt and zoom-check every item (ugc_shot_patterns.md)")
        ff = str(c.get("first_frame") or "")
        if ff and re.search(r"printed|overlay|composite", ff, re.I):
            errors.append(f"{cid}: first_frame {ff} looks like a composited product still; use the product-personalizer images as references instead")
        if mode == "reference" and not cref:
            warnings.append(f"{cid}: reference mode without references is plain text-to-video (no person/product consistency)")
        if mode == "edit":
            if not videos:
                errors.append(f"{cid}: edit mode needs a video reference")
            if ratio != "adaptive" or duration != -1:
                errors.append(f"{cid}: edit mode requires ratio adaptive and duration -1")
            if not EDIT_TRIGGERS.search(prompt):
                errors.append(f"{cid}: edit mode prompt needs an editing trigger (edit the video / add / remove / replace / modify)")
        if mode == "extend":
            if not videos:
                errors.append(f"{cid}: extend mode needs a video reference")
            if ratio != "adaptive":
                errors.append(f"{cid}: extend mode requires ratio adaptive")
            if not EXTEND_TRIGGERS.search(prompt):
                errors.append(f"{cid}: extend mode prompt needs an extension trigger (extend / continue)")
        if not NO_SUBTITLES.search(prompt):
            errors.append(f"{cid}: prompt must state 'No subtitles' (captions are added by video-assembly)")
        if not NO_TEXT.search(prompt):
            warnings.append(f"{cid}: add 'no on-screen text, no captions' as well")
        low = prompt.lower()
        hits = [t for t in forbidden if t in low]
        if hits:
            errors.append(f"{cid}: prompt contains do-not-copy terms {hits}")
        if INTENSE.search(prompt):
            warnings.append(f"{cid}: intense emotional wording can cause glowing eyes; use neutral words (official guide)")
        if re.search(r"[\"“][^\"”]{4,}[\"”]", prompt) and "exactly as shown" not in low and "as shown in @image" not in low:
            warnings.append(f"{cid}: quoted dialogue/text can trigger subtitles or misspellings; refer to the product image instead")
        if len(prompt) > 1800:
            warnings.append(f"{cid}: prompt is {len(prompt)} chars; long prompts dilute control (aim for 600-1200)")
        if mode == "reference" and duration != -1:
            segs = [(float(a), float(b)) for a, b in TIMESTAMP.findall(prompt)]
            if segs:
                segs.sort()
                if abs(segs[0][0]) > 0.01 or abs(segs[-1][1] - duration) > 0.6:
                    warnings.append(f"{cid}: timestamps {segs[0][0]}-{segs[-1][1]}s do not cover the full {duration} s clip")
                for (a1, b1), (a2, b2) in zip(segs, segs[1:]):
                    if abs(b1 - a2) > 0.6:
                        warnings.append(f"{cid}: timeline gap between {b1}s and {a2}s (keep the timeline continuous)")
            else:
                warnings.append(f"{cid}: no timestamps; use '0-3s: ... 3-8s: ...' to control the shot order")
        if c.get("audio"):
            if not re.search(r"no (background )?music|no bgm", low):
                errors.append(f"{cid}: audio is on; the prompt must say 'no music, no BGM' and describe only natural sound (room tone, giggles, fabric), because generated music triggered copyright rejections")
        size_stmt = plan.get("product", {}).get("size_statement")
        if size_stmt and not size_stmt.startswith("<") and any(refs.get(r, {}).get("kind") == "product" for r in cref):
            key = re.findall(r"\d+\s*[x×]\s*\d+", size_stmt)
            if not (key and any(k.replace(" ", "") in low.replace(" ", "") for k in key)):
                errors.append(f"{cid}: product shot must state the product size from product.size_statement ({size_stmt[:60]}...) so the model renders it at the right scale")
        if any(refs.get(r, {}).get("kind") == "person" for r in cref) and any(refs.get(r, {}).get("kind") == "product" for r in cref) and not re.search(r"face[s]? (is|are|stay[s]?|remain[s]?) (fully )?visible|whole face|faces visible", low):
            warnings.append(f"{cid}: say that the person's face stays fully visible above/beside the product (products must never cover faces)")
        layout = plan.get("product", {}).get("layout")
        shows_product = any(refs.get(r, {}).get("kind") == "product" for r in cref)
        if shows_product and layout and not layout.startswith("<"):
            key_words = [w for w in re.findall(r"[a-z]{4,}", layout.lower()) if w not in ("with", "that", "this", "from", "exactly", "shows", "side")][:6]
            if sum(1 for w in key_words if w in low) < max(2, len(key_words) // 2):
                warnings.append(f"{cid}: the product layout ({layout[:80]}...) is not restated in the prompt; say which side/area carries what, so the model does not mirror the sample")
        if any(refs.get(r, {}).get("kind") == "staging" for r in cref):
            warnings.append(f"{cid}: staging references must not show real people (sample frames with people are rejected by "
                            "Seedance's privacy filter, and their faces could leak into the ad); use a frame without people or describe the staging in words")
        if any(refs.get(r, {}).get("kind") == "staging" for r in cref) and not re.search(r"(framing|wrap|drape|staging|composition)[^.]*as in @image", low):
            warnings.append(f"{cid}: a staging reference (sample keyframe) is attached but the prompt does not say 'framing / how the blankets wrap and drape as in @ImageN; the printed design follows @Image<product>'")
        if any(refs.get(r, {}).get("kind") == "texture" for r in cref) and "texture" not in low and "material" not in low:
            warnings.append(f"{cid}: a texture reference is attached but the prompt does not describe the material shot")
        if shows_product and names and not any(n.lower() in low for n in names):
            warnings.append(f"{cid}: the product is referenced but none of the names {names} is mentioned; say the name must appear exactly as in the product image")
        if any(refs.get(r, {}).get("kind") == "person" for r in cref) and not re.search(r"same (person|woman|man|child|girl|boy)|consistent|throughout", low):
            warnings.append(f"{cid}: state that the person from @ImageN stays the same in every shot (consistency)")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "clips": len(clips), "paid_tasks": total_tasks}


def validate(args):
    plan = load(args.plan, "prompts.json")
    analysis = load(args.analysis, "analysis.json") if args.analysis else None
    res = validate_plan(plan, analysis)
    out(res, 0 if res["ok"] else 1)


# ----------------------------------------------------------------------------- render
def build_command(plan, clip):
    refs = {r.get("id"): r for r in plan.get("references", [])}
    d = plan.get("defaults", {})
    parts = ["node", SEEDANCE_SCRIPT, "--confirmed",
             "--version", str(clip.get("version", d.get("version", "2.5"))),
             *(["--model", str(clip.get("model", d.get("model")))] if clip.get("model", d.get("model")) else []),
             "--ratio", str(clip.get("ratio", d.get("ratio", "9:16"))),
             "--duration", str(clip.get("duration", -1)),
             "--resolution", str(clip.get("resolution", d.get("resolution", "480p"))),
             "--prompt", clip["prompt"]]
    for rid in clip.get("references") or []:
        r = refs.get(rid, {})
        if r.get("kind") == "video":
            parts += ["--reference-video", r.get("url") or r.get("path")]
        else:
            parts += ["--reference-image", r.get("path") or r.get("url")]
    if clip.get("first_frame"):
        parts += ["--first-frame", clip["first_frame"]]
        i = parts.index("--ratio"); parts[i + 1] = "adaptive"
    mode = clip.get("mode", "reference")
    if mode in ("edit", "extend"):
        parts += ["--omni-task-type", mode]
    if clip.get("seed") is not None:
        parts += ["--seed", str(clip["seed"])]
    if clip.get("audio"):
        parts += ["--generate-audio"]
    parts += ["--download", clip.get("download", d.get("download", "/mnt/session/outputs/07_clips"))]
    return parts


def render(args):
    plan = load(args.plan, "prompts.json")
    res = validate_plan(plan)
    if not res["ok"]:
        out({"ok": False, "error": "plan is invalid; run validate", **res}, 1)
    out_dir = os.path.dirname(os.path.abspath(args.plan))
    lines = ["#!/usr/bin/env bash", "# One billable Seedance task per line. Submit them together with generate-with-seedance batch.py; never re-run a line whose result is uncertain.", "set -u"]
    rendered, dry = [], []
    for clip in plan["clips"]:
        cmd = build_command(plan, clip)
        txt = os.path.join(out_dir, f"{clip['id']}.prompt.txt")
        with open(txt, "w") as fh:
            fh.write(clip["prompt"])
        lines.append("# " + clip["id"] + f" (attempt {clip.get('attempt', 1)}, {clip.get('duration')} s, refs: {', '.join(clip.get('references') or [])})")
        lines.append(" ".join(shlex.quote(p) for p in cmd))
        rendered.append({"id": clip["id"], "duration": clip.get("duration"), "references": clip.get("references"), "prompt_file": txt,
                         "prompt_head": clip["prompt"].strip().split("\n")[0][:140]})
        if args.dry_run:
            dcmd = [p for p in cmd if p != "--confirmed"] + ["--dry-run"]
            try:
                proc = subprocess.run(dcmd, capture_output=True, text=True, timeout=120)
                ok = proc.returncode == 0
                body = proc.stdout[-1200:] if ok else (proc.stderr or proc.stdout)[-600:]
            except (OSError, subprocess.TimeoutExpired) as error:
                ok, body = False, str(error)
            dry.append({"id": clip["id"], "ok": ok, "output": body})
    script = os.path.join(out_dir, "commands.sh")
    with open(script, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(script, 0o755)
    result = {"ok": all(d["ok"] for d in dry) if dry else True, "commands": script, "clips": rendered,
              "paid_tasks": len(rendered), "warnings": res["warnings"]}
    if dry:
        result["dry_runs"] = dry
    out(result, 0 if result["ok"] else 1)


def strip(args):
    """Compose product previews side by side (left-to-right order, no text) as a layout reference for multi-item stills."""
    from PIL import Image
    ims = [Image.open(p).convert("RGB") for p in args.images]
    h = 900
    ims = [im.resize((int(im.width * h / im.height), h)) for im in ims]
    gap = 24
    canvas = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) + 1), h + 2 * gap), (245, 240, 232))
    x = gap
    for im in ims:
        canvas.paste(im, (x, gap))
        x += im.width + gap
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    canvas.save(args.out)
    out({"ok": True, "strip": args.out, "panels": len(ims), "order": args.images})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("template")
    t.add_argument("--analysis", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--version", default="2.5", help="Seedance version from the brief's VIDEO_MODEL line (2.5, 2.0, 2.0-fast, 2.0-mini)")
    t.add_argument("--model", help="inference endpoint from the brief's VIDEO_MODEL line (ep-...)")
    v = sub.add_parser("validate")
    v.add_argument("--plan", required=True)
    v.add_argument("--analysis")
    st = sub.add_parser("strip")
    st.add_argument("--images", nargs="+", required=True)
    st.add_argument("--out", required=True)
    r = sub.add_parser("render")
    r.add_argument("--plan", required=True)
    r.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    {"template": template, "validate": validate, "render": render, "strip": strip}[args.cmd](args)


if __name__ == "__main__":
    main()
