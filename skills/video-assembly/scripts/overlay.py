#!/usr/bin/env python3
"""Lay edited captions and photo insets onto a clean master (the delivered ad without text), for the caption
editor of the web app. Same drawing code as assemble.py (fonts, presets, effects), no clip re-encoding.

  python3 overlay.py --base final_clean.mp4 --doc captions_doc.json --output final_edit_v1.mp4 [--dry-run]

captions_doc.json:
  {"size": [480, 854], "fps": 24,
   "captions": [{"text", "start", "end", "style", "position" (0-1 or a name), "x" (0-1), "enabled", "animation"}],
   "insets": [{"image", "start", "end", "position", "top", "left", "width", "arrow_to", "enabled"}],
   "reference_captions": [...]}   # the sample's own text: a copied caption is reported as a warning
Prints JSON: {"ok", "output", "captions", "insets", "warnings"}.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assemble as A  # noqa: E402


def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    sys.exit(0)


def layers_for(doc, tmp):
    size = tuple(doc.get("size") or (480, 854))
    fps = int(doc.get("fps") or 24)
    layers, warnings = [], []
    refs = [str(t) for t in doc.get("reference_captions") or [] if str(t).strip()]
    for i, cap in enumerate(doc.get("captions") or []):
        if cap.get("enabled") is False or not str(cap.get("text", "")).strip():
            continue
        hit = A.copied_from(str(cap["text"]), refs) if refs and not cap.get("approved_wording") else None
        if hit:
            warnings.append(f"caption {i + 1} is close to the sample's text \"{hit[0]}\" ({hit[1]})")
        spec = A.caption_spec(cap, size)
        new, _ = A.caption_layers(tmp, f"c{i:02d}", size, cap["text"], spec, float(cap["start"]), float(cap["end"]),
                                  cap.get("animation") or doc.get("caption_animation"), fps)
        layers += new
    for i, ins in enumerate(doc.get("insets") or []):
        if ins.get("enabled") is False or not os.path.isfile(str(ins.get("image", ""))):
            continue
        png = os.path.join(tmp, f"inset_{i:02d}.png")
        A.render_inset_layer(png, size, ins)
        i0, i1 = float(ins["start"]), float(ins["end"])
        if ins.get("animate", True):
            from PIL import Image
            with Image.open(png) as im:
                bb = im.getbbox() or (0, 0, size[0], size[1])
            pops = A.motion_frames(tmp, f"inset_{i:02d}", png, "pop", i0, 0.25, fps, ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2), "in")
            layers += pops
            i0 = pops[-1][2]
        layers.append((png, i0, i1, None))
    return layers, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--doc", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    with open(a.doc) as fh:
        doc = json.load(fh)
    if not os.path.isfile(a.base):
        A.fail(f"base video not found: {a.base}")
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    tmp = tempfile.mkdtemp(prefix="overlay_")
    try:
        layers, warnings = layers_for(doc, tmp)
        if a.dry_run:
            out({"ok": True, "dry_run": True, "layers": len(layers), "warnings": warnings})
        width, height = tuple(doc.get("size") or (480, 854))
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", a.base]
        for png, _, _, _ in layers:
            cmd += ["-i", png]
        chains, label = [f"[0:v]scale={width}:{height}[b]"], "b"
        for n, (_, start, end, _) in enumerate(layers, start=1):
            chains.append(f"[{label}][{n}:v]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[v{n}]")
            label = f"v{n}"
        os.makedirs(os.path.dirname(os.path.abspath(a.output)) or ".", exist_ok=True)
        cmd += ["-filter_complex", ";".join(chains), "-map", f"[{label}]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", a.output]
        A.run(cmd)
        out({"ok": True, "output": a.output, "captions": sum(1 for c in doc.get("captions") or [] if c.get("enabled") is not False),
               "insets": sum(1 for c in doc.get("insets") or [] if c.get("enabled") is not False), "warnings": warnings})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
