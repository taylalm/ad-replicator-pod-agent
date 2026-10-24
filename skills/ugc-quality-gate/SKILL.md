---
name: ugc-quality-gate
description: Independent quality check of a generated UGC ad (final MP4 or single clips) against the client rubric C1-C8 using a separate vision evaluator model through the ModelArk Chat API. Samples frames, compares them with the AI person references and the personalized product previews, scores 1-5 per criterion with evidence, flags hard failures (misspelled name, other brand, profanity, rude gesture, deformed product, wrong personalization, platform UI, watermark) and returns the retry routing. One small billable evaluator call per run.
---

# UGC quality gate

`scripts/gate.py` is the evaluator harness: deterministic checks (format, duration, aspect ratio), frame sampling into timestamped contact sheets, one call to a vision model with the rubric, and a report with routing. You do not score the video yourself; you run the gate and act on its report. Use it after video-assembly (final video) and optionally on single clips before assembly.

## Captions are always new wording

Put the sample's on-screen text (and any reference ad's) in context.json as `reference_captions`, the approved offers as `offer_lines`. A caption that copies a reference (60%+ similar or sharing 4+ words in a row) is the hard failure `copied_caption`, routed to 08_assembly.

## Per-clip check (run on every clip before it is accepted)

`scripts/clip_check.py` checks ONE clip right after it is generated, before step 7 is done: product truth, text, physics, anatomy, size and intent. One small evaluator call per clip.

```bash
python3 /mnt/skills/ugc-quality-gate/scripts/clip_check.py --clip 07_clips/clip_06.mp4 --prompt-file 06_prompts/clip_06.prompt.txt \
  --product "Harper's socks (website preview)|05_personalize/product_harper.png|left sole: quote; right sole: owl + HARPER" \
  --product "client mockup|/mnt/session/uploads/socks_mockup.png|bookshelf pattern covers leg and top of foot" \
  --person "Harper|04_people/person_harper.png" --expected-text HARPER --out 07_clips/checks
```

Pass every product truth image (the personalizer preview of each item, client mockups) and the people in the shot. It writes `checks/check_<clip>.json/.md` and a sheet, and exits 1 on FAIL. Hard failures: wrong_product, wrong_personalization, misspelled_text, foreign_text, physics_violation (two socks on one foot, an empty item standing up as if worn by an invisible body, floating objects), anatomy_error, wrong_count, deformed_product, intent_mismatch. On FAIL, apply each issue's `fix` to the prompt and regenerate (at most twice), then check again; never accept a failing clip silently, and list the check verdicts in the step 7 done message. Keep check images inside `07_clips/checks/` with names starting `check_`; do not save loose frame grabs in the outputs.

## Workflow

1. Dependencies (skips if present):

```bash
bash /mnt/skills/ugc-quality-gate/scripts/ensure-deps.sh
```

2. Write the context file the evaluator needs, `/mnt/session/outputs/09_quality/context.json`:

```json
{
  "product_name": "Personalized Reading Socks",
  "people": [{"name": "LILY", "image": "/mnt/session/outputs/04_people/person_lily.png", "role": "reader"}],
  "product_previews": [{"for": "LILY", "image": "/mnt/session/outputs/05_personalize/product_lily.png",
                        "expected": "dark teal socks, otter artwork, quote 'Do Not Disturb - I'm Reading', name LILY on the sole"}],
  "expected_text": ["LILY", "Do Not Disturb - I'm Reading"],
  "captions": ["POV: you tried talking to her mid chapter", "Personalize yours at macorner.co"],
  "cta_text": "Personalize yours at macorner.co",
  "disclaimer_text": "AI-generated video",
  "setting_brief": "cozy living room / bedroom, soft daylight, authentic phone-shot look",
  "hook_brief": "woman reading on the couch lifts her foot to reveal the sole message within 2 s",
  "do_not_copy": ["TikTok UI", "GiftSoul brand", "Veo watermark", "the sample's rabbit artwork and the name AMELIA"],
  "forbidden": ["profanity", "rude gestures", "other brands", "prices"],
  "product_layout": "left sole: quote text + books; right sole: owl artwork + name; leg: bookshelf pattern; teal cuff/heel/toe",
  "cast_count_expected": 1,
  "gallery_images": ["/mnt/session/outputs/02_product/gallery_01.jpg", "/mnt/session/outputs/02_product/gallery_03.jpg"],
  "audio_required": true,
  "accepted_risks": ["optional: product-art details the client explicitly accepted for this ad, e.g. 'the socks artwork shows the animal's raised paw as part of the product design'"]
}
```

3. Run the gate (one evaluator call, model `seed-2-0-lite-260428`, see "Evaluator model" below):

```bash
python3 /mnt/skills/ugc-quality-gate/scripts/gate.py \
  --video /mnt/session/outputs/08_assembly/final_v1.mp4 \
  --context /mnt/session/outputs/09_quality/context.json \
  --out /mnt/session/outputs/09_quality/round_1
```

   Add `--clip /mnt/session/outputs/07_clips/<id>.mp4` (repeatable) to score clips before assembly, `--max-frames 12` to change the sample density, `--dry-run` to build the contact sheets and print the request without calling the model.

4. Read `report_<tag>.json` / `report_<tag>.md` (the tag is the `--out` folder name, e.g. `round_1`; contact sheets are `quality_<tag>_sheet_NN.jpg`): `verdict` (PASS / FAIL), `scores` C1-C8 with reason and evidence (frame timestamps), `hard_failures`, `routing` (which step to redo for each failure), `visible_text` (what the evaluator read on the product), `disputed_failures` (name/text claims - misspelled, mirrored - that a second reading of full-size frames at the evidence timestamps did not support: most evidence frames must show the problem; these are not hard failures, but mention them in the delivery note), `second_opinion_calls`. Captions covering a face or the personalized design are hard failures (`caption_covers_face`, `caption_covers_personalization`). Look at the contact sheets yourself only to understand a failure, not to overrule the gate.

5. Act on the routing: C1 -> regenerate the AI person image(s); C2/C7 -> personalizer run or the clip prompt; C3-C6 -> the failing clip's Seedance prompt; C8 -> the edit plan (end card / captions). Maximum 3 retries per item; then deliver the best attempt flagged for human review. Keep every round's report (`round_1`, `round_2`, ...).

## Evaluator model

`seed-2-0-lite-260428` (ModelArk model list, 20 Oct 2026: "Multi-modal understanding, structured output (json_schema recommended)", 30K RPM). Chosen because it is a vision-capable, generally available model that is different from the agent's own model (independent judgement), supports structured JSON output and has a high rate limit; the pro variant costs more without changing the rubric. Override with `--model` if the client prefers another listed vision model.

## Guardrails

- The gate's hard failures are final: a video with a misspelled name, another brand, profanity, a rude gesture, a deformed product, wrong personalization, platform UI or a watermark is never delivered as passing.
- One evaluator call per run (plus one per `--clip`); do not loop the gate to fish for a pass. If the model call fails, report the error; do not score manually.
- `ARK_API_KEY` is read from the environment only; never print it.
- Frames and references are sent to the model as base64 data URLs; keep the total under 20 images per call.

## Checking several clips

Run the clip checks side by side instead of one after another (each takes 40-60 s; a tool call ends at 120 s):

```bash
python3 /mnt/skills/ugc-quality-gate/scripts/check_batch.py run --jobs /mnt/session/outputs/07_clips/check_jobs.json \
  --state /mnt/session/outputs/07_clips/check_state.json      # 4 at a time; call again until pending is 0, no sleep needed
```

`check_jobs.json` is a list of `{"name": "clip_03", "args": [<the clip_check.py arguments>]}`. Each result gives the verdict and the issues with their fixes. Name or text claims (mirrored, misspelled) are re-read on full-size frames and moved to `disputed` when most frames do not show them.
