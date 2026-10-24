#!/usr/bin/env python3
"""Write the Seedream prompts for a first-frame still with personalized products, from a short scene spec.

The model decides WHAT the shot shows (people, products, how they are used, framing); this script writes HOW to ask
Seedream for it, with the rules that made the stills correct (tested on the blanket case, 23 Oct 2026):
  1. plain scene first: every product at its REAL size next to the people, used naturally (wrapped, worn, held...),
     in clearly different solid colours, no print; clothes never the product's colour; the setting's key element large;
  2. then one print edit per product on that plain still: the ENTIRE visible surface printed like the personalizer
     preview, names spelled exactly, no plain areas, main art large on the visible face; edges and linings stay plain;
  3. merge the edits (edit_merge.py) and look at every product before animating.
Output: the prompts plus edit_batch.py job files for step 1 and step 2.

  python3 still_prompts.py --spec still_spec.json --out /mnt/session/outputs/07_clips/stills/<shot>

still_spec.json:
{
  "shot": "group_open",
  "scene": "a warm Christmas living room at night",
  "setting_focus": "a tall, brightly lit Christmas tree right behind the couch, filling the upper part of the frame",
  "framing": "straight-on medium-close shot from chest height, the people filling the frame width",
  "reference_image": "/mnt/session/outputs/04_people/group_ref.png",      (optional: people to keep; else the people images)
  "people": [{"name": "Ava", "image": ".../person_ava.png", "who": "the girl on the far left", "clothes": "cream knit sweater"}],
            (always give each person's image: it is sent with the prompt so nobody is swapped)
  "products": [{"owner": "Ava", "kind": "blanket", "colour": "pink", "size": "50 x 60 inch (127 x 152 cm)",
                "use": "wrapped", "preview": ".../product_ava.png", "name_text": "Ava",
                "main_art": "the ballerina cartoon", "lining": "cream sherpa"}],
  "action": "the children giggle and lean into each other"
}
`use` is one of: wrapped, draped_over_lap, held_up, worn, held_in_hands, on_surface, folded_stack (or free text).
"""
import argparse
import json
import os
import sys

USE = {
    "wrapped": "wrapped around their shoulders like a cape, the edge pulled snug under the chin, covering the whole body and "
               "spilling in big soft folds over the seat and onto the floor",
    "draped_over_lap": "spread over their lap and legs, reaching past the feet and draping over the seat edge to the floor",
    "held_up": "held up by them with their OWN two hands at the top corners, hanging straight down in front of their body "
               "to the floor, flat and facing the camera so the whole front is visible",
    "worn": "worn by them the way it is meant to be worn, fitting their body naturally",
    "held_in_hands": "held in their own hands at chest height, the personalized side facing the camera",
    "on_surface": "lying spread open on the surface, covering it from edge to edge and draping over the front edge",
    "folded_stack": "neatly folded in a stack, each item at its real folded thickness",
}
SIZE_HINT = {
    "blanket": "much wider than the person's shoulders and longer than their whole body",
    "throw": "wider than the person's shoulders and longer than their whole body",
}


def plain_prompt(spec):
    lines = [f"Photorealistic vertical phone photo, 9:16, {spec.get('framing', 'medium shot at eye level')}. "
             f"Setting: {spec.get('scene', 'a cosy home')}"
             + (f", with {spec['setting_focus']}" if spec.get("setting_focus") else "") + "."]
    ppl = spec.get("people", [])
    if ppl:
        lines.append("People (same faces and hair as in the reference images): " + "; ".join(
            f"{p['who']} ({p['name']}), wearing {p.get('clothes', 'neutral cream or white clothes')}" for p in ppl) + ".")
    for pr in spec.get("products", []):
        who = next((p["who"] for p in ppl if p["name"] == pr.get("owner")), pr.get("owner", "the person"))
        use = USE.get(pr.get("use", ""), pr.get("use", "")).format(who=who)
        size = pr.get("size", "")
        hint = SIZE_HINT.get(pr.get("kind", ""), "")
        lines.append(f"{who.capitalize()} has a {pr.get('colour')} {pr.get('kind')} at its REAL size{f' ({size})' if size else ''}"
                     + (f", {hint}" if hint else "") + f": {use}."
                     + (f" The {pr['lining']} lining shows only at the edges." if pr.get("lining") else ""))
    colours = [pr.get("colour") for pr in spec.get("products", [])]
    lines.append(f"Every {spec['products'][0].get('kind', 'product')} is PLAIN solid colour ({', '.join(colours)}) with no print and no text; "
                 "the clothes are never the same colour as a product. "
                 + (f"Action: {spec['action']}. " if spec.get("action") else "")
                 + "Faces fully visible. Natural light, authentic UGC phone photo.")
    return " ".join(lines)


def print_prompt(spec, pr):
    ppl = spec.get("people", [])
    who = next((p["who"] for p in ppl if p["name"] == pr.get("owner")), pr.get("owner", "the person"))
    name = pr.get("name_text", "")
    spelled = "-".join(name) if name else ""
    others = len(spec.get("products", [])) - 1
    return (f"Edit image 1. Change ONLY the outer printed face of the {pr.get('colour')} {pr.get('kind')} of {who}. "
            "Its ENTIRE visible outer surface - everywhere it shows, in every fold, over the parts that hang, drape or pool - "
            "becomes exactly the printed design of image 2"
            + (f": the name '{name}' repeated all over in the same mixed lettering styles and density as image 2, every word spelled "
               f"{spelled} exactly, no other words or letters" if name else "")
            + ", with no plain areas anywhere"
            + (f", and {pr['main_art']} printed large on the most visible face, clearly shown" if pr.get("main_art") else "")
            + ". It is a flat print that follows the folds."
            + (f" The {pr['lining']} lining stays plain." if pr.get("lining") else "")
            + f" Keep its {pr.get('colour')} colour, its real size and shape and the way it is used, the people"
            + (f", the other products (still plain)" if others else "") + " and the whole room exactly as in image 1.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="2K")
    a = ap.parse_args()
    spec = json.load(open(a.spec))
    if not spec.get("products"):
        sys.exit("spec needs at least one product")
    os.makedirs(a.out, exist_ok=True)
    shot = spec.get("shot", "still")
    # every person's own photo always goes in, named, so a scene reference can never swap who is who (the cartoon on a
    # photo product is drawn from that photo: the person in the still must be the same child)
    people_imgs = [(p["name"], p["who"], p["image"]) for p in spec.get("people", []) if p.get("image")]
    refs = ([spec["reference_image"]] if spec.get("reference_image") else []) + [img for _, _, img in people_imgs]
    plain = plain_prompt(spec)
    if people_imgs:
        first = 2 if spec.get("reference_image") else 1
        plain += (" " + ("Image 1 sets the scene and framing only. " if spec.get("reference_image") else "")
                  + "Each person looks exactly like their own photo - same face, skin tone, hair colour and hairstyle: "
                  + "; ".join(f"image {first + k} is {who} ({name})" for k, (name, who, _) in enumerate(people_imgs)) + ".")
    plain_path = os.path.join(a.out, f"{shot}_plain.png")
    job1 = [{"name": f"{shot}_plain", "args": ["--prompt", plain] + sum((["--image", r] for r in refs), [])
             + ["--size", a.size, "--output-format", "png", "--download", a.out, "--name", f"{shot}_plain"]}]
    job2, merge_items = [], []
    for pr in spec["products"]:
        n = f"{shot}_print_{pr.get('owner', 'item').lower()}"
        job2.append({"name": n, "args": ["--prompt", print_prompt(spec, pr), "--image", plain_path, "--image", pr["preview"],
                                         "--size", a.size, "--output-format", "png", "--download", a.out, "--name", n]})
        who = next((p["who"] for p in spec.get("people", []) if p["name"] == pr.get("owner")), pr.get("owner"))
        merge_items.append(f"{pr.get('colour')} {pr.get('kind')} of {who}|{os.path.join(a.out, n + '.png')}|{pr['preview']}")
    for fname, data in (("jobs_plain.json", job1), ("jobs_print.json", job2)):
        with open(os.path.join(a.out, fname), "w") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
    merge_cmd = ["python3", "/mnt/skills/ugc-seedance-prompt-craft/scripts/edit_merge.py", "--base", plain_path,
                 "--out", os.path.join(a.out, f"{shot}_merged.png")] + sum((["--item", m] for m in merge_items), [])
    print(json.dumps({"ok": True, "plain_prompt": plain, "print_prompts": {j["name"]: j["args"][1] for j in job2},
                      "steps": [f"edit_batch.py run --jobs {a.out}/jobs_plain.json --state {a.out}/state_plain.json   -> look at the plain still: "
                                "real size next to the people? natural use? clothes not the product colour? setting element large? Fix the spec and rerun if not.",
                                f"edit_batch.py run --jobs {a.out}/jobs_print.json --state {a.out}/state_print.json" if len(job2) > 1 else
                                f"edit_batch.py run --jobs {a.out}/jobs_print.json --state {a.out}/state_print.json   (one product: its print edit is the still)",
                                " ".join(json.dumps(x) if " " in x else x for x in merge_cmd) if len(job2) > 1 else "",
                                "zoom into every product: whole surface printed, names spelled exactly; redo one print edit if not. "
                                "If Seedance refuses the still as a possible real person, make a zoom-out edit (people about half the frame) and animate that."]},
                     indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
