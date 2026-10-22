# Ad Replicator: UGC video ad replication on BytePlus ModelArk

A BytePlus ModelArk **Managed Agent** that recreates a sample UGC ad with new AI-generated people and your own personalized product, and delivers a finished 9:16 ad. A web app ("Ad Replicator") starts runs, shows the 11 steps live, lets a reviewer approve or change each step, and plays the result next to the sample.

```
sample MP4 + product page + brief
  -> 1 analyze the sample            (ugc-video-analyzer)
  -> 2 read the product page         (product-personalizer probe)
  -> 3 plan: people, products, scenes, captions        [reviewer approves]
  -> 4 AI people                     (generate-with-seedream)
  -> 5 personalized products         (product-personalizer run)
  -> 6 clip prompts                  (ugc-seedance-prompt-craft)
  -> 7 clips + per-clip product check (generate-with-seedance, ugc-quality-gate clip_check)
  -> 8 edit plan, 9 assembly         (video-assembly)
  -> 10 quality gate C1-C8           (ugc-quality-gate)
  -> 11 deliver final.mp4 + report
```

## Repository

| Folder | What it holds |
|---|---|
| `agent/` | The agent configuration (`agent_config.json`) and system prompt (`system_prompt.md`). |
| `skills/` | Seven skills, one folder each (`SKILL.md`, scripts, references). Deterministic work is done in scripts; judgement is left to the model. |
| `tools/ma_client.py` | Command-line client for the Managed Agents API: skills, agent updates, sessions, events and files. Standard library only. |
| `ui/` | The web app: FastAPI backend (`ui/server`) and Next.js frontend (`ui/web`). |
| `deploy/vefaas/` | Package and steps for hosting the web app on BytePlus veFaaS. |

### Skills

| Skill | Job |
|---|---|
| `ugc-video-analyzer` | Breaks the sample down into scenes, on-screen text, people, product moments, call to action and what not to copy (`analysis.json`). |
| `product-personalizer` | Opens the product page in headless Chromium, reads the personalization options, fills them in (photo, name, colours) and captures the live preview. It never adds to cart, checks out or logs in. |
| `generate-with-seedream` | Seedream 5.0 pro image generation and editing (AI people, first-frame stills). |
| `ugc-seedance-prompt-craft` | Writes one Seedance 2.5 prompt per clip and checks it against the Seedance rules. It also merges single-product edits into one still (`edit_merge.py`), so each product keeps its own name and artwork. |
| `generate-with-seedance` | Seedance 2.5 video tasks: 9:16, 480p, audio off. |
| `video-assembly` | Trims and joins the clips, adds captions in the client's style, the photo-to-product inset with an arrow, the end card and the AI disclaimer. Captions that copy the sample are refused. |
| `ugc-quality-gate` | An independent vision evaluator (`seed-2-0-lite`). `clip_check.py` checks each clip against the product (personalization, spelling, count, physics). `gate.py` scores the final ad on C1-C8 and routes each failure back to the step that fixes it. |

## Build it in your own BytePlus account

Region `ap-southeast-1`. API base `https://ark.ap-southeast.bytepluses.com/api/v3`. Auth `Authorization: Bearer $ARK_API_KEY`.

1. **Model access.** In the ModelArk console, enable the models used: GLM-5.3 Flash (`glm-5-3-flash-260828`, the agent), Seedream 5.0 pro (`seedream-5-0-pro-260628`), Seedance 2.5 (`seedance-2-5-260628`) and Seed 2.0 lite (`seed-2-0-lite-260428`, the evaluator). Create an API key.
2. **Environment.** Create a Managed Agents environment with nothing pre-installed. Each skill installs its own tools at run time (`scripts/ensure-deps.sh`), because installed packages do not carry over between sessions.
3. **Vault.** Create a vault with a credential exposed as the environment variable `ARK_API_KEY`, allowed host `ark.ap-southeast.bytepluses.com`. The skills call Seedream, Seedance and the evaluator with it.
4. **Skills.** Upload each skill folder:
   ```bash
   export ARK_API_KEY=...            # never write the key into a file
   python3 tools/ma_client.py skill create --dir skills/ugc-video-analyzer --title "UGC video analyzer"
   ```
   Repeat for the seven folders. To release a change later, run `skill upload --skill-id <id> --dir <folder>`.
5. **Agent.** Create an agent with model GLM-5.3 Flash and the built-in toolset (all tools allowed), as in `agent/agent_config.json`. Then set the prompt and the pinned skill versions:
   ```bash
   export MA_AGENT_ID=<agent id> MA_ENV_ID=<environment id> MA_VAULT_ID=<vault id>
   python3 tools/ma_client.py agent set-system --file agent/system_prompt.md
   python3 tools/ma_client.py agent set-skills --skill <skill_id>=<version> --skill ...
   ```
   A new skill version reaches the agent only after `set-skills`, and only in sessions started afterwards.
6. **Web app.**
   ```bash
   ui/start.sh            # http://localhost:3000
   ```
   It needs Python 3.9+ and Node 20+. Set `UI_BASIC_AUTH=user:password` to require a sign-in. To host it, follow `deploy/vefaas/README.md`.

## Inputs and limits worth knowing

- **Sample video.** It must be a direct HTTPS MP4 link that opens without signing in, or a file uploaded in the web app. TikTok and other social page links can't be downloaded from the sandbox.
- **Sandbox network.** Plain HTTP (port 80) is blocked and HTTPS works. The skills switch apt to an HTTPS mirror.
- **Seedance audio.** Seedance adds audio unless told not to, and generated audio can trigger copyright rejections. The skills always send `generate_audio: false`.
- **Seedream parameters.** Seedream 5.0 pro rejects `sequential_image_generation`, so the skills leave it out.
- **Several personalized products in one generation.** Models then mix names and artwork. The prompt-craft skill makes one edit per product and merges the edits.
- **Session file links.** Session files can be downloaded through the Files API with presigned links, which stop working after about a day. Keep the delivered files somewhere durable; for the hosted app, mount TOS storage (see `deploy/vefaas/README.md`).
- **Captions.** They are always rewritten, never copied from the sample. Offer lines are used word for word only when the client approved them.
