---
name: ugc-video-analyzer
description: Break down a sample UGC/TikTok ad video into a structured brief (hook, scenes, on-screen text, product and personalization moments, people, CTA, style, what not to copy) for replicating it with new people and the client's own product. Takes a direct HTTPS link to the video file or a local/uploaded file. Use first in the video replication workflow. No billable API calls.
---

# UGC video analyzer

Two parts: `scripts/analyze.py` does the deterministic extraction (download, probe, scene cuts, keyframes, timestamped contact sheets, audio levels). You then look at the images and write `analysis.json`.

## Workflow

1. Install dependencies (skips if present):

```bash
bash /mnt/skills/ugc-video-analyzer/scripts/ensure-deps.sh
```

2. Extract. The source must be a **direct HTTPS link to the video file** (for example a TOS URL) or a local file such as `/mnt/session/uploads/<file>.mp4`:

```bash
python3 /mnt/skills/ugc-video-analyzer/scripts/analyze.py \
  --source "https://<bucket>.tos-ap-southeast-1.bytepluses.com/<file>.mp4" \
  --out /mnt/session/outputs/analysis
```

   - TikTok, Instagram, YouTube and Facebook page links are rejected: the platforms block downloads from the sandbox. Ask the user for a direct MP4 link or an upload instead. Do not try other download tools.
   - Takes about 30 s for a 20 s 1080p video. Output: `extraction.json`, `keyframes/scene_XX_*.jpg`, `contact_sheet_XX.jpg` (frames every 0.5 s with timestamps), `watermark_check.jpg`.
   - The scene detector misses fades and dissolves. If a scene's frames clearly contain several shots, split it in `analysis.json` and say so in `replication_notes`.
   - If only one scene is detected but the video clearly cuts, rerun with `--scene-threshold 0.2`.

3. Count the distinct on-camera people (cast_count) and note the caption typography (lines, size, position, outline, emoji, offer style) while you look. Look at **every** contact sheet in order, then the keyframes of each scene, then `watermark_check.jpg` (zoomed corners at each scene and the last frame; columns are top-left, top-right, bottom-left, bottom-right). Read on-screen text exactly as shown. For each scene, compare consecutive 0.5 s frames before you describe it: does the background slide (moving car, walking camera)? Is the camera inside or outside (a car, a room)? Where does the product start and end (worn, half on, rolled, held, stretched)? When exactly does the payoff happen? Who reacts on camera? Read each scene's measured `motion` in extraction.json first: `background_label` "moving" (background change 18+) means the camera or vehicle moves even when the contact sheet looks still (the balaclava hook was a driving car at 26.9); "static" means a locked-off shot. Write that into the scene's `motion` and never describe a "moving" scene as parked or still. Which way does each body face relative to the set (a driver faces the windshield even when the head turns to the camera)? In what order is the product put on (from the back of the head forward; nothing at the neck before it is pulled down)? These go into each scene's `camera_position`, `pose`, `motion`, `product_state`, `beats`, `reactions` and `staging_frame` / `real_face_visible` (see the schema): the clips and the edit are built from them, and a misread here makes every later step wrong. Faint corner marks are easy to miss on the contact sheets: report any watermark or logo found in `watermark_check.jpg`, with its corner and time. If `audio` is not null, note that the file has sound; you cannot hear it, so record `"audio": "present, content not checked"` unless the user tells you what it is.

4. Write `/mnt/session/outputs/analysis/analysis.json` following `references/analysis_schema.md`. If the sample has on-screen text, run `python3 /mnt/skills/ugc-video-analyzer/scripts/analyze.py --caption-motion /mnt/session/outputs/analysis/analysis.json`, look at every `caption_motion_*` strip (frames 1/15 s apart, left to right: does the text cut in, fade, pop, slide, type on letter by letter, appear word by word, blink?) and write `caption_style.animation`. Use `references/example_socket_analysis.json` as the model for level of detail.

5. Validate, fix until `"ok": true`:

```bash
python3 /mnt/skills/ugc-video-analyzer/scripts/analyze.py --check /mnt/session/outputs/analysis/analysis.json
```

6. Report to the user: one-paragraph summary, the scene table (time, shot, purpose), the hook, the cast count, the shot arc, the `keep` list (setting, decor, cast, caption style, pacing) and the `do_not_copy` list, and any warnings from extraction. The replica copies everything in `keep` and changes only product, people, names, brand and wording. Keep `source_url` from `extraction.json`: Seedance reference/edit mode needs that public HTTPS URL.

## Guardrails

- Describe only what is visible. Mark anything uncertain as uncertain; never invent captions, prices or claims.
- Screen recordings of TikTok include the app interface (account name, caption bar, buttons). That is not part of the ad: list it under `do_not_copy`, never in `on_screen_text`.
- Other sellers' brands, logos and account names, watermarks (including AI-model marks such as "Veo"), and the sample's own artwork and example names, always go in `do_not_copy`. A model watermark also means the sample itself is AI-generated: note it in `replication_notes`.
- Describe people by appearance only. Do not identify real people.
- The extraction makes no paid API calls. Do not call a model API from this skill.
