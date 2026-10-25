# analysis.json schema

Write `analysis.json` next to `extraction.json`. It is the brief every later step reads: the Seedance prompts, the edit plan for video assembly, and the quality gate. Describe only what is visible in the contact sheets and keyframes (or audible, when audio was checked). Do not guess.

A complete worked example from a real sample is in `example_socket_analysis.json` (it predates the scene detail fields; the scene below shows them).

One scene with the scene detail fields (pet-face balaclava prank, 17 s sample):

```json
{"index": 3, "start": 5.6, "end": 8.56, "shot": "Static frontal, seated, knees-up", "camera": "static",
 "camera_position": "tripod or propped phone in front of the couch at chest height",
 "pose": "seated on the couch facing the camera, hands on knees; dog at his left, woman at his right", "staging_frame": "keyframes/scene_03_a.jpg", "real_face_visible": true,
 "motion": "the golden retriever at the left edge leans in and barks at the masked man; the woman at the right edge laughs and turns away; the man stays still",
 "product_state": "worn over the whole head under a black hood, unchanged through the scene",
 "beats": [{"t": 5.6, "what": "dog already at the left, sniffing the mask"}, {"t": 6.4, "what": "dog barks at the mask", "payoff": true}, {"t": 7.0, "what": "woman at the right laughs, mouth moving as if talking"}],
 "reactions": [{"who": "golden retriever", "where": "left third, head at mask height", "what": "sniffs, then barks at the printed face"}, {"who": "woman about 30", "where": "right edge, half in frame", "what": "laughs and appears to speak"}],
 "setting": "beige couch, FAMILY wall sign", "description": "...", "product_visible": true, "personalization_visible": "pet print worn", "purpose": "lifestyle_social_proof"}
```

| Field | Type | What to write |
|---|---|---|
| `summary` | string | One or two sentences: what the ad is, how it sells, what makes it work. |
| `format` | string | The ad pattern, e.g. "POV meme caption + product montage", "problem/solution talking head", "unboxing". |
| `duration_s` | number | From `extraction.json`. |
| `hook` | object | `start`, `end`, `type` (e.g. `pov_text`, `question`, `problem`, `reveal`, `pov_text_plus_reveal`), `text` (exact on-screen words, if any), `description` (what happens and why it grabs attention). |
| `scenes` | list | One entry per scene from `extraction.json` (merge or split if the detector was wrong, and say so in `replication_notes`). Each: `index`, `start`, `end`, `shot` (framing and angle), `camera` (static, handheld, push-in…), `setting`, `description`, `product_visible` (bool), `personalization_visible` (what personalized element shows, or "none"), `purpose` (`hook`, `personalization`, `product_detail`, `lifestyle_social_proof`, `gifting_unboxing`, `product_hero`, `cta`, …). |
| scene detail (required per scene) | | These fields are what the clip prompts and the edit are built from; a wrong one costs a whole regenerated clip. `camera_position`: where the camera is relative to the subject and the set, e.g. "outside the car at the open driver window, phone held by the man at arm's length pointing back at him" vs "inside the car, selfie from the driver's seat". `motion`: everything that moves: subject action, camera move, and the background (a street sliding past means the car is driving; trees shifting between consecutive 0.5 s frames mean the camera walks). Write "static" only when consecutive frames are the same. `pose`: body pose and orientation relative to the set, the way a director would block it, e.g. "seated in the driver's seat facing the windshield like a driver, only the head turned left to the open window" (never just "facing the camera"). `staging_frame`: the keyframe path that shows the shot best, and `real_face_visible` (true when a real person's face can be seen in it; masked or turned-away faces are false): frames without a real face are given to the image model as a composition reference. `product_state`: how the product is worn or held at the start and at the end of the scene, mechanically, e.g. "mask already over the whole head and hair; only its front panel is rolled up inside-out above the eyebrows" -> "front panel unrolled down over the face to the neck". Use "none" when the product is not in the scene. `beats`: the time-ordered actions inside the scene, each `{"t": seconds from the video start, "what": ...}`, with the payoff marked `"payoff": true` (the dog walks in, the barista bursts out laughing, the print reads full). The edit keeps the payoff, so its time must be right. |
| `reactions` (per scene) | list | Every on-camera person or animal reacting to the product or the gag: who, where in the frame, what they do (laugh, point, film, bark, turn away), and how big they are in the frame. Reactors are part of the joke: count each distinct person in `people` (a group of passers-by is one entry, role "reacting passers-by, about 4") and never file them as background. Use [] when nobody reacts. |
| `on_screen_text` | list | Every caption the ad itself shows. Each: `start`, `end`, `text` (exact, including emoji), `position`, `style`, `role` (`hook`, `benefit`, `price`, `cta`, `caption`). Exclude platform UI text. |
| `product` | object | `type`, `features_shown` (list), `personalization_elements` (list). |
| `people` | list | Each: `description` (appearance and outfit, no names or guesses about identity), `role`, `appears_in_scenes`. Count every distinct on-camera person; "hands only" entries are not cast. |
| `cast_count` | int | Number of distinct on-camera people (the replica casts exactly this many, same ages and mix). |
| `caption_style` | object | How the sample's captions look, so assembly can copy it: `lines_max` (1 or 2), `position` (`top`, `upper`, ...), `size` (`small`/`medium`/`large`, with the cap height as a fraction of frame height if measurable), `weight`, `outline` (colour or none), `emoji` (true/false and which), `tone` (who speaks and how, e.g. "excited parent, first person, exclamation, one CAPS word for emphasis, trailing ellipsis to chain lines"), `examples` (two of the sample's captions verbatim, for tone only; the replica rewrites the words), `colors`, `offer_style` (how price/offer lines differ, e.g. yellow italic with dark outline), `pill` (true if some lines sit on a dark pill). |
| `shot_arc` | list | The narrative order in a few words per shot, e.g. ["group reveal on the couch", "per-child hold-up with photo inset and arrow", "cozy reading use shot", "texture close-up", "folded stack with offer", "group close", "brand outro"]. The replica follows the same arc. |
| `keep` | list | What the replica must reproduce from the sample besides structure: setting and decor (including seasonal items such as a Christmas tree), lighting and time of day, cast size and ages, pacing, caption style, music mood, texture and unboxing beats. These are instructions to keep, never to avoid. |
| `cta` | object | `present` (bool), `form` (`text`, `end_card`, `verbal`, `none`), `text`, `start`. |
| `style` | object | `look`, `lighting`, `color_palette`, `pacing` (shots, average shot length, cut style), `audio` (what was observed: none, music, voiceover, sound effects; or "not checked"). You cannot hear the file: when someone visibly speaks or an animal visibly barks, write it as a beat ("appears to speak") and add a `replication_notes` line asking the user for the words if they matter to the joke. |
| `do_not_copy` | list | Everything that must not appear in the replica: platform UI from screen recordings, other brands, logos, account names, policies and taglines, watermarks (check `watermark_check.jpg`; AI-model marks such as "Veo" count), real people's faces, the sample's own product artwork and example names, and the sample's exact caption wording (captions are rewritten). Never list setting, decor or mood here: those belong in `keep`. |
| `replication_notes` | list | Concrete instructions for the next steps: structure to keep, what to change, timing, gaps to fill (e.g. "no CTA in the sample: add an end card"). |

Validate before moving on:

```bash
python3 /mnt/skills/ugc-video-analyzer/scripts/analyze.py --check /mnt/session/outputs/analysis/analysis.json
```
