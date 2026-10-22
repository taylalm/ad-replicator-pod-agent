---
name: generate-with-seedream
description: Generate or edit images with the BytePlus ModelArk Seedream API from a Managed Agents sandbox. Defaults to Seedream 5.0 pro, 1K, no watermark, and saves outputs to the sandbox. Use after the generation plan (prompts, references, number of images) has been confirmed.
---

# Generate with Seedream

Use `scripts/seedream-generate.mjs` instead of composing ad-hoc API calls.

## Workflow

1. Gather the subject, use case, size, visual style, required text and reference images. Do not ask again when the user already supplied enough detail.
2. Present the generation plan before the first billable call: every prompt, its references, size, and the total number of images (including the retry budget). Explain that generation incurs API charges.
3. Wait for the user to confirm the plan. One confirmation covers every image in that plan, including retries within the stated budget. Ask again before exceeding the budget or changing the model.
4. After confirmation, run one command per image:

```bash
node /mnt/skills/generate-with-seedream/scripts/seedream-generate.mjs \
  --confirmed \
  --prompt "<final prompt>" \
  --version "5.0-pro" \
  --size "1K" \
  --output-format png \
  --download /mnt/session/outputs \
  --name character_olivia
```

5. For image editing or reference-guided generation, repeat `--image`. Each value can be an HTTPS URL, a data URL, or a local image file in the sandbox (png, jpg, jpeg, webp); local files are sent as base64 data URLs.
6. Always pass `--download <dir>` and `--name <prefix>`: output URLs are retained for 24 hours only. Return the saved file paths plus every URL and size from the script's JSON output.

## Model selection

| Version | Model ID | Use when |
|---|---|---|
| `5.0-pro` (default) | `dola-seedream-5-0-pro-260628` | Highest quality. Sizes 1K (default), 1.5K, 2K; png or jpeg |
| `5.0-flash` | `dola-seedream-5-0-flash-260915` | Faster, cheaper drafts. Same sizes and formats |
| `5.0` / `5.0-lite` | `seedream-5-0-260128` / `seedream-5-0-lite-260128` | Only when explicitly requested |
| `4.5` / `4.0` | `seedream-4-5-251128` / `seedream-4-0-250828` | Only when explicitly requested |

- 5.0 pro / flash also support interactive editing (point/bbox coordinates in the prompt) and layer decomposition; see the Seedream 5.0 pro / flash tutorial before using them.
- 5.0 pro / flash reject the `sequential_image_generation` parameter (API 400 InvalidParameter), so the script never sends it unless `--sequential` is passed, and refuses `--sequential` on these versions. Make one call per image. Image series (`--sequential auto --max-images N`) is for older versions only.
- Do not automatically switch versions and resubmit after a timeout, 5xx response, or uncertain result. Report the error and ask before another billable request.

## Guardrails

- Read `ARK_API_KEY` only from the environment. Never print, inspect, copy, or persist it.
- Use `ARK_BASE_URL` when provided; otherwise `https://ark.ap-southeast.bytepluses.com/api/v3`.
- Watermark is off by default because outputs are reused as references; pass `--watermark` when the image is a final deliverable that requires one.
- Do not claim an image exists unless the API response contains an output URL or base64 result.
- Use `--dry-run` to inspect the request body before submitting; it never calls the API.
- Reject requests that violate applicable policy, consent, privacy, intellectual-property, or likeness requirements.

## Useful options

```bash
node /mnt/skills/generate-with-seedream/scripts/seedream-generate.mjs --help
```
