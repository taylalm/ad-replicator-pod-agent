#!/usr/bin/env python3
"""Per-clip check by an independent vision model, run on EVERY generated clip before it is accepted.

Compares sampled frames of one clip with the product truth (personalized product previews, client mockups,
gallery photos) and the people references, and checks physical plausibility. Hard failures:
  wrong_product          product differs from its reference (artwork, layout/side, colours, pattern, shape)
  wrong_personalization  an item carries another person's portrait/name, two names, or the layout is mirrored
  misspelled_text        text on the product differs from the reference (also garbled or invented letters)
  foreign_text           names or words on the product that are not in the reference
  physics_violation      e.g. two socks on one foot, an unworn item standing upright as if worn by an invisible body,
                         floating objects, fabric passing through bodies
  anatomy_error          extra/missing feet, hands, fingers or limbs, merged bodies
  wrong_count            number of people or products differs from the intent
  deformed_product       melted, duplicated or wrongly sized product (e.g. a 50x60 inch blanket shown towel-sized)
  intent_mismatch        the shot does not show what the clip was meant to show

Usage:
  python3 clip_check.py --clip clip_06.mp4 --intent "<what the clip must show>" \
      --product "Harper's socks|05_personalize/product_harper.png|left sole: quote, right sole: owl + HARPER" \
      [--product "mockup|uploads/socks_mockup.png|bookshelf pattern covers leg and top of foot"] \
      [--person "Harper|04_people/person_harper.png"] [--expected-text HARPER] --out 07_clips/checks
Writes <out>/check_<clip>.json and .md. Exit 0 PASS, 1 FAIL, 2 usage/setup error. One evaluator call per clip.
"""
import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate  # noqa: E402  (shared helpers: deps, probe, sample_frames, contact_sheet, data_url, call_model, parse_json)

HARD = ["wrong_product", "wrong_personalization", "misspelled_text", "foreign_text", "physics_violation", "anatomy_error",
        "wrong_count", "deformed_product", "intent_mismatch"]

CHECKLIST = """Check every frame. Report a problem only with a timestamp and what you see.
1. Product identity: each product matches its reference image exactly - artwork, which side/area carries which element (never mirrored or swapped), colours, all-over pattern, shape and proportions. When several personalized items appear, each item carries only its own person's portrait and name.
2. Text: every word printed on a product is spelled exactly as in its reference; garbled, invented, extra or foreign words (names that are not in the references) are failures. Ignore captions; there should be none.
3. Physical realism: wearables are worn the way people wear them - one sock or shoe per foot, a pair on a pair of feet, nothing worn twice or stacked on one limb; an item nobody wears obeys gravity (socks lie flat or slump, a blanket drapes or lies folded) and never stands upright or keeps a body shape as if an invisible person wore it; nothing floats; fabric does not pass through bodies or furniture.
4. Anatomy: every visible person has the right number of feet, legs, hands and fingers; bodies are not merged; feet belong to a visible person.
5. Size: the product's size relative to people and furniture matches the stated real size.
6. Intent: the shot shows what the intent says (people, count, action, framing); faces visible when the intent says so.
Be strict: any physics or anatomy error, any wrong or misspelled product text, any swapped portrait or name is a hard failure."""


def _repair(txt):
    """Make common evaluator JSON slips valid: free text in numeric fields (e.g. "items_on_that_body_part": 1 sock per foot)."""
    import re

    def num(m):
        val = m.group(2).strip()
        if re.fullmatch(r"-?\d+(\.\d+)?", val) or val.startswith('"') or val in ("null", "true", "false"):
            return m.group(0)
        n = re.search(r"\d+(\.\d+)?", val)
        return m.group(1) + (json.dumps(val) if m.group(1).strip().startswith('"t"') else (n.group(0) if n else "null"))
    return re.sub(r'("(?:t|items_on_that_body_part|product_match|physics)"\s*:\s*)(.*?)(?=\s*,\s*"[A-Za-z_]+"\s*:|\s*[}\]])', num, txt)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clip", required=True)
    ap.add_argument("--intent", help="what the clip must show (or use --prompt-file)")
    ap.add_argument("--prompt-file", help="the clip's prompt file; its text is used as the intent")
    ap.add_argument("--product", action="append", default=[], help='"label|image|expected description" (repeat)')
    ap.add_argument("--person", action="append", default=[], help='"name|image" (repeat)')
    ap.add_argument("--expected-text", action="append", default=[], help="exact words that must appear on the product (repeat)")
    ap.add_argument("--size", help="real product size statement, e.g. '50 x 60 inch blanket'")
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=os.environ.get("QUALITY_GATE_MODEL", gate.DEFAULT_MODEL))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    intent = a.intent or ""
    if a.prompt_file:
        try:
            intent = (intent + "\n" + open(a.prompt_file).read()).strip()
        except OSError as e:
            gate.fail(f"prompt file unreadable: {e}")
    if not intent:
        gate.fail("give --intent or --prompt-file")
    if not a.product:
        gate.fail("give at least one --product reference (the product truth)")
    products = []
    for spec in a.product:
        parts = spec.split("|")
        if len(parts) < 2 or not os.path.isfile(parts[1]):
            gate.fail(f"--product needs 'label|existing image[|expected]': {spec}")
        products.append({"label": parts[0], "image": parts[1], "expected": parts[2] if len(parts) > 2 else ""})
    people = []
    for spec in a.person:
        parts = spec.split("|")
        if len(parts) < 2 or not os.path.isfile(parts[1]):
            gate.fail(f"--person needs 'name|existing image': {spec}")
        people.append({"name": parts[0], "image": parts[1]})

    ff = gate.deps()
    info = gate.probe(ff, a.clip)
    os.makedirs(a.out, exist_ok=True)
    tag = os.path.splitext(os.path.basename(a.clip))[0]
    tmp = tempfile.mkdtemp(prefix="clipcheck_")
    frames = gate.sample_frames(ff, a.clip, info["duration_s"], max(3, a.frames), tmp, tag)
    sheet = gate.contact_sheet(frames, os.path.join(a.out, f"check_{tag}_sheet.jpg"), cols=min(4, len(frames)), title=tag)

    content = [{"type": "text", "text": f"CLIP INTENT:\n{intent[:3000]}\n" + (f"REAL SIZE: {a.size}\n" if a.size else "")
                + (f"EXACT TEXT ON THE PRODUCT: {', '.join(a.expected_text)}\n" if a.expected_text else "")}]
    for i, p in enumerate(products, 1):
        content += [{"type": "text", "text": f"PRODUCT REFERENCE {i} - {p['label']}: {p['expected']}"},
                    {"type": "image_url", "image_url": {"url": gate.data_url(p["image"], 768)}}]
    for p in people:
        content += [{"type": "text", "text": f"PERSON REFERENCE - {p['name']}"}, {"type": "image_url", "image_url": {"url": gate.data_url(p["image"], 512)}}]
    for t, path in frames:
        content += [{"type": "text", "text": f"CLIP FRAME t={t:.1f}s"}, {"type": "image_url", "image_url": {"url": gate.data_url(path, 768)}}]
    content.append({"type": "text", "text": CHECKLIST + "\nFirst observe, then judge. Observe SINGLE items, never pairs: each sock, shoe or glove is its own item (a pair worn on two feet is two observations, one per foot). For EVERY single product item visible in each key frame fill one observation: "
                    "who wears it (a person's name, 'unknown person', or 'nobody'), its 3D state ('worn' on a body part; 'flat' = empty and collapsed, "
                    "lying on a surface with no volume; 'filled' = empty but keeping the volume or shape of a body part, e.g. a sock with a rounded heel, "
                    "toes pointing up, a hollow leg or an open cuff standing up; 'held'; 'folded'), and for a worn item how many items are on that same single body part (one foot, one hand), counting itself: 1 is normal, 2 means two socks on one foot."
                    "\nReply with ONLY JSON: {\"observations\": [{\"t\": seconds, \"item\": \"...\", \"worn_by\": \"...\", \"state\": \"worn|flat|filled|held|folded\", "
                    "\"items_on_that_body_part\": n}], \"verdict\": \"PASS\"|\"FAIL\", \"product_match\": 1-5, "
                    "\"physics\": 1-5, \"issues\": [{\"kind\": one of " + json.dumps(HARD + ["minor"]) + ", \"t\": seconds, \"detail\": \"...\", "
                    "\"fix\": \"how to change the prompt or references\"}], \"summary\": \"one sentence\"}"})
    messages = [{"role": "system", "content": "You are a strict quality checker for AI-generated product video clips of a personalized-gifts brand. "
                 "You compare the clip with the product references and judge physical realism like a careful human viewer."},
                {"role": "user", "content": content}]
    if a.dry_run:
        gate.out({"ok": True, "dry_run": True, "clip": a.clip, "frames": [t for t, _ in frames], "products": len(products), "people": len(people),
                  "sheet": sheet, "model": a.model})
    key = os.environ.get("ARK_API_KEY")
    if not key:
        gate.fail("ARK_API_KEY missing")
    base = os.environ.get("ARK_BASE_URL", gate.DEFAULT_BASE)
    resp = gate.call_model(base, key, a.model, messages, max_tokens=3500)
    txt = resp["choices"][0]["message"]["content"]
    if isinstance(txt, list):
        txt = "".join(c.get("text", "") for c in txt)
    res = gate.parse_json(txt) or gate.parse_json(_repair(txt)) or {"verdict": "FAIL", "issues": [{"kind": "minor", "detail": "evaluator reply was not JSON: " + txt[:300]}]}
    issues = res.get("issues") or []
    # deterministic physics rules on the observations (the evaluator's verdict alone missed hollow standing socks)
    for ob in res.get("observations") or []:
        state = str(ob.get("state", "")).lower()
        worn_by = str(ob.get("worn_by", "")).lower()
        n_on = ob.get("items_on_that_body_part")
        if state == "filled" and worn_by in ("nobody", "no one", "none", ""):
            issues.append({"kind": "physics_violation", "t": ob.get("t"), "detail": f"{ob.get('item')} is worn by nobody but keeps the shape of a body part (hollow, upright or foot-shaped)",
                           "fix": "describe the item as empty and lying flat and collapsed on the surface, no feet inside, or show it worn by a visible person"})
        if isinstance(n_on, (int, float)) and n_on > 1:
            issues.append({"kind": "physics_violation", "t": ob.get("t"), "detail": f"{int(n_on)} items on one body part ({ob.get('item')}, worn by {ob.get('worn_by')})",
                           "fix": "one item per body part: say who wears which item and that each foot wears exactly one sock"})
    seen, uniq = set(), []
    for i in issues:  # one finding per kind and item, with every timestamp it was seen at
        k = (i.get("kind"), str(i.get("detail", ""))[:60])
        if k in seen:
            next(u for u in uniq if (u.get("kind"), str(u.get("detail", ""))[:60]) == k).setdefault("also_at", []).append(i.get("t"))
            continue
        seen.add(k)
        uniq.append(i)
    issues = uniq
    hard = [i for i in issues if i.get("kind") in HARD]
    verdict = "FAIL" if hard or str(res.get("verdict", "")).upper() != "PASS" else "PASS"
    report = {"clip": a.clip, "verdict": verdict, "observations": res.get("observations"), "product_match": res.get("product_match"), "physics": res.get("physics"),
              "hard_failures": hard, "issues": issues, "summary": res.get("summary"), "frames": [t for t, _ in frames], "sheet": sheet,
              "model": a.model, "usage": resp.get("usage")}
    jpath = os.path.join(a.out, f"check_{tag}.json")
    with open(jpath, "w") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    md = [f"# Clip check {tag}: {verdict}", "", report["summary"] or "", "",
          f"Product match {report['product_match']}/5, physics {report['physics']}/5", ""]
    md += [f"- **{i.get('kind')}** at {i.get('t')} s: {i.get('detail')} -> fix: {i.get('fix')}" for i in issues] or ["- no issues"]
    with open(os.path.join(a.out, f"check_{tag}.md"), "w") as fh:
        fh.write("\n".join(md) + "\n")
    gate.out({"ok": True, **{k: report[k] for k in ("clip", "verdict", "product_match", "physics", "hard_failures", "summary")}, "report": jpath},
             0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
