---
name: product-personalizer
description: Personalize a product on the client's product page (e.g. macorner.co) in headless Chromium - upload the AI person's photo, enter the name, pick style/colour options - and capture the live preview image as the product reference for Seedance/Seedream. Probe mode inspects the page's personalization form first. Never adds to cart or checks out. No billable API calls.
---

# Product personalizer

Use `scripts/personalize.py`. It has two modes: `probe` (inspect the page) and `run` (execute an action plan). This replaces a personalization API while none is available; the output is the same preview image a shopper would see.

## Workflow

1. Install dependencies once per session. The first run takes about 1-2 minutes (Chromium plus system libraries); later runs are instant:

```bash
bash /mnt/skills/product-personalizer/scripts/ensure-deps.sh
```

2. Probe the product page:

```bash
python3 /mnt/skills/product-personalizer/scripts/personalize.py probe \
  --url "https://macorner.co/products/<handle>" \
  --out /mnt/session/outputs/personalizer/probe
```

3. Look at `probe_page_top.png`, `probe_form.png` and `probe.json` (the summary lists `option_groups`, `dropdowns` with their options, `preview_controls`, the downloaded `gallery_files` and, for photo-upload products, the `photo_guide` text and screenshot). Identify: the photo upload input, the name field (and its `maxlength`), each option group (style, size, colour swatches) and the preview element (often `canvas.lower-canvas`). Note the product name and prices shown; they feed the end card.

4. Write an action plan following `references/action_plan.md`. Inputs:
   - the AI-generated person's image from the Seedream step (never a real person's photo); for photo-upload products it must follow the page's photo guide (normally a full-body, front-facing photo), otherwise the site renders only a bust,
   - the name and options agreed in the generation plan.

5. Run it:

```bash
python3 /mnt/skills/product-personalizer/scripts/personalize.py run --plan /mnt/session/outputs/personalizer/plan_lily.json
```

6. Read the run's JSON first: `options` (each choice and whether it stayed selected), `warning`, `reapplied_options`, `recovered_from` and capture `method` explain most problems without a rerun. The script confirms photo-editor dialogs, re-applies options the page reset and falls back through several capture methods by itself (see `references/action_plan.md`). Then open every captured image. Confirm the name is spelled correctly, the photo or avatar appears, and the chosen options show. Then crop and zoom into the artwork and check it is ad-safe: no profanity, rude gestures, other brands or off-brand content (see the content check in `references/action_plan.md`). If a step failed, read `error_step_XX.png`, fix that step and rerun the whole plan once. If it fails again, stop and report. To save time with several people, personalize them in one page load (one capture per person) instead of one run each.

7. Capture two or three more personalized variants in the same run (different colour, quote/animal, name) with `capture_dialog` on the site's preview dialog, for the options montage.
8. Report the preview path(s), the variant dialog screenshots and the gallery files. The preview is the product's source of truth (which side carries what, where the portrait sits); describe that layout in words for the prompt step.

## Guardrails

- Never add to cart, buy, check out, log in, subscribe or enter personal or payment details. The script refuses clicks on such controls; do not work around it.
- Upload only AI-generated images created in this session.
- One page load per run; several people can be personalized one after another in it (one capture each). If the site returns 429 (Too Many Requests), stop and tell the user; do not retry in a loop.
- Do not change the site's prices or claims; report them exactly as shown on the page.
- Page structures change. If the probe shows different fields than expected, adapt the plan to what the probe shows; do not guess selectors.
