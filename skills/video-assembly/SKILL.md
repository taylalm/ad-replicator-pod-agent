---
name: video-assembly
description: Assemble the final vertical (9:16) ad from generated clips and stills in the Managed Agents sandbox - trim, scale, concatenate, burn in captions in the client's caption style (1-2 short lines in the top band), overlay a photo inset with an arrow, cut in a montage of product-preview stills, mix music / sound effects / the clips' own audio, and append the client's fixed outro. Use after all clips are generated and the edit plan is agreed. No billable API calls.
---

# Video assembly

Use `scripts/assemble.py` with a JSON edit plan. Do not write ad-hoc ffmpeg commands.

## Workflow

1. Install dependencies once per session (skips if present, about 10 s the first time):

```bash
bash /mnt/skills/video-assembly/scripts/ensure-deps.sh
```

2. Write the edit plan to `/mnt/session/outputs/08_assembly/edit_plan.json` (schema below). Base it on the sample analysis: same scene order, pacing and caption roles, captions **rewritten** in new words, 1-2 short lines each. Use only facts from the product page and the brief for offers and product names; never invent them.
3. Validate without rendering and show the steps to the user:

```bash
python3 /mnt/skills/video-assembly/scripts/assemble.py --plan /mnt/session/outputs/08_assembly/edit_plan.json --dry-run
```

4. Render:

```bash
python3 /mnt/skills/video-assembly/scripts/assemble.py --plan /mnt/session/outputs/08_assembly/edit_plan.json
```

5. Report the output path, duration, and the preview frame paths from the JSON result. Look at the preview frames before calling the video done: captions readable and above the faces, insets not covering the product, outro present.

## Edit plan schema

```json
{
  "output": "/mnt/session/outputs/08_assembly/final_v1.mp4",
  "size": [1080, 1920],
  "fps": 30,
  "clips": [
    {"path": "/mnt/session/outputs/07_clips/clip_01.mp4", "start": 0, "end": 4.5},
    {"image": "/mnt/session/outputs/05_personalize/variant_kim_dialog.png", "duration": 1.2, "zoom": 1.06},
    {"image": "/mnt/session/outputs/05_personalize/variant_loran_dialog.png", "duration": 1.2, "zoom": 1.06},
    {"path": "/mnt/session/outputs/07_clips/clip_02.mp4"}
  ],
  "captions": [
    {"text": "POV: you asked her a question mid chapter", "start": 0, "end": 4.5, "style": "client"},
    {"text": "Each one is customized with their photo and name", "start": 4.5, "end": 9, "style": "client"},
    {"text": "It comes in different sizes & custom options", "start": 9, "end": 13, "style": "pill"},
    {"text": "Buy 4 or more and save up to 20%", "start": 13, "end": 17, "style": "offer"},
    {"text": "Limited time offer. Shop now", "start": 17, "end": 20, "style": "cta"}
  ],
  "insets": [
    {"image": "/mnt/session/outputs/04_people/person_harper.png", "start": 4.5, "end": 9, "position": "top-right", "width": 0.34, "top": 0.24, "arrow_to": [0.45, 0.55]}
  ],
  "outro": {"path": "/mnt/skills/video-assembly/assets/outro/macorner_outro.mp4"},
  "music": {"path": "/mnt/session/uploads/track.mp3", "volume": 0.7, "fade_out": 1.0},
  "sfx": [{"path": "/mnt/session/uploads/kids_giggle.wav", "start": 0.5, "volume": 0.9}],
  "keep_clip_audio": true,
  "preview_frames": 6
}
```

- `clips` (required): played in order. Video entries (`path`, optional `start`/`end` trim) are scaled and centre-cropped to fill `size`. Still entries (`image`, `duration`, optional `zoom` for a slow push-in, `fit`: `contain` (default; the whole image inside the frame over a blurred copy of itself) or `cover`) cut product-preview screenshots or product-page images into the edit, for example the "Looks Good to Go?" dialog of three other personalized variants.
- Video clips take `start`/`end` (trim, seconds in the clip) and optional `zoom` (e.g. 1.35, crops the centre for a tighter close-up; `zoom_anchor` [x, y] 0-1 moves the crop, e.g. [0.5, 0.3] to keep faces near the top).
- `reference_captions`: the sample's on-screen text (and any reference ad's). Every caption must be NEW wording: one that is 60%+ similar to a reference or shares 4+ words in a row fails validation (dry-run too). Only a client-approved offer line keeps its wording, marked `"approved_wording": true`.
- `captions`: times on the final timeline. `style` presets copied from the client's ads: `client` (small white bold, thin dark outline, top band; default), `pill` (white on a dark pill, feature lines), `offer` (yellow bold with dark outline), `cta` (large white with red outline, final shop-now line), plus plain `outline` / `box`; and the styles of the client's finished ads: `offer_italic` (heavy italic yellow with dark outline, e.g. "And when you get 4 or more, you'll save up to 44%!"), `shop_now` (big heavy italic white with red outline, two lines "Limited Time Offer" / "Shop Now"), `promo_pink` (white bold in a pink rounded box, offer lines), `pov_box` (white bold in a black rounded box, POV hooks). Caption sizes are fractions of the frame width with a floor of 4.4% of the width so 480p renders stay readable (about 21 px at 480p, 48 px at 1080p); override with `size` in pixels. Captions are limited to 2 lines and about 70 characters; a caption that wraps to a third line fails. Positions: `top` (default, above faces), `upper`, `middle`, `lower`, `bottom`, or a number 0.04-0.80; anything below 0.30 of the frame warns unless `allow_over_subject` is set. Emoji render with Noto Color Emoji (installed by ensure-deps.sh); copy the sample's emoji use (one per caption at most, at the end of the line).
- `insets`: a photo (the AI person's original picture) in a white-bordered box, top-right by default, with a white curved arrow to `arrow_to` (frame fractions; aim at the printed portrait). With face avoidance on, the tip is placed just above the head of the portrait nearest `arrow_to`, pointing down at it, and the curve is routed so it never crosses a face.
- Face avoidance (default on, `"avoid_faces": false` to disable): for every caption and inset the script asks the vision model where faces are (real faces and printed portraits) in the frame at the middle of the interval and moves the caption to the nearest free band (top, upper, lower, bottom), moves the inset to a free side/height, lands the arrow tip just above the target portrait's head and routes the curve around every face. The JSON result lists what moved under `face_avoidance`; check the preview frames anyway. Use it for the "photo becomes the cartoon" shot.
- `outro`: appended after the last clip, scaled to `size`. `true`, `{}` or no `path` uses the bundled client outro (`assets/outro/macorner_outro.mp4`, 4 s, carries the AI line). When an outro is present, do not add an `end_card` or a `disclaimer`.
- `end_card`: only when the client has no fixed outro; `lines` drawn under an optional `image`.
- Audio: `keep_clip_audio` keeps the clips' own sound (for example natural sound generated with the clips); `music` is looped and faded out before the outro; `sfx` entries are placed at `start` seconds. All present sources are mixed. Without any source the track is silent, which the client treats as a failure, so always provide at least music from the uploads.
- `disclaimer`: a small pill shown over the scenes (not over the outro). Not needed when the outro carries the AI line.
- `preview_frames`: number of JPG stills saved next to the output for review and the quality gate.

## Guardrails

- Only use media files that exist in the sandbox: generated clips, uploads, product-page images downloaded by the personalizer probe, previews captured by the personalizer, and the bundled outro.
- Music and sound effects must come from the user's uploads or a licence the user confirms. Never download audio from the web.
- Keep captions inside the top band and away from faces and from the bottom 15% where TikTok places its own UI.
- Offers and discounts only when the brief provides the approved wording.
- If rendering fails, report the error from the JSON output; do not retry with different settings without telling the user.
- Text is rendered with the bundled Poppins font (SIL Open Font Licence, `assets/fonts/OFL.txt`).
