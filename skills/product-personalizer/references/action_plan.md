# Action plan format

`run` mode executes a JSON plan. Write it from `probe.json` and the probe screenshots: use the selectors the probe printed, or simpler equivalents you can see are unique (`#id`, `input[placeholder='Example: Mason']`, `input[name='Style'][value='...']`).

```json
{
  "url": "https://macorner.co/products/<handle>",
  "out": "/mnt/session/outputs/personalizer/lily",
  "steps": [
    {"action": "upload", "selector": "input[type=file][accept='image/*']", "file": "/mnt/session/outputs/character_lily.png", "snapshot": true},
    {"action": "wait_text_gone", "text": "Your Photo is being Prepared", "timeout_ms": 90000},
    {"action": "fill", "selector": "input[placeholder='Example: Mason']", "value": "Lily"},
    {"action": "click_text", "selector": "form.personalized-form", "text": "Style 2"},
    {"action": "click", "selector": ".swatch-container > *:nth-child(1)", "snapshot": true},
    {"action": "wait", "ms": 2000},
    {"action": "capture", "selector": "canvas.lower-canvas", "file": "preview.png"},
    {"action": "screenshot", "selector": "form.personalized-form", "file": "form_filled.png"}
  ]
}
```

| Action | Fields | What it does |
|---|---|---|
| `upload` | `selector`, `file` | Sets a file on an `<input type=file>`, even a hidden one. Use the AI-generated person's image only. |
| `fill` | `selector`, `value` | Types into a text box, then presses Tab so the preview updates. Respect `maxlength` from the probe. |
| `click` | `selector` | Clicks an option, swatch or button. Purchase and account controls are refused. |
| `click_text` | `text`, optional `selector` (scope), `exact` | Clicks the element showing that text, e.g. an option label. |
| `select` | `selector`, `label` | Chooses an option in a `<select>`. |
| `wait` | `ms` (max 90000) | Fixed pause, e.g. for an animation. |
| `wait_for` | `selector`, optional `state` | Waits until an element appears (or `"hidden"`). |
| `wait_text_gone` | `text` | Waits until a loading message disappears, e.g. a photo-processing notice. |
| `dismiss_popups` | | Closes newsletter/discount overlays again if one appears mid-flow. |
| `capture_dialog` | optional `selector`, `text`, `file` | Screenshots the site's visible preview dialog ("Looks Good to Go?") after a Preview click; `text` narrows it to the dialog containing that text (e.g. "Looks Good"). Used for the options montage: one capture per variant. |
| `close_dialog` | | Closes that dialog via its Close control or Escape; never its Add to cart button. |
| `capture` | `selector`, `file`, optional `method` | Saves the preview: exports a `<canvas>` as PNG, or screenshots any other element. |
| `screenshot` | optional `selector`, `file`, `full_page` | Saves a screenshot for checking. |

Every step accepts `timeout_ms` (default 30000) and `"snapshot": true` (screenshot after the step).

Tips:
- Run `probe` first and look at `probe_form.png`: option labels in the screenshot tell you which radio or swatch is which.
- Put a `wait_text_gone` or `wait_for` after an upload; photo processing can take 20 s or more.
- Capture after the last change, then open the image and check name, photo and options before using it.
- One product per run. Do not loop over many variations quickly; the site rate-limits automated traffic.

## Selector lessons from macorner.co (verified 19 Oct 2026)

- Option tiles: use the probe's `option_groups[].pattern`, e.g. `div.swatch-container >> nth=2 >> div:nth-of-type(5)` (group index from the probe, tile number counted left to right, top to bottom).
- Custom dropdowns (Ant Design): click the probe's `dropdowns[].open_with` (`... .ant-select-selector`), then `click_text` the option. Clicking the placeholder text itself does not open it. The probe lists the options.
- Style/size pills contain hidden markup: use `click_text` with `"exact": false`.
- The Preview control is not a `<button>`: use `{"action": "click", "selector": "text=Preview >> visible=true"}`. The preview dialog that opens also contains an "Add to cart" button: never click it.
- If unsure, do a short recon run first (open the dropdown, click one tile, screenshot), then write the full plan.
- Working example: `example_macorner_socks_plan.json`.

## Content check before using a preview in an ad

Zoom into the personalized artwork (crop the preview) and check for profanity, rude gestures, other brands or anything off-brand. Product art can carry jokes that are fine on a product page but not in an ad (the socks' rabbit artwork shows a raised middle finger). If an option fails, pick another option and re-run; if all options fail, report it instead of using it.

## Selector lessons from photo-upload products (blanket, verified 20 Oct 2026)

- Style/size choices are label tiles with hidden radio inputs: use `click_text` with `"exact": false` on the visible label, not `click` on the `input[type=radio]`.
- The photo-processing notice differs per store/page ("Your Photo is being Prepared", "Image Processing...", then "Ready to Preview and Edit!"). Use `wait_text_gone` on the text the probe screenshot shows, with `timeout_ms` 90000, or `wait_for` the "Ready" text; processing took about 30 s.
- The hidden upload input is `form.personalized-form input[type=file][accept="image/*"]` (not the review-photo upload elsewhere on the page). If an "Edit Photo" crop dialog opens, click its Apply/Done button (never a purchase control).
- Background colour tiles are not in a fixed colour order across pages: read the tile `background`/`image` from the probe before choosing by colour.
- Expect `canvas.lower-canvas` to be composed before the form's status text updates; capture after clicking Preview and a 3 s wait.

## Showing several personalized variants in one run (options montage)

One page load, several captures: after the main capture, change one or more options (colour tile, quote, animal, name), click Preview, `capture_dialog` to `variant_<name>_dialog.png`, `close_dialog`, repeat. Three extra variants are enough; use different colours, quotes/animals and names each time (all ad-safe). The dialog screenshots are cut into the ad by video-assembly as stills.

## Photo-upload products

- Read `photo_guide` from the probe (text + `probe_photo_guide.png`) and generate the AI person image to match it: usually a full-body, front-facing photo on a plain background, the whole person visible from head to feet, no hat or sunglasses, good light. The site turns it into a full-body cartoon; a head-and-shoulders photo gives only a bust, which the client rejected. Give each person a lively activity pose with a prop, like the product page's example cartoons (ballerina, basketball, football, reading): the cartoon inherits the pose, and plain standing poses look dull on the product.
- The probe downloads up to 8 product gallery images to `gallery_NN.jpg` (material, pattern, lifestyle). Pass the material/pattern ones to the prompt-craft plan as `texture` references.
