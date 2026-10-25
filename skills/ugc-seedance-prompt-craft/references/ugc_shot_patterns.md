# UGC ad shot patterns for Seedance 2.5 prompts

Goal: clips that cut together like the sample (same purpose per shot, same pacing) but show the client's personalized product on new AI people. Captions, end card and disclaimer are added later by video-assembly, so clips carry **no text**.

## Prompt skeleton (per clip, 5-10 s, 1-3 shots)

```
@Image1 is <PERSON>: <age, hair, outfit>; the same person appears in every shot, consistent face and clothes.
@Image2 is the personalized <PRODUCT>: <what is printed/personalized>; the artwork, colours and the name <NAME> must look exactly as shown in @Image2, legible, not deformed, not mirrored.
<One sentence: authentic phone-shot UGC video, vertical 9:16, natural daylight, lived-in home, handheld, realistic skin and fabric, no studio look.>
0-4s: [medium shot, static] <action that mirrors sample scene N: what the person does, where the product is, which part of it faces the camera>.
4-8s: [close-up, slow push-in] <product detail: the personalized area fills the frame for at least 2 seconds, in focus>.
Keep the product the same size and design in every shot. Neutral, pleasant expressions. No subtitles, no on-screen text, no captions, no logos, no watermarks, no other brands.
```

## Mapping sample purposes to shots

| Sample purpose | What the clip must show | Typical framing |
|---|---|---|
| hook | the person in a relatable situation; the product appears or is revealed within 1-2 s | medium-wide, eye level, static or slight handheld |
| personalization | the personalized area (name, photo, artwork) large and in focus for 2+ s | close-up, shallow depth of field |
| product_detail | material, pattern, stitching, how it is worn or used | close-up, low angle or top-down |
| lifestyle_social_proof | the product in everyday use at home | medium, handheld, natural light |
| gifting_unboxing | hands open a box/tissue to reveal the product | top-down close-up, handheld |
| product_hero | the whole product laid out, full design visible | flat lay, slow push-in |
| cta | not generated: the end card is rendered by video-assembly | - |

## Shots with several personalized items: one edit per product, then merge

Video and image models mix names and portraits when one generation carries several personalized products, and pasted or warped artwork (print_overlay.py) looks fake. Proven method (Case A, 21 Oct 2026):
1. Plain still (generate-with-seedream 5.0-pro, 2K): the scene and people with PLAIN products, each a clearly different solid colour matching its artwork background, at real size (state it; e.g. 50 x 60 inch blankets cocooning each child from chin to past the toes, hems pooling on the couch). Check size and faces before going on.
2. One Seedream edit per product, run side by side with `scripts/edit_batch.py run --jobs edit_jobs.json --state 07_clips/seedream_state.json` (each job = the arguments of one generate-with-seedream call; call again until pending is 0; one after another a dozen edits cost 10-15 minutes), ALWAYS on the plain still (never chain edits: each edit re-renders the picture and erases earlier prints), with exactly two inputs: the plain still and that product's personalizer image. Prompt: "Edit image 1. Change only the <colour> <product> of <owner>: print on its outer surface exactly the design of image 2 - <the cartoon in words>, and only the name <Name> ... following the folds and drape of the fabric, at the real scale of <size>. Keep everything else in image 1 exactly unchanged: the other products stay completely plain with no print and no text, every face, pose, background, light and framing."
3. Merge: `scripts/edit_merge.py --base plain.png --out merged.png --item "<description>|<edit>|<personalizer preview>" ...` takes each product from its own edit by colour mask. Zoom into every product: its own portrait and name only, correctly spelled. Redo only the failing product's edit.
4. Animate the merged still with generate-with-seedance in first-frame mode (`--first-frame`, ratio adaptive) and small motion; the prints stay because nothing on them is regenerated from scratch. If the privacy filter refuses a close-up of photoreal children, step the framing back a little.
5. Run ugc-quality-gate clip_check.py on the clip.
For folded or stacked products, the plain still shows the folds at real thickness (about 1 cm per layer for fleece/sherpa); each edit prints that fold with its own names.
Reference mode with several products (person photos + personalizer images) is the fallback when no plain still is possible; it leaves stray names. `scripts/print_overlay.py` stays for layout checks only, never as a video input.

## Rules of thumb

- **Physical realism for wearables.** Say who wears which item and that each foot (hand) wears exactly one: "Harper wears the personalized pair, one sock on each foot; Willow wears plain cream socks". Never ask for one pair to appear on two people in the same shot (the model then doubles the socks up on one foot). An item nobody wears is described as empty, lying flat and collapsed on the surface, no feet inside, cuffs flat; never "soles up" alone, which makes the model stand empty socks up like invisible feet. Show soles to the camera on a person's raised feet instead.

- **Real product size.** Seedance has no sense of scale: a blanket comes out towel-sized unless the prompt states the physical size and a scale cue. Put the chosen size in every product shot in words a camera understands: "the blanket is 50 x 60 inches (127 x 152 cm): held up by an 8-year-old it is taller than the child and wider than their arm span, the bottom edge touches the floor; wrapped, it covers the child from shoulders to feet with fabric to spare; folded, the stack is as wide as the couch cushion". Attach the product page's size chart and any gallery photo that shows the product on furniture or with a person as `texture`/`setting` references and say "size relative to people as in @ImageN".
- **Blankets wrap, they do not lie flat.** The sample's blankets envelop the children: pulled up around the shoulders, bunched in the lap, spilling over the couch edge to the floor; the child is inside the blanket, not under a flat sheet. Say it: "each child is cocooned in their own blanket pulled up to the shoulders, the blanket bunched around them with folds and the sherpa edge turned out, the lower part draping over the couch edge toward the floor; the printed portrait sits on the fabric over the lap/chest and faces the camera". Attach the sample's scene keyframe as a `staging` reference and say "framing, how the blankets wrap and drape, and the scale relative to the children as in @ImageN; the printed design itself follows @Image2".
- **Faces stay visible.** When a person holds the product up, the top edge stays at chest or shoulder height so the face is fully visible above it (as in the sample); never let the product cover a face. Say it explicitly: "she holds the blanket at chest height; her whole face is visible above the top edge".

- **The product beats the sample.** The website preview (`@Image2`) defines the layout: which sole carries the quote and which the animal + name, where the portrait sits, the leg pattern, cuff and toe colours. Restate that layout in words in every product shot ("left sole: the quote text; right sole: the owl and the name NORA; leg: the bookshelf pattern") and add "never mirrored or swapped". If the sample shows the product the other way round, follow the website, not the sample.
- **Copy the sample's world.** Setting, season and decor (a Christmas tree and fairy lights if the sample has them), time of day, furniture style, number of people and their ages come from `analysis.json`; only the product, the people themselves, the names and the brand change.
- **Texture shots** use the product-page gallery images as `texture` references: "the sock is stretched between two hands so the bookshelf pattern of @Image3 fills the frame", "a hand strokes the fleece; the sherpa lining of @Image3 folds over at the edge". One texture clip per product, 4-5 s.
- **Audio**: clips may generate natural sound only when the plan sets `"audio": true` and the prompt says "no music, no BGM; only room tone and <children giggling / fabric rustle>"; music is added in assembly from the client's track.

- One person per clip unless the sample shows two; children appear with a parent or alone at home, never in unsafe situations.
- Products: a sock sole faces the camera when the personalization is on the sole; a blanket is held up or spread so the printed cartoon and name face the camera; keep text unmirrored.
- Photo/avatar products (blankets, pillows, mugs with a printed portrait): every product shot must show the portrait. Write it explicitly: "the large cartoon portrait of the child printed in the middle of the blanket, exactly as in @Image2, faces the camera and is fully visible; the name pattern surrounds it". Clips whose product shows only the name pattern without the portrait fail C2 and must be regenerated before assembly; prefer one shot where the blanket is held flat toward the camera.
- Say "the same person as @Image1" in every clip that reuses a person, and "the product exactly as @Image2" in every product shot.
- Keep each shot 3-5 s; two or three shots per clip; hard cuts between shots ("at the 4-second mark, hard cut to ...").
- Do not describe prices, offers, brand names or captions in the prompt.
- Match the sample's mood words from `analysis.style` (look, lighting, palette) but not its brand, UI or watermark.
- Faces: friendly everyday look, no glamour lighting; avoid "perfect", "stunning"; prefer "natural", "relaxed".
- When a clip fails C6 (product deformed/illegible), simplify: fewer shots, product closer and still, "product stays rigid and flat, no hands covering the artwork".
- When a clip fails C1 (person looks unnatural), reduce motion ("sits still, small natural movements") and keep the face medium-sized, not extreme close-up.

## Writing the still prompts: `scripts/still_prompts.py` (tested 23 Oct 2026)

Do not hand-write Seedream prompts for stills with personalized products. Describe the shot in a small spec (people, each product's colour, real size, how it is used, preview image, name text, main art; scene, setting focus, framing, action) and run `still_prompts.py --spec still_spec.json --out <dir>`. It writes the plain-scene prompt, one print-edit prompt per product, the edit_batch job files and the merge command, with the rules that made the stills right:
- **Real size beside the people, used naturally.** A 50 x 60 inch blanket wraps a child from the chin to the floor; a small panel over the lap looks like a different product. Compare the plain still with the sample frame: if the sample's product looks bigger, make it bigger or frame closer.
- **The whole visible surface is printed.** The print edit asks for the entire surface, every fold, no plain areas, names spelled letter by letter, the main art large on the visible face. Edges and linings stay plain.
- **Every person is the same person as their photo.** On photo products the cartoon is drawn from that photo, so a child who looks different from their own cartoon is a wrong product. still_prompts.py sends each person's photo with the prompt and names it; after every still, compare each face, skin tone and hair with its photo and with the cartoon on their product.
- **A person holds their own product with their own hands,** unless the sample clearly shows someone else holding it.
- **Clothes are never the product's colour, and the setting's key element (tree, table, bed) is large in the frame.**
- **Two steps for a single product too, when the size changes:** a big plain product first, then the print. Printing and resizing in one edit garbled the names.
- **Seedance refuses a still as a possible real person** (close, sharp faces): make a zoom-out edit (people about half the frame) and animate that.
Look at the plain still before the print edits, and zoom into every product after the merge.

## Replicating a scene beat by beat (balaclava review, 25 Oct 2026)

A client review of a replica that passed every automatic check found seven faults. Each came from one of these rules being missing:
- **The payoff goes early and the edit keeps it.** A Seedance clip is 4-6 s; the sample shot is often 2-3 s. Put the scene's payoff beat (the dog walks in, the barista bursts out laughing, the mask is pulled down over the face) at 1-3 s of the clip timeline, set `payoff` and `use`, and pass `--payoff` to clip_check: its `payoff_window` is where the edit plan's start/end go. A payoff at 4-5 s with the edit keeping 0-3 s is a scene without its joke.
- **Copy the camera and the motion, not just the place.** `analysis.scenes[].camera_position` and `motion` decide the shot: a man leaning out of a moving car's window filmed from outside is a different hook from a selfie in a parked car. Never add "parked", "stays still" or "small natural motion" to protect the print when the sample moves; protect the print with the product spec and a first-frame still instead.
- **Reactions are the joke.** Every entry in the scene's `reactions` goes into the prompt as a visible action with its place in the frame: "the golden retriever at the left barks at the mask", "the woman at the right bursts out laughing and turns away", "four passers-by around him laugh and point". Passers-by who react are part of the shot, at mid-ground size, not "far behind".
- **The product state follows the sample mechanically.** Write how the product sits at the start and at the end (from `product_state`): "the mask already covers his whole head and hair; only its front panel is rolled up inside-out above his eyebrows; he pulls it down over his face to the neck". A band on the forehead with hair showing is a different product.
- **One product spec, pasted unchanged.** Write `product.spec` once from the website preview and the product page's own worn photos (where the print sits, how much of the head/body it covers when worn, plain areas), paste it word for word into every still and clip prompt that shows the product, and give the same text to clip_check as the expected description. Reworded specs contradicted each other and the clip check failed correct clips against the wrong wording (24 Seedance tasks for 7 clips).
- **Worn prints at their real scale.** On a full-face wearable (balaclava, mask), the printed face covers the whole front of the head as on the product page's worn photos: forehead to chin, ear to ear. A smaller face floating in black fabric is a wrong product.
- **Leave room for the caption.** When the sample keeps a caption at the top through the video, frame every shot so faces and the product stay below about the top 25% of the frame (the walking shot is the usual offender).
- **Never drop a beat silently.** If a beat (a hand pinching the mask, a stretch) keeps failing, keep it and change how it is shown (closer, slower, a first-frame still at the beat); report it if it still fails, instead of removing it.
- **Stretch shots keep the print's colours.** Hands lift the item into the air and stretch it lengthwise as in the sample, moderately; say "the print keeps its exact colours while it stretches, no washing out". Start from a first-frame still of the hands holding the real product.

## Stills from the sample's own frames (balaclava review 2, 25 Oct 2026)

- **Give the image model the sample frame for composition.** Text alone produced a man sitting backwards in the car seat; adding the sample's frame as the last Seedream input ("Match image N exactly for pose, body orientation, camera position and angle, framing and setting type; use the man of image 1 and the print of image 2") reproduced the blocking at once. Use `analysis.scenes[].staging_frame` only when `real_face_visible` is false (masked, turned away, hands only), and blur the sample's caption band first so it is not copied. With a real face in the frame, describe the blocking in words from `pose`.
- **Describe how a material looks, not its trade name.** "Breathable mesh" was drawn as see-through fishnet; "smooth, opaque black stretch fabric, fine knit, no visible holes" matches the product. Check the product page photos: if the fabric looks solid, say solid.
- **Putting a wearable on follows the sample's order.** A balaclava goes over the back of the head first; before it is pulled down, the whole lower part (face panel and neck tube) is rolled up on the forehead and the neck is bare. Write the state at the start and at the end, and what is NOT on yet.
- **Check every first-frame still before animating** with ugc-quality-gate `still_check.py` (the still next to the sample frame; about a cent, against about 50 cents for a clip). It catches the product (holes, print size), hands and the product state well; body orientation is not reliably seen by the default checker model, which is why the sample frame goes into the still itself.
- **The sample video cannot be a Seedance input when real people are in it.** Tested 25 Oct 2026: the whole balaclava sample in edit mode ("replace the print, the dog and the people") and its 4 s donning segment as a motion reference were both refused at submission with `InputVideoSensitiveContentDetected.PrivacyInformation` ("the input video may contain real person"); refusals are not billed. Edit or reference mode on a video works only on footage without identifiable people (hands only, product only) or on our own generated clips. For people shots, copy the motion in words from `beats` and the blocking from the staging frame.
- **Motion needs a speed and what passes the camera.** "The SUV drives forward slowly; the houses slide past" gave a parked-looking car (clip check: background static). "The SUV is DRIVING at about 20 mph the whole time: houses, lawns, trees and parked cars rush past behind him from the front of the car to the back, with motion blur; road bumps shake the phone" gave a moving street. Put the speed, the direction of what passes, blur and shake into every shot whose sample `motion` has a moving vehicle or a walking camera.
