#!/usr/bin/env node

import { readFileSync, writeFileSync, mkdirSync, existsSync, statSync } from "node:fs";
import { extname, join } from "node:path";

const DEFAULT_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3";
const DEFAULT_VERSION = "5.0-pro";

// Model IDs from the official ModelArk model list (docs.byteplus.com/en/docs/modelark/model-list).
const MODEL_BY_VERSION = {
  "5.0-pro": "dola-seedream-5-0-pro-260628",
  "5.0-flash": "dola-seedream-5-0-flash-260915",
  "5.0": "seedream-5-0-260128",
  "5.0-lite": "seedream-5-0-lite-260128",
  "4.5": "seedream-4-5-251128",
  "4.0": "seedream-4-0-250828",
};
// Seedream 5.0 pro / flash tutorial: resolution 1K, 1.5K, 2K; output format png, jpeg.
const PRO_FLASH_SIZES = ["1K", "1.5K", "2K"];
const OUTPUT_FORMAT_VERSIONS = ["5.0-pro", "5.0-flash", "5.0", "5.0-lite"];
const IMAGE_MIME = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp" };

function fail(message, code = 2) {
  console.error(JSON.stringify({ ok: false, error: message }));
  process.exit(code);
}

function parseArgs(argv) {
  const out = { images: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (["--confirmed", "--dry-run", "--watermark", "--help"].includes(arg)) {
      out[arg.slice(2).replaceAll("-", "_")] = true;
      continue;
    }
    if (arg === "--no-watermark") {
      out.watermark = false;
      continue;
    }
    const value = argv[++i];
    if (value === undefined) fail(`Missing value for ${arg}`);
    if (arg === "--image") out.images.push(value);
    else if (arg.startsWith("--")) out[arg.slice(2).replaceAll("-", "_")] = value;
    else fail(`Unknown argument: ${arg}`);
  }
  return out;
}

function help() {
  console.log(`Usage: seedream-generate.mjs --confirmed --prompt TEXT [options]

Options:
  --version 5.0-pro|5.0-flash|5.0|5.0-lite|4.5|4.0   Default 5.0-pro
  --model ID               Explicit model or endpoint ID
  --size SIZE              5.0-pro/flash: 1K, 1.5K, 2K (default 1K)
  --image IMG              Repeat. HTTPS URL, data URL, or a local image file in the sandbox
  --seed INTEGER
  --sequential auto|disabled  Not for 5.0-pro/flash (API rejects it). Omitted unless set
  --max-images 1-15        Used with sequential auto
  --response-format url|b64_json
  --output-format png|jpeg Seedream 5.0 family only
  --download DIR           Save every output image into DIR (URLs expire after 24 hours)
  --name PREFIX            File name prefix for --download (default: image)
  --watermark | --no-watermark   Default: no watermark
  --dry-run                Print sanitized request without calling API
  --confirmed              Required for a billable generation request`);
}

const args = parseArgs(process.argv.slice(2));
if (args.help) {
  help();
  process.exit(0);
}
if (!args.prompt) fail("--prompt is required");

const version = args.version || process.env.SEEDREAM_VERSION || DEFAULT_VERSION;
if (!MODEL_BY_VERSION[version]) fail(`--version must be one of ${Object.keys(MODEL_BY_VERSION).join(", ")}`);

function imageRef(value) {
  try { if (new URL(value).protocol === "https:") return value; } catch {}
  if (/^data:image\/[a-z+]+;base64,/i.test(value)) return value;
  if (existsSync(value) && statSync(value).isFile()) {
    const mime = IMAGE_MIME[extname(value).toLowerCase()];
    if (!mime) fail(`--image: unsupported image type ${extname(value)} (use png, jpg, jpeg or webp)`);
    return `data:${mime};base64,${readFileSync(value).toString("base64")}`;
  }
  fail("--image must be an HTTPS URL, a data URL, or an existing local image file");
}

const warnings = [];
const body = {
  model: args.model || process.env.SEEDREAM_MODEL || MODEL_BY_VERSION[version],
  prompt: args.prompt,
  size: args.size || "1K",
  response_format: args.response_format || "url",
  // Default off: generated images are reused as references and personalizer uploads, where a visible mark would carry over.
  watermark: args.watermark ?? false,
};
if (["5.0-pro", "5.0-flash"].includes(version) && !PRO_FLASH_SIZES.includes(body.size)) {
  fail(`--size must be one of ${PRO_FLASH_SIZES.join(", ")} for ${version}`);
}
if (args.images.length) body.image = args.images.length === 1 ? imageRef(args.images[0]) : args.images.map(imageRef);
if (args.seed !== undefined) {
  const seed = Number(args.seed);
  if (!Number.isInteger(seed)) fail("--seed must be an integer");
  body.seed = seed;
}
// Only send sequential_image_generation when explicitly requested: dola-seedream-5-0-pro-260628 rejects the
// parameter entirely (400 InvalidParameter "not supported by the current model"), even with "disabled".
if (args.sequential !== undefined) {
  if (["5.0-pro", "5.0-flash"].includes(version)) fail(`--sequential is not supported by ${version}; make one call per image`);
  if (!["auto", "disabled"].includes(args.sequential)) fail("--sequential must be auto or disabled");
  body.sequential_image_generation = args.sequential;
}
if (!["url", "b64_json"].includes(body.response_format)) fail("--response-format must be url or b64_json");
if (args.max_images !== undefined) {
  const maxImages = Number(args.max_images);
  if (!Number.isInteger(maxImages) || maxImages < 1 || maxImages > 15) fail("--max-images must be an integer from 1 to 15");
  if (body.sequential_image_generation !== "auto") fail("--max-images requires --sequential auto");
  body.sequential_image_generation_options = { max_images: maxImages };
}
if (args.output_format !== undefined) {
  if (!OUTPUT_FORMAT_VERSIONS.includes(version)) fail("--output-format is supported only by the Seedream 5.0 family");
  if (!["png", "jpeg"].includes(args.output_format)) fail("--output-format must be png or jpeg");
  body.output_format = args.output_format;
}

if (args.dry_run) {
  const shown = JSON.parse(JSON.stringify(body));
  const trim = v => (typeof v === "string" && v.startsWith("data:") ? `${v.slice(0, 40)}...(${v.length} chars)` : v);
  if (shown.image) shown.image = Array.isArray(shown.image) ? shown.image.map(trim) : trim(shown.image);
  console.log(JSON.stringify({ ok: true, dry_run: true, request: shown, warnings }, null, 2));
  process.exit(0);
}
if (!args.confirmed) fail("Generation requires confirmation; rerun with --confirmed");
if (!process.env.ARK_API_KEY) fail("ARK_API_KEY is not available in the sandbox environment");

const baseUrl = (process.env.ARK_BASE_URL || DEFAULT_BASE_URL).replace(/\/$/, "");
const controller = new AbortController();
const timeout = setTimeout(() => controller.abort(), 180_000);
try {
  const response = await fetch(`${baseUrl}/images/generations`, {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.ARK_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: controller.signal,
  });
  const text = await response.text();
  let payload;
  try { payload = JSON.parse(text); } catch { payload = { message: text.slice(0, 1000) }; }
  if (!response.ok) fail(`Seedream API ${response.status}: ${JSON.stringify(payload)}`, 1);
  const data = payload.data || [];
  const saved = [];
  if (args.download) {
    mkdirSync(args.download, { recursive: true });
    for (const [i, item] of data.entries()) {
      const ext = item.output_format === "jpeg" ? "jpg" : "png";
      const path = join(args.download, `${args.name || "image"}${data.length > 1 ? `_${i + 1}` : ""}.${ext}`);
      try {
        if (item.b64_json) writeFileSync(path, Buffer.from(item.b64_json, "base64"));
        else if (item.url) {
          const r = await fetch(item.url);
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          writeFileSync(path, Buffer.from(await r.arrayBuffer()));
        }
        saved.push(path);
      } catch (error) {
        warnings.push(`Download of output ${i + 1} failed: ${error.message}`);
      }
    }
  }
  console.log(JSON.stringify({ ok: true, model: payload.model || body.model, created: payload.created, data, saved, usage: payload.usage, warnings }, null, 2));
} catch (error) {
  fail(error.name === "AbortError" ? "Seedream request timed out; result is uncertain, do not retry automatically" : `Seedream request failed: ${error.message}`, 1);
} finally {
  clearTimeout(timeout);
}
