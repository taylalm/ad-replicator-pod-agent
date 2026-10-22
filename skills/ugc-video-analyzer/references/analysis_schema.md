# analysis.json schema

Write `analysis.json` next to `extraction.json`. It is the brief every later step reads: the Seedance prompts, the edit plan for video assembly, and the quality gate. Describe only what is visible in the contact sheets and keyframes (or audible, when audio was checked). Do not guess.

A complete worked example from a real sample is in `example_socket_analysis.json`.

| Field | Type | What to write |
|---|---|---|
| `summary` | string | One or two sentences: what the ad is, how it sells, what makes it work. |
| `format` | string | The ad pattern, e.g. "POV meme caption + product montage", "problem/solution talking head", "unboxing". |
| `duration_s` | number | From `extraction.json`. |
| `hook` | object | `start`, `end`, `type` (e.g. `pov_text`, `question`, `problem`, `reveal`, `pov_text_plus_reveal`), `text` (exact on-screen words, if any), `description` (what happens and why it grabs attention). |
| `scenes` | list | One entry per scene from `extraction.json` (merge or split if the detector was wrong, and say so in `replication_notes`). Each: `index`, `start`, `end`, `shot` (framing and angle), `camera` (static, handheld, push-in…), `setting`, `description`, `product_visible` (bool), `personalization_visible` (what personalized element shows, or "none"), `purpose` (`hook`, `personalization`, `product_detail`, `lifestyle_social_proof`, `gifting_unboxing`, `product_hero`, `cta`, …). |
| `on_screen_text` | list | Every caption the ad itself shows. Each: `start`, `end`, `text` (exact, including emoji), `position`, `style`, `role` (`hook`, `benefit`, `price`, `cta`, `caption`). Exclude platform UI text. |
| `product` | object | `type`, `features_shown` (list), `personalization_elements` (list). |
| `people` | list | Each: `description` (appearance and outfit, no names or guesses about identity), `role`, `appears_in_scenes`. Count every distinct on-camera person; "hands only" entries are not cast. |
| `cast_count` | int | Number of distinct on-camera people (the replica casts exactly this many, same ages and mix). |
| `caption_style` | object | How the sample's captions look, so assembly can copy it: `lines_max` (1 or 2), `position` (`top`, `upper`, ...), `size` (`small`/`medium`/`large`, with the cap height as a fraction of frame height if measurable), `weight`, `outline` (colour or none), `emoji` (true/false and which), `tone` (who speaks and how, e.g. "excited parent, first person, exclamation, one CAPS word for emphasis, trailing ellipsis to chain lines"), `examples` (two of the sample's captions verbatim, for tone only; the replica rewrites the words), `colors`, `offer_style` (how price/offer lines differ, e.g. yellow italic with dark outline), `pill` (true if some lines sit on a dark pill). |
| `shot_arc` | list | The narrative order in a few words per shot, e.g. ["group reveal on the couch", "per-child hold-up with photo inset and arrow", "cozy reading use shot", "texture close-up", "folded stack with offer", "group close", "brand outro"]. The replica follows the same arc. |
| `keep` | list | What the replica must reproduce from the sample besides structure: setting and decor (including seasonal items such as a Christmas tree), lighting and time of day, cast size and ages, pacing, caption style, music mood, texture and unboxing beats. These are instructions to keep, never to avoid. |
| `cta` | object | `present` (bool), `form` (`text`, `end_card`, `verbal`, `none`), `text`, `start`. |
| `style` | object | `look`, `lighting`, `color_palette`, `pacing` (shots, average shot length, cut style), `audio` (what was observed: none, music, voiceover, sound effects; or "not checked"). |
| `do_not_copy` | list | Everything that must not appear in the replica: platform UI from screen recordings, other brands, logos, account names, policies and taglines, watermarks (check `watermark_check.jpg`; AI-model marks such as "Veo" count), real people's faces, the sample's own product artwork and example names, and the sample's exact caption wording (captions are rewritten). Never list setting, decor or mood here: those belong in `keep`. |
| `replication_notes` | list | Concrete instructions for the next steps: structure to keep, what to change, timing, gaps to fill (e.g. "no CTA in the sample: add an end card"). |

Validate before moving on:

```bash
python3 /mnt/skills/ugc-video-analyzer/scripts/analyze.py --check /mnt/session/outputs/analysis/analysis.json
```
