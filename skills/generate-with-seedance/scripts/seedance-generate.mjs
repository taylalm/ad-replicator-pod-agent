#!/usr/bin/env node

import { readFileSync, writeFileSync, mkdirSync, existsSync, statSync } from "node:fs";
import { extname, join } from "node:path";

const DEFAULT_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3";
const DEFAULT_VERSION = "2.5";

// Model IDs from the official ModelArk model list (docs.byteplus.com/en/docs/modelark/model-list).
const MODEL_BY_VERSION = {
  "2.5": "dreamina-seedance-2-5-260628",
  "2.0": "dreamina-seedance-2-0-260128",
  "2.0-fast": "dreamina-seedance-2-0-fast-260128",
  "2.0-mini": "dreamina-seedance-2-0-mini-260615",
  "1.5-pro": "seedance-1-5-pro-251215", // retiring; kept only for compatibility
};

// Output specs from the Seedance 2.5 tutorial capability table.
const SPECS = {
  "2.5": { duration: [4, 30], resolutions: ["480p", "720p", "1080p"], outputFormats: ["mp4", "mov"], draft: true },
  "2.0": { duration: [4, 15], resolutions: ["480p", "720p", "1080p", "4k"], outputFormats: ["mp4"], draft: false },
  "2.0-fast": { duration: [4, 15], resolutions: ["480p", "720p"], outputFormats: ["mp4"], draft: false },
  "2.0-mini": { duration: [4, 15], resolutions: ["480p", "720p"], outputFormats: ["mp4"], draft: false },
  "1.5-pro": { duration: [2, 12], resolutions: ["480p", "720p", "1080p"], outputFormats: ["mp4"], draft: false },
};

const RATIOS = ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "adaptive"];
const OMNI_TYPES = ["auto", "reference", "edit", "extend"];
const IMAGE_MIME = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp" };

function fail(message, code = 2, extra = {}) {
  console.error(JSON.stringify({ ok: false, error: message, ...extra }));
  process.exit(code);
}

function parseArgs(argv) {
  const out = { reference_images: [], reference_videos: [] };
  const flags = ["--confirmed", "--dry-run", "--no-wait", "--return-last-frame", "--generate-audio", "--watermark", "--draft", "--help"];
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (flags.includes(arg)) {
      out[arg.slice(2).replaceAll("-", "_")] = true;
      continue;
    }
    if (arg === "--no-watermark") {
      out.watermark = false;
      continue;
    }
    const value = argv[++i];
    if (value === undefined) fail(`Missing value for ${arg}`);
    if (["--image", "--reference-image"].includes(arg)) out.reference_images.push(value);
    else if (arg === "--reference-video") out.reference_videos.push(value);
    else if (arg.startsWith("--")) out[arg.slice(2).replaceAll("-", "_")] = value;
    else fail(`Unknown argument: ${arg}`);
  }
  return out;
}

function help() {
  console.log(`Usage:
  Submit: seedance-generate.mjs --confirmed --prompt TEXT [options]
  Poll:   seedance-generate.mjs --task-id ID [--download DIR]

Options:
  --version 2.5|2.0|2.0-fast|2.0-mini|1.5-pro   Default 2.5
  --model ID                 Explicit model or endpoint ID override
  --ratio RATIO              21:9, 16:9, 4:3, 1:1, 3:4, 9:16, adaptive (default 9:16)
  --duration SECONDS         2.5: 4-30 or -1 (model picks); 2.0 series: 4-15 or -1
  --resolution 480p|720p|1080p   Default 480p (testing)
  --first-frame IMG          First frame (forces ratio adaptive)
  --last-frame IMG
  --reference-image IMG      Repeat. HTTPS URL, data URL, or a local file path in the sandbox
  --image IMG                Alias for --reference-image
  --reference-video URL      Repeat. Public HTTPS URL only (4-30 s per video recommended)
  --omni-task-type auto|reference|edit|extend
  --output-format mp4|mov    mov is Seedance 2.5 only
  --draft                    Draft mode (Seedance 2.5 only)
  --generate-audio           Off unless set (the API default is ON)
  --seed INTEGER
  --watermark | --no-watermark
  --return-last-frame
  --download DIR             Save the finished video into DIR (URLs expire)
  --poll-interval SECONDS    Default 10
  --max-wait SECONDS         Default 900
  --no-wait
  --dry-run                  Print the request body without calling the API
  --confirmed                Required to submit a new (billable) task`);
}

const args = parseArgs(process.argv.slice(2));
if (args.help) {
  help();
  process.exit(0);
}

const baseUrl = (process.env.ARK_BASE_URL || DEFAULT_BASE_URL).replace(/\/$/, "");
const headers = () => ({ Authorization: `Bearer ${process.env.ARK_API_KEY}`, "Content-Type": "application/json" });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60_000);
  try {
    const response = await fetch(`${baseUrl}${path}`, { ...options, headers: headers(), signal: controller.signal });
    const text = await response.text();
    let payload;
    try { payload = JSON.parse(text); } catch { payload = { message: text.slice(0, 1000) }; }
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${JSON.stringify(payload)}`);
    return payload;
  } finally {
    clearTimeout(timeout);
  }
}

async function download(url, dir, name) {
  mkdirSync(dir, { recursive: true });
  const response = await fetch(url);
  if (!response.ok) throw new Error(`download HTTP ${response.status}`);
  const path = join(dir, name);
  writeFileSync(path, Buffer.from(await response.arrayBuffer()));
  return path;
}

async function poll(taskId) {
  const interval = Math.max(2, Number(args.poll_interval || 10));
  const maxWait = Math.max(interval, Number(args.max_wait || 900));
  if (!Number.isFinite(interval) || !Number.isFinite(maxWait)) fail("Polling values must be numbers");
  const deadline = Date.now() + maxWait * 1000;
  while (true) {
    let task;
    try { task = await request(`/contents/generations/tasks/${encodeURIComponent(taskId)}`); }
    catch (error) { fail(`Task query failed: ${error.message}`, 1, { task_id: taskId }); }
    if (["succeeded", "failed", "cancelled", "expired"].includes(task.status)) {
      const result = { ok: task.status === "succeeded", task_id: taskId, status: task.status, task };
      if (task.status === "succeeded" && args.download && task.content?.video_url) {
        try {
          const ext = (task.content.video_url.split("?")[0].match(/\.(mp4|mov)$/i) || [, "mp4"])[1];
          result.saved_video = await download(task.content.video_url, args.download, `${taskId}.${ext}`);
          if (task.content.last_frame_url) result.saved_last_frame = await download(task.content.last_frame_url, args.download, `${taskId}_last_frame.png`);
        } catch (error) {
          result.download_error = `${error.message}; the video URL is still in task.content and expires later`;
        }
      }
      console.log(JSON.stringify(result, null, 2));
      process.exit(task.status === "succeeded" ? 0 : 1);
    }
    if (Date.now() >= deadline) fail("Local wait limit reached; query this task ID later instead of creating a new task", 3, { task_id: taskId, status: task.status });
    await sleep(interval * 1000);
  }
}

if (args.task_id) {
  if (!process.env.ARK_API_KEY) fail("ARK_API_KEY is not available in the sandbox environment");
  await poll(args.task_id);
}
if (!args.prompt) fail("--prompt is required when creating a task");

const version = args.version || process.env.SEEDANCE_VERSION || DEFAULT_VERSION;
if (!MODEL_BY_VERSION[version]) fail(`--version must be one of ${Object.keys(MODEL_BY_VERSION).join(", ")}`);
const spec = SPECS[version];
const model = args.model || process.env.SEEDANCE_MODEL || MODEL_BY_VERSION[version];
let ratio = args.ratio || "9:16";
const duration = Number(args.duration ?? 5);
const resolution = args.resolution || "480p";

if (!RATIOS.includes(ratio)) fail(`--ratio must be one of ${RATIOS.join(", ")}`);
const [minDuration, maxDuration] = spec.duration;
if (!Number.isInteger(duration) || (duration !== -1 && (duration < minDuration || duration > maxDuration))) {
  fail(`--duration must be -1 or an integer from ${minDuration} to ${maxDuration} for version ${version}`);
}
if (!spec.resolutions.includes(resolution)) fail(`--resolution must be one of ${spec.resolutions.join(", ")} for version ${version}`);
if (args.output_format && !spec.outputFormats.includes(args.output_format)) fail(`--output-format must be one of ${spec.outputFormats.join(", ")} for version ${version}`);
if (args.draft && !spec.draft) fail("--draft is supported only by Seedance 2.5");
if (args.omni_task_type && !OMNI_TYPES.includes(args.omni_task_type)) fail(`--omni-task-type must be one of ${OMNI_TYPES.join(", ")}`);

function httpsUrl(value) {
  try { return new URL(value).protocol === "https:"; } catch { return false; }
}

// Images may be HTTPS URLs, data URLs, or local sandbox files (converted to data URLs).
function imageRef(value, name) {
  if (value === undefined) return undefined;
  if (httpsUrl(value)) return value;
  if (/^data:image\/[a-z+]+;base64,/i.test(value)) return value;
  if (existsSync(value) && statSync(value).isFile()) {
    const mime = IMAGE_MIME[extname(value).toLowerCase()];
    if (!mime) fail(`${name}: unsupported image type ${extname(value)} (use png, jpg, jpeg or webp)`);
    return `data:${mime};base64,${readFileSync(value).toString("base64")}`;
  }
  fail(`${name} must be an HTTPS URL, a data URL, or an existing local image file`);
}

const firstFrame = imageRef(args.first_frame, "--first-frame");
const lastFrame = imageRef(args.last_frame, "--last-frame");
const references = args.reference_images.map(value => imageRef(value, "--reference-image"));
for (const video of args.reference_videos) {
  if (!httpsUrl(video)) fail("--reference-video must be a public HTTPS URL");
}

// Task-type constraints from the Seedance 2.5 tutorial ("Read before use").
if (firstFrame && ratio !== "adaptive") {
  if (args.ratio) fail("First-frame / first-last-frame tasks require --ratio adaptive");
  ratio = "adaptive";
}
if (args.omni_task_type === "edit") {
  if (!args.reference_videos.length) fail("--omni-task-type edit needs at least one --reference-video");
  if (ratio !== "adaptive" || duration !== -1) fail("Video editing requires --ratio adaptive and --duration -1");
}
if (args.omni_task_type === "extend") {
  if (!args.reference_videos.length) fail("--omni-task-type extend needs at least one --reference-video");
  if (ratio !== "adaptive") fail("Video extension requires --ratio adaptive");
}

const body = {
  model,
  content: [
    { type: "text", text: args.prompt },
    ...(firstFrame ? [{ type: "image_url", image_url: { url: firstFrame }, role: "first_frame" }] : []),
    ...(lastFrame ? [{ type: "image_url", image_url: { url: lastFrame }, role: "last_frame" }] : []),
    ...references.map(url => ({ type: "image_url", image_url: { url }, role: "reference_image" })),
    ...args.reference_videos.map(url => ({ type: "video_url", video_url: { url }, role: "reference_video" })),
  ],
  ratio,
  duration,
  resolution,
  // Always explicit: the API defaults generate_audio to true, which can trigger audio copyright rejections.
  generate_audio: Boolean(args.generate_audio),
};
if (args.omni_task_type) body.omni_reference_task_type = args.omni_task_type;
if (args.output_format) body.output_format = args.output_format;
if (args.draft) body.draft = true;
if (args.return_last_frame) body.return_last_frame = true;
if (args.watermark !== undefined) body.watermark = args.watermark;
if (args.seed !== undefined) {
  const seed = Number(args.seed);
  if (!Number.isInteger(seed)) fail("--seed must be an integer");
  body.seed = seed;
}

if (args.dry_run) {
  const shown = JSON.parse(JSON.stringify(body));
  for (const item of shown.content) {
    if (item.image_url?.url?.startsWith("data:")) item.image_url.url = `${item.image_url.url.slice(0, 40)}...(${item.image_url.url.length} chars)`;
  }
  console.log(JSON.stringify({ ok: true, dry_run: true, request: shown }, null, 2));
  process.exit(0);
}
if (!args.confirmed) fail("Task submission requires confirmation; rerun with --confirmed");
if (!process.env.ARK_API_KEY) fail("ARK_API_KEY is not available in the sandbox environment");

let created;
try { created = await request("/contents/generations/tasks", { method: "POST", body: JSON.stringify(body) }); }
catch (error) { fail(`Task submission failed or result is uncertain; do not retry automatically: ${error.message}`, 1); }
const taskId = created.id;
if (!taskId) fail("Task submission response did not contain an id; result is uncertain, do not retry automatically", 1);
if (args.no_wait) {
  console.log(JSON.stringify({ ok: true, task_id: taskId, status: "submitted" }, null, 2));
  process.exit(0);
}
await poll(taskId);
