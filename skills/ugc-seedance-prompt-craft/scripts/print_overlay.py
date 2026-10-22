#!/usr/bin/env python3
r"""Print the exact website artwork onto products in a still (deterministic, no generative text).

For shots with several personalized items the video model mixes portraits and invents names. This
script takes a still of the scene (people with PLAIN or roughly printed products), finds the visible
front panel of each product (four corners, via the vision model or given by hand), and warps the real
website preview onto it with the fabric's own shading, so every portrait and name in the first frame
is exactly the website's. The result is then animated with generate-with-seedance --first-frame.

Two modes: --mode colorkey textures every whole product (wrapped/draped/folded, each a distinct plain colour in the still);
--mode quad (default) warps the preview onto a flat front panel.

Usage:
  python3 print_overlay.py [--mode colorkey] --still still.png --out still_printed.png \
      --item "purple blanket, left|/mnt/.../product_harper.png" \
      --item "pink blanket, second from left|/mnt/.../product_mila.png" ... \
      [--quads quads.json] [--model seed-2-0-lite-260428] [--strength 0.9]

--item is "<description of the product in the still>|<preview image>[|crop=x0,y0,x1,y1]", in any order. The optional crop
(fractions of the product panel) prints only part of the design, e.g. a band of the name pattern without the portrait on
the visible face of a folded blanket in a stack: crop=0.03,0.04,0.97,0.22.
--quads skips detection: {"<description>": [[x,y],[x,y],[x,y],[x,y]], ...} as 0-1 fractions,
clockwise from top-left. Detected quads are written next to the output for review.
"""
import argparse
import base64
import io
import json
import os
import re
import sys
import urllib.request

DEFAULT_MODEL = "seed-2-0-lite-260428"


def out(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    sys.exit(code)


def deps():
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        out({"ok": False, "error": "needs pillow and numpy (scipy recommended for colorkey): pip install pillow numpy scipy"}, 2)


def preview_panel(path):
    """Crop the website preview to the product itself (drop the flat page background around it)."""
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(int)
    bg = a[2:12, 2:12].reshape(-1, 3).mean(0)
    diff = np.abs(a - bg).sum(2) > 40
    ys, xs = np.where(diff)
    if len(xs) < 100:
        return im
    pad = 2
    return im.crop((max(0, xs.min() + pad), max(0, ys.min() + pad), min(im.width, xs.max() - pad), min(im.height, ys.max() - pad)))


def detect_quads(still, descriptions, model):
    key = os.environ.get("ARK_API_KEY")
    if not key:
        out({"ok": False, "error": "ARK_API_KEY missing: pass --quads instead"}, 2)
    from PIL import Image
    im = Image.open(still).convert("RGB")
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    listing = "\n".join(f"- {d}" for d in descriptions)
    text = ("For each product listed below, give the four corners of the largest flat-ish visible FRONT area of that product "
            "(the area where its print would be seen), excluding any face, hand, arm, foot or other person, as fractions 0-1 of the image "
            "width and height, clockwise from top-left. Reply with ONLY JSON: {\"<description exactly as given>\": [[x,y],[x,y],[x,y],[x,y]], ...}\n"
            + listing)
    body = {"model": model, "temperature": 0, "max_tokens": 1200, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}},
        {"type": "text", "text": text}]}]}
    req = urllib.request.Request((os.environ.get("ARK_BASE_URL") or "https://ark.ap-southeast.bytepluses.com/api/v3") + "/chat/completions",
                                 data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    txt = data["choices"][0]["message"]["content"]
    if isinstance(txt, list):
        txt = "".join(c.get("text", "") for c in txt)
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        out({"ok": False, "error": "vision model returned no quads", "raw": txt[:500]}, 1)
    return json.loads(m.group(0))


def _vision(still, text, model, max_tokens=1200):
    key = os.environ.get("ARK_API_KEY")
    if not key:
        return None
    from PIL import Image
    im = Image.open(still).convert("RGB")
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}},
        {"type": "text", "text": text}]}]}
    req = urllib.request.Request((os.environ.get("ARK_BASE_URL") or "https://ark.ap-southeast.bytepluses.com/api/v3") + "/chat/completions",
                                 data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        txt = json.loads(resp.read())["choices"][0]["message"]["content"]
    if isinstance(txt, list):
        txt = "".join(c.get("text", "") for c in txt)
    return txt


def detect_boxes(still, descriptions, model):
    """Bounding box (fractions) of the WHOLE visible product for each description, so a colour mask never leaks
    into a neighbour, the wall or the couch."""
    listing = "\n".join(f"- {d}" for d in descriptions)
    txt = _vision(still, "For each product listed below give the bounding box of the WHOLE visible product (all of its fabric, "
                  "including parts wrapped around a person, but not the person's head), normalised 0-1. Reply ONLY JSON: "
                  "{\"<description exactly as given>\": [x0, y0, x1, y1], ...}\n" + listing, model)
    if not txt:
        return {}
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        return {k: [float(v) for v in b] for k, b in json.loads(m.group(0)).items()} if m else {}
    except (ValueError, TypeError):
        return {}


def detect_faces(still, model):
    """Boxes (fractions) of real faces and of bare hands/feet in the still, as (kind, (x0, y0, x1, y1)).
    Faces are never printed on; inside hand/foot boxes only skin-coloured pixels are kept free."""
    try:
        txt = _vision(still, "List every real human face, and every visible bare hand or foot, in this photo as boxes normalised 0-1. "
                      "Reply ONLY a JSON array [{\"kind\": \"face\"|\"hand\"|\"foot\", \"x0\":..,\"y0\":..,\"x1\":..,\"y1\":..}].", model, 800)
        m = re.search(r"\[.*\]", txt or "", re.S)
        return [(str(b.get("kind", "face")), (float(b["x0"]), float(b["y0"]), float(b["x1"]), float(b["y1"]))) for b in json.loads(m.group(0))] if m else []
    except Exception:
        return []


def perspective_coeffs(dst, src):
    """Coefficients for PIL's PERSPECTIVE transform mapping output (dst) points to input (src) points."""
    import numpy as np
    A, B = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); B.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); B.append(v)
    return np.linalg.solve(np.array(A, float), np.array(B, float)).tolist()


def overlay(still_img, panel, quad_px, strength):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    W, H = still_img.size
    src = [(0, 0), (panel.width, 0), (panel.width, panel.height), (0, panel.height)]
    coeffs = perspective_coeffs(quad_px, src)
    warped = panel.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon([tuple(p) for p in quad_px], fill=255)
    feather = max(2, int(min(W, H) * 0.006))
    mask = mask.filter(ImageFilter.GaussianBlur(feather))
    base = np.asarray(still_img).astype(float) / 255.0
    art = np.asarray(warped).astype(float) / 255.0
    m = np.asarray(mask).astype(float)[..., None] / 255.0
    # keep the fabric's folds and light: scale the artwork by the local luminance of the original fabric
    lum = (0.299 * base[..., 0] + 0.587 * base[..., 1] + 0.114 * base[..., 2])
    region = lum[np.asarray(mask) > 128]
    ref = float(np.median(region)) if region.size else 0.6
    shade = np.clip(np.asarray(Image.fromarray((lum * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(3))).astype(float) / 255.0 / max(ref, 1e-3), 0.55, 1.25)[..., None]
    shaded = np.clip(art * shade, 0, 1)
    result = base * (1 - m * strength) + shaded * (m * strength)
    return Image.fromarray((result * 255).astype("uint8"))


def _hsv(arr):
    """arr float 0-1 HxWx3 -> hue degrees, sat, val."""
    import numpy as np
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    mx = arr.max(-1); mn = arr.min(-1); d = mx - mn + 1e-6
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    s = np.where(mx > 0, (mx - mn) / (mx + 1e-6), 0)
    return h, s, mx


def key_hue(panel):
    """Dominant hue of the product's background colour (ignores white lettering and the portrait)."""
    import numpy as np
    a = np.asarray(panel.convert("RGB").resize((200, 200))).astype(float) / 255
    h, s, v = _hsv(a)
    sel = (s > 0.25) & (v > 0.3)
    if sel.sum() < 50:
        return None
    hist, edges = np.histogram(h[sel], bins=36, range=(0, 360))
    k = int(hist.argmax())
    return float((edges[k] + edges[k + 1]) / 2)


def _box_sel(shape, box):
    import numpy as np
    H, W = shape[:2]
    sel = np.zeros((H, W), bool)
    x0, y0, x1, y1 = box
    sel[max(0, int(y0 * H)):min(H, int(y1 * H) + 1), max(0, int(x0 * W)):min(W, int(x1 * W) + 1)] = True
    return sel


def still_hue(still_img, hue, x_range=None, box=None, exclude=None):
    """The plain product's own hue in the still: the hue peak nearest to the artwork's hue (pastel fabric differs),
    measured inside the product's box when known, with faces/hands left out."""
    import numpy as np
    a = np.asarray(still_img.resize((still_img.width // 4, still_img.height // 4))).astype(float) / 255
    h, s, v = _hsv(a)
    sel = (s > 0.08) & (v > 0.2)
    if box:
        sel &= _box_sel(a.shape, box)
    for kind, fb in exclude or []:
        sel &= ~_box_sel(a.shape, fb)
    if x_range:
        W = a.shape[1]
        xs = np.arange(W)[None, :].repeat(a.shape[0], 0)
        sel &= (xs >= x_range[0] * W) & (xs <= x_range[1] * W)
    hist, edges = np.histogram(h[sel], bins=72, range=(0, 360))
    centers = (edges[:-1] + edges[1:]) / 2
    dist = np.minimum(np.abs(centers - hue), 360 - np.abs(centers - hue))
    score = hist * np.exp(-(dist / 22.0) ** 2) * (dist <= 45)  # prefer the peak closest to the artwork colour
    if score.max() == 0:
        return hue
    return float(centers[int(np.argmax(score))])


def _skin(h, s, v):
    return ((h < 50) | (h > 345)) & (s > 0.12) & (s < 0.75) & (v > 0.25)


def _exclude(m, exclude, h, s, v, pad):
    H, W = m.shape
    for kind, (fx0, fy0, fx1, fy1) in exclude or []:
        pw, ph = (fx1 - fx0) * pad, (fy1 - fy0) * pad
        ys, ye = max(0, int((fy0 - ph) * H)), min(H, int((fy1 + ph) * H))
        xs, xe = max(0, int((fx0 - pw) * W)), min(W, int((fx1 + pw) * W))
        if kind == "face":
            m[ys:ye, xs:xe] = False
        else:  # a hand/foot resting on the product: free only its skin
            m[ys:ye, xs:xe] &= ~_skin(h[ys:ye, xs:xe], s[ys:ye, xs:xe], v[ys:ye, xs:xe])
    return m


def colorkey_mask(still_img, hue, tol=20, x_range=None, exclude=None, box=None, others=()):
    """Mask of the plain product in the still: pixels of that hue, largest connected region; faces (exclude boxes) removed."""
    import numpy as np
    from PIL import Image, ImageFilter
    a = np.asarray(still_img).astype(float) / 255
    h, s, v = _hsv(a)
    dh = np.minimum(np.abs(h - hue), 360 - np.abs(h - hue))
    m = (dh < tol) & (s > 0.06) & (v > 0.18)
    for oh in others:  # another product in a near colour: each pixel goes to the closest product hue
        m &= dh <= np.minimum(np.abs(h - oh), 360 - np.abs(h - oh))
    m = _exclude(m, exclude, h, s, v, 0.25)
    if x_range:
        W = a.shape[1]
        xs = np.arange(W)[None, :]
        m &= (xs >= x_range[0] * W) & (xs <= x_range[1] * W)
    if box:
        m &= _box_sel(m.shape, box)
    img = Image.fromarray((m * 255).astype("uint8")).filter(ImageFilter.MedianFilter(5))
    m = np.asarray(img) > 127
    try:
        from scipy import ndimage  # optional: keep the largest blob, close fold highlights, fill holes
        lab, n = ndimage.label(m)
        if n > 1:  # keep every sizeable piece (a hand or a fold shadow can split one product in two)
            sizes = np.asarray(ndimage.sum(m, lab, range(1, n + 1)))
            keep = np.where(sizes >= sizes.max() * 0.08)[0] + 1
            m = np.isin(lab, keep)
        r = max(2, int(min(m.shape) * 0.012))
        m = ndimage.binary_closing(m, structure=np.ones((3, 3)), iterations=r)
        # a product cut by the frame edge: close that edge too (bridging gaps), so highlights touching it get filled
        H, W = m.shape
        mp = np.pad(m, 1, constant_values=False)
        def bridge(line):
            idx = np.where(line)[0]
            out_ = np.zeros_like(line)
            if idx.size:
                out_[idx.min():idx.max() + 1] = True
            return out_
        if m[0, :].sum() > W * 0.02:
            mp[0, 1:-1] = bridge(m[0, :])
        if m[-1, :].sum() > W * 0.02:
            mp[-1, 1:-1] = bridge(m[-1, :])
        if m[:, 0].sum() > H * 0.02:
            mp[1:-1, 0] = bridge(m[:, 0])
        if m[:, -1].sum() > H * 0.02:
            mp[1:-1, -1] = bridge(m[:, -1])
        m = ndimage.binary_fill_holes(mp)[1:-1, 1:-1]
        if box:
            m &= _box_sel(m.shape, box)
        m = _exclude(m, exclude, h, s, v, 0.1)  # filling must never paint over a face or a hand
    except ImportError:
        pass
    return m


def colorkey_print(still_img, panel, mask, strength=0.95, portrait_at=None, scale_k=1.0, fit="height"):
    """Texture the whole visible product with the website artwork: the panel covers the product's bounding box,
    the fabric's own shading (folds, light) is kept, sherpa/skin/faces outside the mask stay untouched."""
    import numpy as np
    from PIL import Image, ImageFilter
    ys, xs = np.where(mask)
    if len(xs) < 500:
        return still_img, None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    # fit="height": the product's length spans the visible product top to bottom (a blanket wrapped chin to toes);
    # "width": its width spans the visible front; "cover": whichever is larger. scale_k fine-tunes (0.8 = smaller print).
    scale = {"height": bh / panel.height, "width": bw / panel.width}.get(fit, max(bw / panel.width, bh / panel.height)) * scale_k
    tex = panel.resize((max(1, int(panel.width * scale)), max(1, int(panel.height * scale))), Image.BICUBIC)
    # centre the artwork on the product (or on a given point, e.g. the lap) so the portrait is visible
    if portrait_at:  # fractions of the product's bounding box
        cx, cy = x0 + portrait_at[0] * bw, y0 + portrait_at[1] * bh
    else:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left = int(cx - tex.width / 2); top = int(cy - tex.height / 2)
    pa = np.asarray(panel.convert("RGB").resize((120, 120))).astype(float) / 255
    ph_, ps_, pv_ = _hsv(pa)
    kh = key_hue(panel)
    fabric = pa[(ps_ > 0.25) & (pv_ > 0.3) & (np.minimum(np.abs(ph_ - kh), 360 - np.abs(ph_ - kh)) < 15)] if kh is not None else pa.reshape(-1, 3)
    bg = tuple(int(c * 255) for c in (np.median(fabric, 0) if len(fabric) else pa.reshape(-1, 3).mean(0)))
    canvas = Image.new("RGB", still_img.size, bg)  # beyond the artwork: plain fabric in the product colour
    canvas.paste(tex, (left, top))
    base = np.asarray(still_img).astype(float) / 255
    art = np.asarray(canvas).astype(float) / 255
    lum = 0.299 * base[..., 0] + 0.587 * base[..., 1] + 0.114 * base[..., 2]
    ref = float(np.median(lum[mask])) if mask.any() else 0.6
    lum_img = Image.fromarray((np.clip(lum, 0, 1) * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(2))
    shade = np.clip(np.asarray(lum_img).astype(float) / 255 / max(ref, 1e-3), 0.45, 1.3)[..., None]
    soft = np.asarray(Image.fromarray((mask * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(2))).astype(float)[..., None] / 255
    out = base * (1 - soft * strength) + np.clip(art * shade, 0, 1) * (soft * strength)
    return Image.fromarray((out * 255).astype("uint8")), [int(x0), int(y0), int(x1), int(y1)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--still", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--item", action="append", required=True, help='"<description>|<preview image>"')
    ap.add_argument("--quads", help="JSON file with quads per description (skips detection)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--strength", type=float, default=0.92)
    ap.add_argument("--mode", choices=["quad", "colorkey"], default="quad",
                    help="quad: warp onto a flat front panel; colorkey: the still has PLAIN products in distinct colours - texture the whole "
                         "visible product (best for wrapped/draped/folded blankets). Item extras for colorkey: |box=x0,y0,x1,y1 |x=0.0-0.3 |tol=20 "
                         "|fit=height|width|cover |scale=1.0 |at=0.5,0.5 |crop=x0,y0,x1,y1 |rotate=90")
    ap.add_argument("--boxes", help="colorkey: JSON {description: [x0,y0,x1,y1]} product boxes (skips detection)")
    ap.add_argument("--no-detect", action="store_true", help="colorkey: no vision calls for product boxes")
    a = ap.parse_args()
    deps()
    from PIL import Image
    items = []
    for it in a.item:
        if "|" not in it:
            out({"ok": False, "error": f"--item needs 'description|preview': {it}"}, 2)
        parts = it.split("|")
        d, p = parts[0], parts[1]
        crop = None
        for extra in parts[2:]:
            if extra.strip().startswith("crop="):
                crop = [float(v) for v in extra.strip()[5:].split(",")]
        if not os.path.isfile(p.strip()):
            out({"ok": False, "error": f"preview not found: {p}"}, 2)
        items.append((d.strip(), p.strip(), crop))
    img = Image.open(a.still).convert("RGB")
    if a.mode == "colorkey":
        applied, missing = [], []
        faces = detect_faces(a.still, a.model)
        parsed = []
        for it in a.item:
            parts = it.split("|")
            opts = {"d": parts[0].strip(), "p": parts[1].strip(), "xr": None, "tol": 20.0, "box": None, "scale": 1.0, "at": None, "fit": None, "crop": None, "rotate": 0}
            for extra in parts[2:]:
                k, _, v = extra.strip().partition("=")
                if k == "x":
                    lo, hi = v.split("-"); opts["xr"] = (float(lo), float(hi))
                elif k == "tol":
                    opts["tol"] = float(v)
                elif k == "box":
                    opts["box"] = [float(x) for x in v.split(",")]
                elif k == "scale":
                    opts["scale"] = float(v)
                elif k == "at":
                    opts["at"] = tuple(float(x) for x in v.split(","))
                elif k == "fit":
                    opts["fit"] = v
                elif k == "crop":
                    opts["crop"] = [float(x) for x in v.split(",")]
                elif k == "rotate":
                    opts["rotate"] = int(float(v)) % 360
            opts["fit"] = opts["fit"] or ("cover" if opts["crop"] else "height")
            parsed.append(opts)
        given = json.load(open(a.boxes)) if a.boxes else {}
        need = [o["d"] for o in parsed if not o["box"] and o["d"] not in given]
        detected = detect_boxes(a.still, need, a.model) if need and not a.no_detect else {}
        boxes = {**detected, **given}
        base_img = img.copy()
        for o in parsed:
            o["box_"] = o["box"] or boxes.get(o["d"])
            panel = preview_panel(o["p"])
            if o["crop"]:
                c = o["crop"]
                panel = panel.crop((int(c[0] * panel.width), int(c[1] * panel.height), int(c[2] * panel.width), int(c[3] * panel.height)))
            if o["rotate"]:  # a folded product shows its pattern at any angle; rotate a names-only strip to lie along the fold
                panel = panel.rotate(o["rotate"], expand=True)
            o["panel"] = panel
            kh = key_hue(panel)
            o["hue"] = None if kh is None else still_hue(base_img, kh, o["xr"], o["box_"], faces)
        for o in parsed:
            if o["hue"] is None:
                missing.append(o["d"]); continue
            others = [x["hue"] for x in parsed if x is not o and x["hue"] is not None]
            mask = colorkey_mask(base_img, o["hue"], o["tol"], o["xr"], faces, o["box_"], others)
            img, bb = colorkey_print(img, o["panel"], mask, a.strength, o["at"], o["scale"], o["fit"])
            if bb is None:
                missing.append(o["d"]); continue
            applied.append({"item": o["d"], "preview": os.path.basename(o["p"]), "hue": round(o["hue"]), "box": o["box_"], "mask_bbox_px": bb,
                            "mask_px": int(mask.sum()), "fit": o["fit"], "scale": o["scale"], "at": o["at"], "crop": o["crop"]})
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        img.save(a.out)
        bfile = os.path.splitext(a.out)[0] + "_boxes.json"
        with open(bfile, "w") as fh:
            json.dump({o["d"]: o.get("box_") for o in parsed}, fh, indent=1)
        out({"ok": not missing, "mode": "colorkey", "out": a.out, "applied": applied, "missing": missing, "faces_excluded": len(faces),
             "boxes_file": bfile,
             "next": "View the result reduced: every product printed edge to edge with exactly its own artwork, portrait visible, faces/hands/sherpa untouched. "
                     "Fix a product that leaks or is cut with |box=x0,y0,x1,y1 (or edit the boxes file and pass --boxes); a portrait that is too big or "
                     "too small with |scale=0.8 or |fit=width; move the portrait with |at=0.5,0.6 (fractions of the product box)."}, 0 if not missing else 1)
    quads = json.load(open(a.quads)) if a.quads else detect_quads(a.still, [d for d, _, _ in items], a.model)
    W, H = img.size
    applied, missing = [], []
    for d, p, crop in items:
        q = quads.get(d)
        if not q or len(q) != 4:
            missing.append(d)
            continue
        qpx = [(float(x) * W, float(y) * H) for x, y in q]
        panel = preview_panel(p)
        if crop:
            panel = panel.crop((int(crop[0] * panel.width), int(crop[1] * panel.height), int(crop[2] * panel.width), int(crop[3] * panel.height)))
        img = overlay(img, panel, qpx, a.strength)
        applied.append({"item": d, "preview": os.path.basename(p), "crop": crop, "quad": q})
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    img.save(a.out)
    qfile = os.path.splitext(a.out)[0] + "_quads.json"
    with open(qfile, "w") as fh:
        json.dump(quads, fh, indent=1)
    out({"ok": not missing, "out": a.out, "applied": applied, "missing": missing, "quads_file": qfile,
         "next": "View the result: each product must show exactly its own preview, faces and hands untouched. Adjust quads in the quads file and rerun with --quads if a panel is off, then animate with --first-frame."},
        0 if not missing else 1)


if __name__ == "__main__":
    main()
