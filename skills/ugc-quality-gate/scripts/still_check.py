#!/usr/bin/env python3
"""Check a first-frame still against the sample's frame BEFORE it is animated (one cheap vision call; a clip costs
about 50 times more). The evaluator puts the two pictures side by side and lists every staging difference that a
viewer would notice, plus product and anatomy errors in the still itself.

  python3 still_check.py --still 07_clips/stills/s1_hook.png --sample-frame 01_analysis/keyframes/scene_01_a.jpg \
      --scene "<analysis scene: shot, camera_position, motion, product_state, reactions>" \
      --product "balaclava|05_personalize/product_ethan.png|<product.spec>" [--person "Ethan|04_people/person_ethan.png"] \
      --out 07_clips/checks

Checked (hard failures):
  pose_orientation  body pose or orientation relative to the set differs (sits backwards in a car, stands instead of sits)
  camera            camera position, angle or distance differs (inside vs outside a car, selfie vs third person)
  product_state     how the product is worn or held differs (rolled vs pulled down, around the neck too early)
  wrong_product     the product differs from its reference or spec (shape, print size and position, holes, colours)
  people            missing or extra people or reactors, wrong ages; a person who should react does not
  anatomy_error     extra or missing hands, fingers or limbs
  foreign_text      captions, logos or text copied into the still
The new people, the new print and new names are expected differences, never failures. Writes check_still_<name>.json.
Exit 0 PASS, 1 FAIL, 2 usage/setup error.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate  # noqa: E402

HARD = ["pose_orientation", "camera", "product_state", "wrong_product", "people", "anatomy_error", "foreign_text"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--still", required=True)
    ap.add_argument("--sample-frame", help="the sample's frame for this shot (staging truth); omit when none exists")
    ap.add_argument("--scene", required=True, help="the analysis scene in words: shot, camera_position, motion, product_state, reactions")
    ap.add_argument("--product", action="append", default=[], help='"label|image|expected description (product.spec)"')
    ap.add_argument("--person", action="append", default=[], help='"name|image"')
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=os.environ.get("QUALITY_GATE_MODEL", gate.DEFAULT_MODEL))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    for p in [a.still] + ([a.sample_frame] if a.sample_frame else []):
        if not os.path.isfile(p):
            gate.fail(f"not found: {p}")
    products, people = [], []
    for spec in a.product:
        parts = spec.split("|")
        if len(parts) < 2 or not os.path.isfile(parts[1]):
            gate.fail(f"--product needs 'label|existing image[|expected]': {spec}")
        products.append({"label": parts[0], "image": parts[1], "expected": parts[2] if len(parts) > 2 else ""})
    for spec in a.person:
        parts = spec.split("|")
        if len(parts) < 2 or not os.path.isfile(parts[1]):
            gate.fail(f"--person needs 'name|existing image': {spec}")
        people.append({"name": parts[0], "image": parts[1]})

    content = [{"type": "text", "text": f"SHOT TO REPLICATE (from the sample analysis):\n{a.scene[:2000]}"}]
    os.makedirs(a.out, exist_ok=True)
    if a.sample_frame:  # one side-by-side picture: the model compares within an image far better than across two images
        from PIL import Image, ImageDraw
        h = 900
        left, right = (Image.open(x).convert("RGB") for x in (a.sample_frame, a.still))
        left, right = (im.resize((max(1, int(im.width * h / im.height)), h)) for im in (left, right))
        pair = Image.new("RGB", (left.width + right.width + 20, h + 40), "white")
        pair.paste(left, (0, 40))
        pair.paste(right, (left.width + 20, 40))
        d = ImageDraw.Draw(pair)
        d.text((10, 12), "LEFT: SAMPLE", fill="black")
        d.text((left.width + 30, 12), "RIGHT: GENERATED STILL", fill="black")
        side = os.path.join(a.out, f"pair_{os.path.splitext(os.path.basename(a.still))[0]}.jpg")
        pair.save(side, quality=88)
        content += [{"type": "text", "text": "SIDE BY SIDE (left = sample frame, right = generated still). Compare them here first:"},
                    {"type": "image_url", "image_url": {"url": gate.data_url(side, 1400)}}]
    if a.sample_frame:
        content += [{"type": "text", "text": "SAMPLE FRAME (staging truth: pose, body orientation, camera, framing, product state, who reacts):"},
                    {"type": "image_url", "image_url": {"url": gate.data_url(a.sample_frame, 768)}}]
    for p in products:
        content += [{"type": "text", "text": f"PRODUCT REFERENCE - {p['label']}: {p['expected']}"},
                    {"type": "image_url", "image_url": {"url": gate.data_url(p["image"], 768)}}]
    for p in people:
        content += [{"type": "text", "text": f"PERSON REFERENCE - {p['name']}"}, {"type": "image_url", "image_url": {"url": gate.data_url(p["image"], 512)}}]
    content += [{"type": "text", "text": "GENERATED STILL (to check):"}, {"type": "image_url", "image_url": {"url": gate.data_url(a.still, 1024)}},
                {"type": "text", "text":
                 "First OBSERVE each picture on its own, then COMPARE. For the sample frame (or, without one, the shot description) and for the "
                 "generated still, fill the same fields in plain words: torso_facing (which way the chest points relative to the set, e.g. 'toward the "
                 "windshield / car front', 'toward the camera', 'toward the rear of the car'); head (turned which way, relative to the torso); "
                 "seat_or_stance (e.g. 'driver's seat behind the wheel', 'leaning out of the window', 'standing'); camera (where the phone is: inside or "
                 "outside, in front or beside, height, distance, who holds it); hands (count them and say what each does); product_state (what the "
                 "product covers right now: crown, face, neck - and what is rolled up or not yet on); neck_area (bare skin, collar, or fabric); "
                 "people_and_reactions; framing (subject size and position, headroom); text (any caption or logo). "
                 "Then compare field by field. Expected differences, never failures: the new people, the new printed design from the product "
                 "reference, names, colours of clothes. Every other mismatch a viewer would notice is an issue: torso_facing, head, seat_or_stance -> "
                 "pose_orientation; camera -> camera; product_state or neck_area -> product_state; the product against its reference and expected "
                 "description (shape, print size and position, solid vs see-through fabric, holes, colours, mirrored) -> wrong_product; people and "
                 "reactions -> people; more than two hands per person or extra limbs -> anatomy_error; captions or logos -> foreign_text. "
                 "Reply with ONLY JSON: {\"sample\": {fields}, \"still\": {fields}, \"verdict\": \"PASS\"|\"FAIL\", \"issues\": [{\"kind\": one of "
                 + json.dumps(HARD + ["minor"]) + ", \"detail\": \"sample: ... / still: ...\", \"fix\": \"how to change the still prompt\"}], "
                 "\"summary\": \"one sentence\"}"}]
    messages = [{"role": "system", "content": "You are a strict continuity supervisor for recreated video shots of a personalized-gifts brand."},
                {"role": "user", "content": content}]
    os.makedirs(a.out, exist_ok=True)
    tag = os.path.splitext(os.path.basename(a.still))[0]
    if a.dry_run:
        gate.out({"ok": True, "dry_run": True, "still": a.still, "sample_frame": a.sample_frame, "products": len(products), "people": len(people), "model": a.model})
    key = os.environ.get("ARK_API_KEY")
    if not key:
        gate.fail("ARK_API_KEY missing")
    base = os.environ.get("ARK_BASE_URL", gate.DEFAULT_BASE)
    res, raw, resp = None, "", {}
    for _ in range(2):
        resp = gate.call_model(base, key, a.model, messages, max_tokens=3000)
        raw = resp["choices"][0]["message"]["content"]
        if isinstance(raw, list):
            raw = "".join(c.get("text", "") for c in raw)
        res = gate.parse_json(raw)
        if res:
            break
    if not res:
        res = {"verdict": "FAIL", "issues": [{"kind": "minor", "detail": "evaluator reply was not JSON: " + raw[:300]}]}
    issues = res.get("issues") or []
    hard = [i for i in issues if i.get("kind") in HARD]
    verdict = "FAIL" if hard or str(res.get("verdict", "")).upper() != "PASS" else "PASS"
    report = {"still": a.still, "sample_frame": a.sample_frame, "verdict": verdict, "hard_failures": hard, "issues": issues,
              "observed": {"sample": res.get("sample"), "still": res.get("still")},
              "summary": res.get("summary"), "model": a.model, "usage": resp.get("usage")}
    path = os.path.join(a.out, f"check_still_{tag}.json")
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    gate.out({"ok": True, "still": a.still, "verdict": verdict, "hard_failures": hard, "summary": report["summary"], "report": path},
             0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
