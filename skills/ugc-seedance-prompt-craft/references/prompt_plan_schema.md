# prompts.json schema

```json
{
  "source_video_url": "https://.../sample.mp4",
  "product": {"name": "Personalized Reading Socks", "names": ["LILY"], "personalization": "otter avatar + quote 'Do Not Disturb - I'm Reading' + name LILY on the soles"},
  "do_not_copy": ["..."],
  "defaults": {"version": "2.5", "model": "<endpoint from VIDEO_MODEL, optional>", "ratio": "9:16", "resolution": "480p", "download": "/mnt/session/outputs/07_clips"},
  "references": [
    {"id": "person_lily", "kind": "person", "path": "/mnt/session/outputs/04_people/person_lily.png", "describe": "woman about 30, wavy brown hair, cream knit sweater"},
    {"id": "product_lily", "kind": "product", "path": "/mnt/session/outputs/05_personalize/product_lily.png", "describe": "dark teal crew socks, otter artwork and LILY on the sole"},
    {"id": "sample_video", "kind": "video", "url": "https://.../sample.mp4"}
  ],
  "clips": [
    {"id": "clip_01", "mode": "reference", "duration": 8, "attempt": 1, "scenes": [1, 2],
     "references": ["person_lily", "product_lily"],
     "prompt": "@Image1 is ... @Image2 is ... 0-4s: ... 4-8s: ... No subtitles, no on-screen text ..."}
  ]
}
```

| Field | Notes |
|---|---|
| `references[].kind` | `person`, `product`, `texture` (product-page material/pattern photo), `photo` (the original AI photo for photo products), `staging` (a sample scene keyframe used only for framing, wrap/drape and scale; the printed design still follows the product reference. Only frames with NO real person in them: Seedance rejects references showing real people (privacy filter, seen 22 Oct 2026); for a staging idea with people, describe it in words or use a Seedream still made with the AI people), `setting`, `style` (images: local sandbox path or https URL) or `video` (public https URL only) |
| `product.layout` | the website preview's layout in words (which side carries what); the validator warns when a product shot does not restate it |
| `product.size_statement` | the chosen size with a scale cue; the validator requires its dimensions (e.g. "50 x 60") in every product shot prompt |
| `cast_count` | number of people in the sample; the replica casts the same number |
| `clips[].audio` | `true` adds `--generate-audio`; the prompt must then say "no music, no BGM" and describe natural sound only |
| `clips[].mode` | `reference` (default), `edit` (needs a video reference, ratio adaptive, duration -1, editing wording) or `extend` |
| `clips[].references` | ordered list of reference ids; the prompt addresses them as `@Image1`, `@Image2` ... (images) and `@Video1` ... (videos) in that order |
| `clips[].duration` | 4-30 (integer seconds) or -1 |
| `clips[].scenes` | the sample scene indexes this clip replaces (used by video-assembly to time captions) |
| `clips[].attempt` | bump when regenerating after a quality-gate retry |
| `clips[].seed` | optional integer |
| `clips[].first_frame` | path of a still to animate (sets `--first-frame` and ratio adaptive); only for shots whose opening frame does not show the product; never a composited product still |

`render` writes `commands.sh` next to the plan; each line is one `generate-with-seedance` call with `--download` set to `defaults.download` (clip files are saved as `<task_id>.mp4`; rename or map them in the edit plan by task id).

`defaults.version` and `defaults.model` come from the brief's `VIDEO_MODEL` line (for example `--version 2.0-mini --model ep-...`); `craft.py template --version ... --model ...` sets them. Seedance 2.0, 2.0 fast and 2.0 mini allow 4-15 s per clip (2.5: 4-30 s); fast and mini go up to 720p.
