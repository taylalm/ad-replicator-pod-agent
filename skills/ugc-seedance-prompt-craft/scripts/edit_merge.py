#!/usr/bin/env python3
"""Merge one-product-per-edit images into one still (natural prints, no identity mixing).

Workflow for a shot with several personalized products (e.g. four kids, each in their own blanket):
1. Generate the scene with PLAIN products, each a clearly different solid colour (generate-with-seedream).
2. For EACH product, run one Seedream edit on that same plain still with only that product's personalizer image:
   "Edit image 1. Change only the <colour> <product> of <owner>: print on it exactly the design of image 2 ...
    Keep everything else in image 1 exactly unchanged: the other products stay plain ...".
   Never chain the edits (each edit re-renders the picture and erases earlier prints); always edit the plain still.
3. Merge: this script takes each edited product from its own edit, cut out by that product's colour mask
   (union of the mask in the plain still and in the edit), and pastes it onto the plain still.

Usage:
  python3 edit_merge.py --base still_plain.png --out still_merged.png \
      --item "purple blanket wrapped around the girl on the far left|edit_harper.png|product_harper.png" \
      --item "pink blanket wrapped around the toddler second from left|edit_mila.png|product_mila.png" ... \
      [--boxes boxes.json] [--tol 26]
--item is "<description of the product in the still>|<edited image>|<personalizer preview>". The preview gives the
product colour; product boxes come from the vision model (or --boxes, as written by print_overlay.py) and are saved
next to the output. Needs pillow, numpy, scipy and print_overlay.py in the same folder.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="the plain still all edits were made from")
    ap.add_argument("--out", required=True)
    ap.add_argument("--item", action="append", required=True, help='"<description>|<edited image>|<preview image>"')
    ap.add_argument("--boxes", help="JSON {description: [x0,y0,x1,y1]} (skips detection)")
    ap.add_argument("--tol", type=float, default=26)
    ap.add_argument("--model", default="seed-2-0-lite-260428")
    a = ap.parse_args()
    import print_overlay as po
    po.deps()
    import numpy as np
    from PIL import Image, ImageFilter

    items = []
    for spec in a.item:
        parts = [x.strip() for x in spec.split("|")]
        if len(parts) != 3 or not all(os.path.isfile(p) for p in parts[1:]):
            po.out({"ok": False, "error": f"--item needs 'description|existing edited image|existing preview': {spec}"}, 2)
        items.append({"d": parts[0], "edit": parts[1], "preview": parts[2]})
    base = Image.open(a.base).convert("RGB")
    boxes = json.load(open(a.boxes)) if a.boxes else po.detect_boxes(a.base, [i["d"] for i in items], a.model)
    for it in items:
        kh = po.key_hue(po.preview_panel(it["preview"]))
        if kh is None:
            po.out({"ok": False, "error": f"no product colour found in {it['preview']}"}, 1)
        it["hue"] = po.still_hue(base, kh, None, boxes.get(it["d"]), [])
    out = np.asarray(base).astype(float)
    applied = []
    for it in items:
        ed = Image.open(it["edit"]).convert("RGB")
        if ed.size != base.size:
            ed = ed.resize(base.size, Image.LANCZOS)
        others = [x["hue"] for x in items if x is not it]
        box = boxes.get(it["d"])
        m = po.colorkey_mask(base, it["hue"], a.tol, None, [], box, others) | po.colorkey_mask(ed, it["hue"], a.tol, None, [], box, others)
        soft = np.asarray(Image.fromarray((m * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(3))).astype(float)[..., None] / 255
        out = out * (1 - soft) + np.asarray(ed).astype(float) * soft
        applied.append({"item": it["d"], "edit": os.path.basename(it["edit"]), "hue": round(it["hue"]), "box": box, "mask_px": int(m.sum())})
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    Image.fromarray(out.astype("uint8")).save(a.out)
    bfile = os.path.splitext(a.out)[0] + "_boxes.json"
    with open(bfile, "w") as fh:
        json.dump({i["d"]: boxes.get(i["d"]) for i in items}, fh, indent=1)
    missing = [x["item"] for x in applied if x["mask_px"] < 500]
    po.out({"ok": not missing, "out": a.out, "applied": applied, "missing": missing, "boxes_file": bfile,
            "next": "View the result reduced and zoom into every product: its own print only, no plain patches, no seams across faces. "
                    "Redo one product's edit if its print is wrong, then merge again; animate with --first-frame and small motion."},
           0 if not missing else 1)


if __name__ == "__main__":
    main()
