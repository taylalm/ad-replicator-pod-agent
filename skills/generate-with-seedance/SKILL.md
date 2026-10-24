---
name: generate-with-seedance
description: Submit and monitor Seedance video generation tasks (text-to-video, first-frame, omni reference, video edit, video extend) from a Managed Agents sandbox. Defaults to Seedance 2.5, 9:16, 480p, no audio. Use after the generation plan (prompts, references, durations, number of tasks) has been confirmed.
---

# Generate with Seedance

Use `scripts/seedance-generate.mjs` for both task submission and status polling. Do not compose ad-hoc API calls.

## Workflow

1. Gather the purpose, storyboard, shot motion, visual style, ratio, duration, resolution and references. Do not ask again when the user already supplied enough detail.
2. Present the generation plan before the first billable call: every prompt, its references, duration, ratio, resolution, and the total number of tasks (including the retry budget). Explain that tasks incur API charges and take time.
3. Wait for the user to confirm the plan. One confirmation covers every task in that plan, including retries within the stated budget. Ask again before exceeding the budget or changing model, resolution or duration.
4. After confirmation, run one command per task:

```bash
node /mnt/skills/generate-with-seedance/scripts/seedance-generate.mjs \
  --confirmed \
  --prompt "<final prompt>" \
  --version "2.5" \
  --ratio "9:16" \
  --duration "8" \
  --resolution "480p" \
  --reference-image /mnt/session/outputs/character_olivia.png \
  --reference-image /mnt/session/outputs/design_olivia.png \
  --download /mnt/session/outputs/clips
```

   **Several clips: submit them together.** A tool call in the sandbox ends after about 2 minutes and one clip takes 3-5 minutes, so clips run one after another cost the sum of all clips. With a `commands.sh` from ugc-seedance-prompt-craft, submit every clip at once, then collect them:

```bash
python3 /mnt/skills/generate-with-seedance/scripts/batch.py submit --commands /mnt/session/outputs/06_prompts/commands.sh \
  --state /mnt/session/outputs/07_clips/tasks.json            # optional: --clips clip_01,clip_04
python3 /mnt/skills/generate-with-seedance/scripts/batch.py wait --state /mnt/session/outputs/07_clips/tasks.json
```

   `wait` polls every pending task for up to 100 s, downloads finished videos as `<task_id>.mp4` and prints a table; call it again until `pending` is 0. A clip already in the state file is never submitted twice; a submission with an uncertain result is marked `uncertain` and not retried. For a new attempt, give the clip a new id (for example `clip_02_v2`) in prompts.json, render again and submit that id with `--clips`.

5. References:
   - `--reference-image` (repeatable) accepts an HTTPS URL, a data URL, or a local image file in the sandbox (png, jpg, jpeg, webp); local files are sent as base64 data URLs.
   - `--reference-video` (repeatable) accepts public HTTPS URLs only. Recommended length 4–30 s each.
   - `--first-frame` / `--last-frame` start a first-frame task; the ratio is then forced to `adaptive`.
   - In the prompt, refer to inputs as @Image1, @Image2 … and @Video1 … in the order they are passed.
6. Task types (Seedance 2.5 "Read before use" rules, enforced by the script):
   - Reference-to-video: references only, any ratio/duration. Optionally `--omni-task-type reference`.
   - Video edit (replace a subject, add/remove objects): `--omni-task-type edit`, at least one `--reference-video`, `--ratio adaptive`, `--duration -1`. The prompt must say edit / add / remove / replace.
   - Video extend: `--omni-task-type extend`, at least one `--reference-video`, `--ratio adaptive`. The prompt must say extend / continue.
7. Audio is OFF unless `--generate-audio` is passed. The API itself defaults to audio ON, so the script always sends `generate_audio` explicitly. Generated audio has triggered `OutputAudioSensitiveContentDetected` copyright rejections; keep audio off and add music in post-production unless the user asks otherwise.
8. Preserve every returned `task_id`. The script polls that task until `succeeded`, `failed`, `cancelled`, `expired`, or the local wait limit. If waiting times out, query later with `--task-id <id>`; never create a replacement task automatically.
9. Always pass `--download <dir>` (e.g. `/mnt/session/outputs/clips`): result URLs expire. Return the saved file path and the complete `content` object.

## Model selection

| Version | Model ID | Duration | Resolution | Use when |
|---|---|---|---|---|
| `2.5` (default) | `dreamina-seedance-2-5-260628` | 4–30 s or -1 | 480p, 720p, 1080p | Default. Up to 30 s, up to 30 reference images + 10 videos, edit/extend, draft mode, mov output |
| `2.0` | `dreamina-seedance-2-0-260128` | 4–15 s or -1 | 480p–1080p, 4k | Only when explicitly requested |
| `2.0-fast` | `dreamina-seedance-2-0-fast-260128` | 4–15 s or -1 | 480p, 720p | Fast previews when 2.5 is unavailable |
| `2.0-mini` | `dreamina-seedance-2-0-mini-260615` | 4–15 s or -1 | 480p, 720p | Low-cost previews |
| `1.5-pro` | `seedance-1-5-pro-251215` | 2–12 s | 480p–1080p | Retiring; do not use for new work |

- Testing default: `--resolution 480p`. Raise to 720p/1080p only for final renders the user approves.
- `--duration -1` lets the model choose the length within the valid range.
- `--draft` (2.5 only) produces a cheaper draft; use it to check composition before a full render if the user agrees.
- Do not switch models automatically after a failed or uncertain submission. A timeout, network failure, 429 or 5xx can leave the result uncertain and must never trigger another billable POST.

## Guardrails

- Read `ARK_API_KEY` only from the environment. Never print, inspect, copy, or persist it.
- Use `ARK_BASE_URL` when provided; otherwise `https://ark.ap-southeast.bytepluses.com/api/v3`.
- Task creation is non-idempotent and billable. `--confirmed` is required; do not retry a POST automatically.
- Polling may be repeated with `--task-id <id>`; this does not create a new task.
- Do not claim success before the API reports `succeeded`.
- Use `--dry-run` to inspect the request body before submitting; it never calls the API.
- Reject requests that violate applicable policy, consent, privacy, intellectual-property or likeness requirements.

## Useful options

```bash
node /mnt/skills/generate-with-seedance/scripts/seedance-generate.mjs --help
```
