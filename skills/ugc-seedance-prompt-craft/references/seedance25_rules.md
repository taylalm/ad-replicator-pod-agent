# Seedance 2.5 rules used by the validator

Sources (read 20 Oct 2026): `docs.byteplus.com/en/docs/modelark/seedance-2-5` (tutorial, "Read before use") and `docs.byteplus.com/en/docs/modelark/seedance-2-5-prompt-guide`. Model ID `dreamina-seedance-2-5-260628`.

## Task types and constraints (tutorial, "Read before use")

| Task | Trigger | Constraints |
|---|---|---|
| Text-to-video | prompt only | none |
| First / first-last frame | `first_frame` (+ `last_frame`) image roles | `ratio` must be `adaptive`; output follows the first frame's ratio |
| Reference-to-video | at least one `reference_image` / `reference_video` / `reference_audio` | none on ratio or duration |
| Video editing | a `reference_video` + editing intent (edit the video, add, remove/delete, modify/replace/change) | `ratio` = `adaptive`, `duration` = `-1`, reference video 4-30 s, output keeps the video's ratio and duration; `output_format` mov recommended |
| Video extension | a `reference_video` + extension intent (extend forward/backward, continue) | `ratio` = `adaptive`; duration user-defined or -1 |

`omni_reference_task_type` (`auto`, `reference`, `edit`, `extend`) moves validation earlier; a mismatch between the declared type and what the model infers from the prompt fails asynchronously (`InvalidParameter.TaskTypeMismatch`).

## Limits (tutorial)

- Up to 50 reference assets per request: 30 images (up to 4K), 10 videos (combined up to 30 s), 10 audio clips (combined up to 30 s).
- Duration 4-30 s or -1; resolutions 480p / 720p / 1080p; ratios 21:9, 16:9, 4:3, 1:1, 3:4, 9:16, adaptive; 24 fps; mp4 or mov.
- Stability: 1-8 subject images work best; 5-10 s subject videos; editing works best on videos under 20 s.

## Prompt-guide rules that matter for ads

- **Bind every asset by number and role in the prompt**, in upload order: "@Image1 is the woman ...", "@Image2 is the product ...". Do not rely on text written inside the image to identify a character.
- **One-sentence summary first** (subject + location + event + style + camera), then a **shot sequence with timestamps** ("0-3s ... 3-8s ...") covering the whole clip without gaps; 1-second granularity; do not use timestamps for high-frequency actions.
- **Positive descriptions**; negatives are reliable only for subtitles and audio ("No subtitles", "No BGM", "No audio").
- **Subtitles**: say "No subtitles"; avoid repeating dialogue words or attaching tone/expression notes to specific words (they trigger subtitles); reference videos with subtitles make the output inherit them.
- **Text in the video is often misspelled**: provide text that must be exact as a reference image (our personalized product preview) and say it must match the image exactly.
- **Emotion words**: neutral wording ("amused", "pleased"); intense words ("fanatical", "extremely shocked") can make eyes glow.
- **High-resolution AI references** can produce fingerprint-like textures on grass/foliage; 1K-2K references are enough.
- **Camera language** can be used directly: wide / medium / close-up, push in, pull out, pan, handheld, low angle, top-down, first-person; transitions need both the time and the method ("at the 5-second mark, hard cut to ...").
- **Actions**: general descriptions, a few memorable specifics, no repeats; expressions in plain sentences.
- Editing prompts must say what changes from A to B and may use timestamps ("replace the woman in @Video1 with the woman in @Image1; keep everything else unchanged").
- Audio: this workflow sends `generate_audio: false` (copyright rejections were seen with generated audio); music is added in post-production.
