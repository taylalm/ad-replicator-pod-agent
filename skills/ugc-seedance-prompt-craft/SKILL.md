---
name: ugc-seedance-prompt-craft
description: Turn a UGC ad analysis plus the AI people and personalized product previews into validated Seedance 2.5 prompts (one per clip, 9:16, 480p, audio off, @Image references in upload order), then emit the exact generate-with-seedance commands. The script validates against the official Seedance 2.5 rules; you write the prompts. No billable API calls.
---

# UGC Seedance prompt craft

Bridge between the analysis / replica plan and `generate-with-seedance`. `scripts/craft.py` does the deterministic part (skeleton from the analysis, rule validation, command rendering, dry runs). You write the prompts.

## Workflow

1. Build the skeleton from the analysis and the replica plan's references:

```bash
python3 /mnt/skills/ugc-seedance-prompt-craft/scripts/craft.py template \
  --analysis /mnt/session/outputs/01_analysis/analysis.json \
  --out /mnt/session/outputs/06_prompts/prompts.json
```

   It groups the sample's scenes into clips of 5-10 s (Seedance 2.5 minimum is 4 s; sample shots are usually shorter, so one clip covers 1-3 consecutive scenes and video-assembly trims them). Keep the clip count at or below the paid-call budget.

2. Fill `prompts.json` (schema in `references/prompt_plan_schema.md`): the `references` table (AI person images, personalized product previews, optional setting/style images), then one `prompt` per clip following `references/ugc_shot_patterns.md` and the official rules in `references/seedance25_rules.md`. Essentials:
   - Address references as `@Image1`, `@Image2`... in the order of the clip's `references` list. Bind each one in the first sentences ("@Image1 is the woman who appears in every shot", "@Image2 is the personalized sock: the sole artwork and the name LILY must match it exactly").
   - Describe the shots with timestamps that cover the whole duration ("0-4s ... 4-8s ...").
   - Always end with: "No subtitles, no on-screen text, no captions, no logos, no watermarks." Captions are burned in later by video-assembly.
   - Never mention anything from `do_not_copy` (other brands, platform UI, watermarks, the sample's names).
   - Personalized text (names, quotes) comes from the product preview image, not from prose: Seedance misspells typed text, so say "exactly as shown in @Image2".
   - Neutral emotional words ("pleased", "amused"), no dialogue lines in quotes (they trigger subtitles), realistic phone-shot UGC look, handheld, natural light.

3. Validate and fix until `"ok": true`:

```bash
python3 /mnt/skills/ugc-seedance-prompt-craft/scripts/craft.py validate \
  --plan /mnt/session/outputs/06_prompts/prompts.json \
  --analysis /mnt/session/outputs/01_analysis/analysis.json
```

4. Render the commands and run the free dry runs (they call `seedance-generate.mjs --dry-run`, which never submits):

```bash
python3 /mnt/skills/ugc-seedance-prompt-craft/scripts/craft.py render \
  --plan /mnt/session/outputs/06_prompts/prompts.json --dry-run
```

   Output: `commands.sh` (one `generate-with-seedance` call per clip, `--confirmed` included) and `clip_XX.prompt.txt` next to the plan, plus the dry-run request bodies.

5. Show the user the clip table (id, duration, references, first line of the prompt) and the number of paid tasks. After confirmation (or when the brief pre-approves the budget), run the commands from `commands.sh` one at a time with the `generate-with-seedance` skill rules (no automatic retries after an uncertain submission).

6. When a quality-gate retry routes back here (C3 setting, C4 hook, C5 hook-product link, C6 product visuals), edit only the failing clip's prompt, bump its `attempt`, validate, render and regenerate that clip only.

## Modes

- `reference` (default): AI person + product preview images as `reference_image`; any ratio and duration (4-30 s).
- `edit`: the sample video itself as `@Video1` (`reference_video`, public HTTPS URL, 4-30 s) with replace/edit wording; ratio `adaptive`, duration `-1`. Use only when the sample has no platform UI, watermark or brand overlay, because edit mode keeps everything that is not replaced.
- `extend`: continue a generated clip; ratio `adaptive`.

## Guardrails

- No API calls from this skill; billable generation happens only through `generate-with-seedance` after confirmation.
- Validation failures are blocking; warnings should be fixed when cheap.
- Keep prompts in English, one clip per task, audio off (`generate_audio: false` is sent by the generator script).
- Do not reference real people or copyrighted characters; AI people only.
