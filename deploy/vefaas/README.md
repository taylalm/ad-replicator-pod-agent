# Deploy the Ad Replicator UI on BytePlus veFaaS

This follows the "Enterprise AI Agent Implementation Guide with MCP and ModelArk Managed Agents" (veFaaS Web Application function behind an API Gateway trigger). The package is one Python service: it serves the web pages and the API on port 8000. The ModelArk API key stays on the server and never reaches the browser.

## What you upload

`deploy/vefaas/dist/ad-replicator-vefaas.zip` (about 110 MB, half of it the two showcase jobs; the console accepts up to 1024 MiB, but large browser uploads can stall, so keep it small). Rebuild it any time with:

```bash
bash deploy/vefaas/build_package.sh
```

It contains `run.sh`, the backend, the built web pages, the recorded demo run, read-only copies of the delivered jobs, and Python dependencies for Linux x86_64 and Python 3.11. Nothing needs installing on the function.

## Console steps (BytePlus console, region ap-southeast-1)

1. **veFaaS, create a function.**
   - Type: Web Application. Runtime: Native Python 3.11.
   - Startup command: `bash run.sh`. Do not chmod anything: the code directory is read-only.
   - Listening port: `8000`.
   - Execution timeout: the maximum allowed (at least 300 s). Large MP4 uploads go to ModelArk inside one request.
   - Memory: 1 GB is enough.
   - Instances: set the maximum to **1** if the console allows it. Each instance keeps its own cache and syncs the jobs on its own.
2. **Environment variables:**

   | Name | Value |
   |---|---|
   | `ARK_API_KEY` | The ModelArk API key the agent runs with (the same key as today). |
   | `UI_BASIC_AUTH` | `<username>:<password>` for the sign-in prompt you share with the client. Leaving it empty makes the site public: don't. |
   | `UI_DOWNLOAD_MAX_BYTES` | Optional, default `600000`. Files larger than this are streamed from ModelArk storage instead of being copied to the instance. |

3. **Upload the ZIP and click Release.**
4. **API Gateway trigger.**
   - Create an API Gateway trigger for the function, with route path `/`.
   - In the gateway's plugin list, raise **Rate Limiting** to 100 QPS or more. The default of about 1 QPS per replica returns HTTP 429 as soon as a page loads its scripts and thumbnails.
   - The MCP Session Affinity plugin from the guide is not needed: this is a plain web app, not an MCP server.
5. **Copy the public URL** (`https://xxx.apigateway-ap-southeast-1.apigw-byteplus.com/`) and open it. The browser asks for the username and password.

## Checks after release

| Check | Expected |
|---|---|
| `https://<url>/api/health` | `{"ok": true, "api_key_present": true, ...}`, with no sign-in needed |
| `https://<url>/` | A sign-in prompt, then "Your videos" |
| "Your videos" | Every job started from this UI. The list is rebuilt from the agent sessions, so the cloud copy sees the same jobs as the Mac. |
| A job page | Final video and clips play. Big files stream straight from ModelArk storage. |
| New video, Upload a file | An MP4 uploads and the job starts |

## How it behaves on serverless

- **No database.**
  - Every job lives in its ModelArk agent session; its title ends with `[job-...]`.
  - On a fresh instance, the job list, events and files are rebuilt from ModelArk into `/tmp`.
  - The first open of a big job takes a minute or two.
- **Syncing:** progress updates while someone has the page open. When no one is watching, an idle instance may pause; it catches up on the next visit.
- **File lifetime:**
  - ModelArk lists session files with a 7-day `expire_at`, but in practice they stop downloading after about **one day** (tested 22 Oct 2026).
  - The package therefore ships read-only "showcase" copies of finished jobs from `ui/data/jobs` (list in `SHOWCASE_JOBS` in `build_package.sh`).
  - Discovery skips sessions created before the package was built (`UI_DISCOVER_AFTER`).
  - New jobs made on the cloud site keep their videos for about a day. To keep them longer, enable **Storage** in the function settings: mount a TOS bucket, for example at `/mnt/data`, then set `UI_DATA_DIR=/mnt/data/jobs` and `UI_DOWNLOAD_MAX_BYTES=0` so the instance copies every file into the bucket.
- **Large uploads:** the API Gateway may limit request size. If a large MP4 fails to upload, use the "Paste a link" option with a TOS link instead.

## Updating the code later

1. Rebuild the ZIP.
2. On the function page, open the **Code** tab, upload the new ZIP, and **Release**.
3. Environment variables stay as they are.
