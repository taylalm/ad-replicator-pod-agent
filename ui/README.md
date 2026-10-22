# Ad Replicator web app

Start a run from a sample ad and a product page, approve the plan and each step, watch the 11 steps live, regenerate single clips, and review the final ad next to the sample.

## Start

```bash
export ARK_API_KEY=...        # read by the backend only; never sent to the browser
ui/start.sh                   # http://localhost:3000 (one process: web pages + API)
UI_DEV=1 ui/start.sh          # development: backend on :8787 + Next dev server on :3000
```

Requirements: Python 3.9+, Node 20+, macOS or Linux.

## Environment variables

| Variable | Meaning |
|---|---|
| `ARK_API_KEY` | ModelArk API key. Never logged, never in responses. |
| `MA_AGENT_ID`, `MA_ENV_ID`, `MA_VAULT_ID` | Your agent, environment and vault ids (see the main README). |
| `UI_BASIC_AUTH` | `user:password` to require a sign-in. `/api/health` stays open. |
| `UI_PORT` | Port, default 3000. |
| `UI_DATA_DIR` | Where jobs are stored, default `ui/data/jobs`. |
| `UI_DOWNLOAD_MAX_BYTES` | Files above this size are streamed from ModelArk storage instead of being copied (0 = copy everything). |
| `UI_SHOW_COST` | `1` shows the cost per video; it is hidden by default. |

## How it works

```
ui/server/   FastAPI backend
  main.py      API endpoints, file serving (HTTP Range), uploads, sign-in, static pages
  sync.py      one background thread per job: new events and session files from ModelArk
  derive.py    events + files -> what the pages show (steps, plan, clips, takes, reports)
  costs.py     production time and cost per video
  store.py     job folders
  compose.py   the labelled first message the agent reads
  validate.py  checks the sample link before a run starts
ui/web/      Next.js (static export) + TypeScript + Tailwind
```

The browser talks only to the backend. The backend holds the key and talks to the Managed Agents API through `tools/ma_client.py`. There is no database. Every job is an agent session whose title ends with `[job-...]`, and a new install rebuilds its job list from those sessions.

### Job folder

```
<job>/job.json      id, title, status, session id, inputs
<job>/events.json   the session's events, oldest first
<job>/files/        the session's output files
```

### Messages the web app sends to the agent

| Button | Message |
|---|---|
| Approve | `APPROVE` |
| Request changes | `CHANGES: <text>` |
| Regenerate a clip | `REGENERATE: clip <id> \| PROMPT: ...`, with an optional still prompt and references |
| Add a missing scene | `ADD CLIP: <text>` |
| Request a revision (after delivery) | `REVISION: <text>` |

### Replay

"Replay the run" plays a finished job back at 24x speed (`/job?id=<id>&replay=1&speed=24`). It pauses where the run waited for approval. Nothing is sent to the agent, so it costs nothing and changes nothing.
