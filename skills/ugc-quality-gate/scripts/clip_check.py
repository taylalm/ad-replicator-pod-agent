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
      [--person "Harper|04_people/person_harper.png"] [--expected-text HARPER] \
      [--payoff "the dog walks in and the woman bursts out laughing"] --out 07_clips/checks
The product reference images (and their expected descriptions) are the product truth: wording about the product in
the intent never overrides them. With --payoff, the report gives `payoff_window` [start, end] in clip seconds (where
the payoff is visible): the edit plan keeps that window, and a payoff that never happens is an intent_mismatch.
Writes <out>/check_<clip>.json and .md. Exit 0 PASS, 1 FAIL, 2 usage/setup error. One evaluator call per clip.
"""
import argparse
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate  # noqa: E402  (shared helpers: deps, probe, sample_frames, contact_sheet, data_url, call_model, parse_json)

HARD = ["wrong_product", "wrong_personalization", "misspelled_text", "foreign_text", "physics_violation", "anatomy_error",
        "wrong_count", "deformed_product", "intent_mismatch"]

CHECKLIST = """Check every frame. Report a problem only with a timestamp and what you see.
1. Product identity: each product matches its reference image exactly - artwork, which side/area carries which element (never mirrored or swapped), colours, all-over pattern, shape and proportions. When several personalized items appear, each item carries only its own person's portrait and name.
2. Text: every word printed on a product is spelled exactly as in its reference; garbled, invented, extra or foreign words (names that are not in the references) are failures. Ignore captions; there should be none.
3. Physical realism: wearables are worn the way people wear them - one sock or shoe per foot, a pair on a pair of feet, nothing worn twice or stacked on one limb; a wearable nobody wears obeys gravity (socks lie flat or slump, a garment drapes or lies folded) and never keeps a body shape as if an invisible person wore it, while bags, mugs, boxes and ornaments keep their own shape and may stand; nothing floats; fabric does not pass through bodies or furniture.
4. Anatomy: every visible person has the right number of feet, legs, hands and fingers; bodies are not merged; feet belong to a visible person.
4b. Physics over time (compare the frames, use the filmstrip): people walk the way they face and their legs step while they move (no sliding); nobody and nothing appears or vanishes in the middle of the frame; sizes do not jump between frames; everything is supported (feet on the ground, seated on a seat, held in a hand, worn, lying on a surface); a leash or rope runs continuously from the hand to the collar; held things touch the hand that holds them; nothing passes through a body, a car door or furniture; liquids, hair and fabric fall downward; a person keeps the same face, hair and clothes through the shot; a driver faces forward in the car and the car moves the way it points.
5. Size: the product's size relative to people and furniture matches the stated real size.
6. Intent: the shot shows what the intent says (people, count, action, framing, reactions); faces visible when the intent says so.
7. Product truth: the PRODUCT REFERENCE images and their expected descriptions are the truth about the product (shape, print size and position, plain areas). If the intent's wording about the product disagrees with the reference image, follow the reference image and do not fail the clip over that wording; mention the disagreement as "minor".
Be strict: any physics or anatomy error, any wrong or misspelled product text, any swapped portrait or name is a hard failure."""


def physics_from_tracks(tracks):
    """Deterministic physics rules on the evaluator's per-frame tracks (the evaluator measures, the code judges).
    Returns physics_violation / anatomy_error issues: walking backwards, vanishing or appearing mid-frame, size jumps,
    extra hands, floating, sliding without stepping."""
    out = []
    opposite = {"toward_camera": "away_from_camera", "away_from_camera": "toward_camera"}

    def add(kind, who, t, detail, fix):
        out.append({"kind": kind, "t": t, "detail": f"{who}: {detail}", "fix": fix})

    for tr in tracks:
        who, kind = str(tr.get("who", "?"))[:80], str(tr.get("kind", "")).lower()
        fr = []
        for f in tr.get("frames") or []:
            try:
                fr.append({**f, "t": float(f.get("t")), "height": float(f.get("height") or 0), "x": float(f.get("x") if f.get("x") is not None else 0.5)})
            except (TypeError, ValueError):
                continue
        fr.sort(key=lambda f: f["t"])
        vis = [f for f in fr if f.get("visible") is not False and f["height"] > 0]
        # 1. walking backwards: facing vs the size trend (also when the camera moves with the main subject)
        if kind in ("person", "animal", "vehicle") and len(vis) >= 2:
            facing = str(vis[len(vis) // 2].get("facing", "")).lower()
            ratio = vis[-1]["height"] / vis[0]["height"]
            travel = "away_from_camera" if ratio < 0.8 else ("toward_camera" if ratio > 1.25 else None)
            if travel and opposite.get(facing) == travel:
                add("physics_violation", who, f"{vis[0]['t']:.1f}-{vis[-1]['t']:.1f}", f"faces {facing} but travels {travel} (moving backwards)",
                    "state for every person which way they face AND walk; a reaction from someone who passed is 'walks away, then turns the head back'")
        for p, q in zip(fr, fr[1:]):
            pv, qv = p.get("visible") is not False, q.get("visible") is not False
            # 2. vanishing / appearing in the middle of the frame
            if pv and not qv and not p.get("at_edge") and not q.get("occluded") and p["height"] > 0.15 and 0.12 < p["x"] < 0.88:
                add("physics_violation", who, f"{p['t']:.1f}-{q['t']:.1f}", "vanishes in the middle of the frame",
                    "keep the number of people and objects fixed in the shot, or say from which edge someone leaves")
            if qv and not pv and not q.get("at_edge") and not p.get("occluded") and q["height"] > 0.15 and 0.12 < q["x"] < 0.88:
                add("physics_violation", who, f"{p['t']:.1f}-{q['t']:.1f}", "appears out of nowhere in the middle of the frame",
                    "name everyone who is in the shot from the first frame, or say from which edge they enter")
            # 3. size jumps (morphing) between neighbouring frames
            if pv and qv and p["height"] > 0.1 and q["height"] > 0.1 and q["t"] - p["t"] <= 1.0:
                r = q["height"] / p["height"]
                if r > 1.6 or r < 0.6:
                    add("physics_violation", who, f"{p['t']:.1f}-{q['t']:.1f}", f"size jumps x{r:.1f} between frames",
                        "slower, simpler motion; keep the camera distance steady")
        # 4. extra hands
        for f in vis:
            try:
                if kind == "person" and int(f.get("hands") or 0) > 2:
                    add("anatomy_error", who, f"{f['t']:.1f}", f"{int(f['hands'])} hands", "say 'exactly two hands'; fewer people's hands near the product")
                    break
            except (TypeError, ValueError):
                pass
        # 5. floating: no support in two or more frames
        air = [f for f in vis if str(f.get("support", "")).lower() in ("air", "none", "floating")]
        if kind in ("person", "animal", "object") and len(air) >= 2:
            add("physics_violation", who, f"{air[0]['t']:.1f}-{air[-1]['t']:.1f}", "floats with nothing supporting it",
                "say what holds or carries it (held in his right hand, lying on the bed, feet on the path)")
        # 6. sliding: travels across the frame while the legs never step
        if kind in ("person", "animal") and len(vis) >= 3 and all(f.get("legs_stepping") is False for f in vis) \
                and all(str(f.get("support", "ground")).lower() == "ground" for f in vis):
            moved = abs(vis[-1]["x"] - vis[0]["x"]) > 0.2 or not (0.8 <= vis[-1]["height"] / vis[0]["height"] <= 1.25)
            if moved:
                add("physics_violation", who, f"{vis[0]['t']:.1f}-{vis[-1]['t']:.1f}", "moves across the ground without stepping (sliding)",
                    "describe the walk: 'walks with natural steps'; or keep the person standing still")
    return out


def _walkers(base, key, model, strip):
    """One focused call on the filmstrip: every individual who walks or moves, facing and height per frame."""
    msg = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": gate.data_url(strip, 1600)}},
        {"type": "text", "text": "Frames of one video clip, left = earliest, times on top. List EVERY individual person or animal who walks or moves "
                                 "(main subject and background people; one entry per individual, never group people). For each: which way the body "
                                 "faces (toward_camera, away_from_camera, left, right) and the HEIGHT in each frame they are in (head to feet, or head "
                                 "to the frame's bottom edge, as a fraction of the frame height; measure each frame separately and carefully). "
                                 "Reply with ONLY JSON: {\"walkers\": [{\"who\": \"where and what they wear\", \"facing\": \"...\", "
                                 "\"heights\": [[t, fraction], ...]}]}"}]}]
    try:
        resp = gate.call_model(base, key, model, msg, max_tokens=3000)
        txt = resp["choices"][0]["message"]["content"]
        if isinstance(txt, list):
            txt = "".join(c.get("text", "") for c in txt)
        return (gate.parse_json(txt) or {}).get("walkers") or []
    except SystemExit:
        return None


def _filmstrip(frames, path, h=360):
    try:
        from PIL import Image, ImageDraw
        ims = [Image.open(p).convert("RGB") for _, p in frames]
        ims = [im.resize((max(1, int(im.width * h / im.height)), h)) for im in ims]
        strip = Image.new("RGB", (sum(im.width for im in ims) + 6 * (len(ims) - 1), h + 24), "white")
        x = 0
        for (t, _), im in zip(frames, ims):
            strip.paste(im, (x, 24))
            ImageDraw.Draw(strip).text((x + 4, 6), f"t={t:.1f}s", fill="black")
            x += im.width + 6
        strip.save(path, quality=85)
        return path
    except Exception:
        return None


def _repair(txt):
    """Make common evaluator JSON slips valid: free text in numeric fields (e.g. "items_on_that_body_part": 1 sock per foot)."""
    import re

    def num(m):
        val = m.group(2).strip()
        if re.fullmatch(r"-?\d+(\.\d+)?", val) or val.startswith('"') or val in ("null", "true", "false"):
            return m.group(0)
        n = re.search(r"\d+(\.\d+)?", val)
        return m.group(1) + (json.dumps(val) if m.group(1).strip().startswith('"t"') else (n.group(0) if n else "null"))
    txt = re.sub(r'("payoff_window"\s*:\s*)\[\s*([\d.]+)\s*(?:-|to|–)\s*([\d.]+)\s*\]', r'\1[\2, \3]', txt)
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
    ap.add_argument("--payoff", help="the moment the edit must keep (e.g. 'the barista bursts out laughing'); reported as payoff_window")
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
                + (f"EXACT TEXT ON THE PRODUCT: {', '.join(a.expected_text)}\n" if a.expected_text else "")
                + (f"PAYOFF (the moment the edit keeps): {a.payoff}\n" if a.payoff else "")}]
    for i, p in enumerate(products, 1):
        content += [{"type": "text", "text": f"PRODUCT REFERENCE {i} - {p['label']}: {p['expected']}"},
                    {"type": "image_url", "image_url": {"url": gate.data_url(p["image"], 768)}}]
    for p in people:
        content += [{"type": "text", "text": f"PERSON REFERENCE - {p['name']}"}, {"type": "image_url", "image_url": {"url": gate.data_url(p["image"], 512)}}]
    for t, path in frames:
        content += [{"type": "text", "text": f"CLIP FRAME t={t:.1f}s"}, {"type": "image_url", "image_url": {"url": gate.data_url(path, 768)}}]
    strip = _filmstrip(frames, os.path.join(a.out, f"check_{tag}_strip.jpg"))
    if strip:  # one picture in time order: movement (who gets bigger, who drifts back) is judged across it
        content += [{"type": "text", "text": "FILMSTRIP: the same frames side by side, left = earliest. Use it to judge which way each person moves."},
                    {"type": "image_url", "image_url": {"url": gate.data_url(strip, 1600)}}]
    content.append({"type": "text", "text": CHECKLIST + "\nFirst observe, then judge. Observe SINGLE items, never pairs: each sock, shoe or glove is its own item (a pair worn on two feet is two observations, one per foot). For EVERY single product item visible in each key frame fill one observation: "
                    "who wears it (a person's name, 'unknown person', or 'nobody'), its 3D state ('worn' on a body part; 'flat' = empty and collapsed, "
                    "lying on a surface with no volume; 'filled' = empty but keeping the volume or shape of a body part, e.g. a sock with a rounded heel, "
                    "toes pointing up, a hollow leg or an open cuff standing up - 'filled' applies to WEARABLES only; 'standing' = a non-wearable that keeps its own shape on a surface, e.g. a tote bag, mug, box or ornament, which is normal; 'held'; 'folded'), whether the item is a wearable (sock, shoe, glove, hat, garment), and for a worn item how many items are on that same single body part (one foot, one hand), counting itself: 1 is normal, 2 means two socks on one foot."
                    "\nThen TRACK every person, animal, vehicle and handled object (the product, a leash, a cup) through the frames, ONE entry per individual (never group two people). For each one and each frame "
                    "give: visible (true/false), at_edge (true when it is cut by the frame edge or just entering/leaving), occluded (hidden behind something), "
                    "x (horizontal centre, 0-1), height (head to feet or top to bottom as a fraction of the frame height; measure carefully), facing "
                    "(toward_camera, away_from_camera, left, right), support (ground, seat, held_by:<who>, worn_by:<who>, on:<surface>, air), hands (people: "
                    "visible hands that belong to this person) and legs_stepping (people/animals: true when the legs are in a walking step)."
                    "\nReply with ONLY JSON: {\"observations\": [{\"t\": seconds, \"item\": \"...\", \"worn_by\": \"...\", \"wearable\": true, \"state\": \"worn|flat|filled|standing|held|folded\", "
                    "\"items_on_that_body_part\": n}], \"tracks\": [{\"who\": \"what it is, where it is and what it wears\", \"kind\": \"person|animal|vehicle|object\", "
                    "\"frames\": [{\"t\": seconds, \"visible\": true, \"at_edge\": false, \"occluded\": false, \"x\": 0.5, \"height\": 0.8, \"facing\": \"toward_camera\", "
                    "\"support\": \"ground\", \"hands\": 2, \"legs_stepping\": true}]}], \"verdict\": \"PASS\"|\"FAIL\", \"product_match\": 1-5, "
                    "\"physics\": 1-5, " + ("\"payoff_window\": [first second the payoff is visible, last second] or null if it never happens, " if a.payoff else "") + "\"issues\": [{\"kind\": one of " + json.dumps(HARD + ["minor"]) + ", \"t\": seconds, \"detail\": \"...\", "
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
    res, raw = None, ""
    for _ in range(2):  # an unreadable reply is asked once more before it counts as a failure
        resp = gate.call_model(base, key, a.model, messages, max_tokens=7000)
        txt = resp["choices"][0]["message"]["content"]
        if isinstance(txt, list):
            txt = "".join(c.get("text", "") for c in txt)
        raw = txt
        res = gate.parse_json(txt) or gate.parse_json(_repair(txt))
        if res:
            break
    unreadable = not res
    if unreadable:
        res = {"verdict": "FAIL", "issues": [{"kind": "minor", "detail": "evaluator reply was not JSON: " + raw[:300]}]}
    issues = res.get("issues") or []
    # deterministic physics rules on the observations (the evaluator's verdict alone missed hollow standing socks)
    for ob in res.get("observations") or []:
        state = str(ob.get("state", "")).lower()
        worn_by = str(ob.get("worn_by", "")).lower()
        n_on = ob.get("items_on_that_body_part")
        item = str(ob.get("item", "")).lower()
        # only wearables can look worn by an invisible person; bags, mugs, boxes and ornaments keep their own shape
        not_wearable = ob.get("wearable") is False or re.search(r"\b(bag|tote|mug|cup|tumbler|bottle|box|ornament|frame|pillow|cushion|blanket|notebook|keychain|book)s?\b", item)
        if state == "filled" and worn_by in ("nobody", "no one", "none", "") and not not_wearable:
            issues.append({"kind": "physics_violation", "t": ob.get("t"), "detail": f"{ob.get('item')} is worn by nobody but keeps the shape of a body part (hollow, upright or foot-shaped)",
                           "fix": "describe the item as empty and lying flat and collapsed on the surface, no feet inside, or show it worn by a visible person"})
        if isinstance(n_on, (int, float)) and n_on > 1:
            issues.append({"kind": "physics_violation", "t": ob.get("t"), "detail": f"{int(n_on)} items on one body part ({ob.get('item')}, worn by {ob.get('worn_by')})",
                           "fix": "one item per body part: say who wears which item and that each foot wears exactly one sock"})
    issues += physics_from_tracks(res.get("tracks") or [])
    # walking gets its own focused question: in the all-entity tracking the evaluator grouped two passers-by and
    # smoothed their sizes, while a walkers-only question measured the woman walking backwards correctly
    people = [t for t in res.get("tracks") or [] if str(t.get("kind", "")).lower() in ("person", "animal")]
    walkers = None
    if strip and (len(people) >= 2 or re.search(r"\bwalk|stroll|pass|street|park|path|run", intent, re.I)):
        walkers = _walkers(base, key, a.model, strip)
        issues += physics_from_tracks([{"who": w.get("who"), "kind": "person",
                                        "frames": [{"t": h[0], "height": h[1], "facing": w.get("facing"), "x": 0.5} for h in (w.get("heights") or [])
                                                   if isinstance(h, (list, tuple)) and len(h) == 2]} for w in walkers or []])
    seen, uniq = set(), []
    for i in issues:  # one finding per kind and item, with every timestamp it was seen at
        k = (i.get("kind"), str(i.get("detail", ""))[:60])
        if k in seen:
            next(u for u in uniq if (u.get("kind"), str(u.get("detail", ""))[:60]) == k).setdefault("also_at", []).append(i.get("t"))
            continue
        seen.add(k)
        uniq.append(i)
    issues = uniq
    # second opinion on name/text claims (stylized lettering and folded fabric are often misread as mirrored or misspelled):
    # the claim stays only if most of the re-read frames show it, as in the final gate
    disputed = []
    claim_re = re.compile(r"mirror|revers|backward|flipp|misspel|spell|letter", re.I)
    for i in list(issues):
        if i.get("kind") not in ("misspelled_text", "wrong_personalization") or not claim_re.search(str(i.get("detail", ""))):
            continue
        ts = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(i.get("t", "")))] + [float(x) for x in (i.get("also_at") or []) if isinstance(x, (int, float))]
        if len(ts) >= 2 and len(re.findall(r"\d+(?:\.\d+)?", str(i.get("t", "")))) == 2:  # a range "a-b": three frames across it
            lo, hi = ts[0], ts[1]
            ts = [lo + (hi - lo) * f for f in (0.2, 0.5, 0.8)] + ts[2:]
        if not ts:
            ts = [t for t, _ in frames]
        claim = {"kind": "wrong_personalization", "detail": str(i.get("detail", "")), "evidence": ", ".join(f"t={t:.2f}s" for t in ts[:3])}
        ctx = {"product_previews": [{"image": p["image"]} for p in products], "expected_text": a.expected_text}
        kept, gone, _ = gate.verify_text_claims([claim], ctx, ff, a.clip, base, key, a.model, tmp)
        if gone:
            issues.remove(i)
            disputed.append({**i, "second_opinion": gone[0].get("second_opinion")})
    payoff_window = res.get("payoff_window") if a.payoff else None
    if isinstance(payoff_window, str):  # "0.5-2.5" or "0.5 to 2.5"
        nums = re.findall(r"\d+(?:\.\d+)?", payoff_window)
        payoff_window = [float(nums[0]), float(nums[-1])] if nums else None
    if a.payoff and not unreadable and not (isinstance(payoff_window, list) and len(payoff_window) == 2):
        issues.append({"kind": "intent_mismatch", "t": None, "detail": f"the payoff never happens: {a.payoff}",
                       "fix": "put the payoff early in the clip timeline (e.g. 1-3s) and describe it as a visible action"})
        payoff_window = None
    hard = [i for i in issues if i.get("kind") in HARD]
    only_disputed = disputed and not issues
    verdict = "FAIL" if hard or (str(res.get("verdict", "")).upper() != "PASS" and not only_disputed) else "PASS"
    report = {"clip": a.clip, "verdict": verdict, "observations": res.get("observations"), "product_match": res.get("product_match"), "physics": res.get("physics"), "tracks": res.get("tracks"), "walkers": walkers,
              "payoff_window": payoff_window, "hard_failures": hard, "issues": issues, "disputed": disputed, "summary": res.get("summary"), "frames": [t for t, _ in frames], "sheet": sheet,
              "model": a.model, "usage": resp.get("usage"), **({"raw_reply": raw[:4000]} if unreadable else {})}
    jpath = os.path.join(a.out, f"check_{tag}.json")
    with open(jpath, "w") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    md = [f"# Clip check {tag}: {verdict}", "", report["summary"] or "", "",
          f"Product match {report['product_match']}/5, physics {report['physics']}/5", ""]
    md += [f"- **{i.get('kind')}** at {i.get('t')} s: {i.get('detail')} -> fix: {i.get('fix')}" for i in issues] or ["- no issues"]
    with open(os.path.join(a.out, f"check_{tag}.md"), "w") as fh:
        fh.write("\n".join(md) + "\n")
    gate.out({"ok": True, **{k: report[k] for k in ("clip", "verdict", "product_match", "physics", "payoff_window", "hard_failures", "disputed", "summary")}, "report": jpath},
             0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
