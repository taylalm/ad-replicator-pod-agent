/** Typed client for the local backend (ui/server). The browser never sees the API key. */

// Same origin by default: next.config.ts forwards /api/* to the backend. NEXT_PUBLIC_API_BASE points elsewhere if needed.
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");

export type StepStatus = "pending" | "running" | "done" | "failed";
export type JobStatus = "queued" | "running" | "awaiting_approval" | "done" | "failed" | "stopped";

export interface Step {
  n: number;
  name: string;
  status: StepStatus;
  started_at: string | null;
  finished_at: string | null;
  elapsed_s: number | null;
  latest_message: string | null;
  reason: string | null;
  rounds: number;
}

export interface JobFile {
  name: string;
  kind: "image" | "video" | "json" | "md" | "other";
  step: number;
  size: number;
  mtime: number;
  local_url: string;
}

export interface Person { name: string; image: string; file: string }
export interface Product { name: string; image: string; file: string; artwork: string | null; person: string | null }
export interface ClipRef { id: string; kind?: string | null; file?: string | null; url?: string | null; describe?: string | null }
export interface Clip {
  id: string; n: number; file: string; url: string; size: number; scene?: number | string; duration_s?: number; summary?: string;
  mode?: string | null; prompt?: string | null; prompt_file?: string | null; still_prompt?: string | null;
  references?: ClipRef[]; still_references?: ClipRef[]; takes?: Array<{ file: string; url: string; mtime?: number }>;
  model?: string | null; drafts?: Draft[];
}
export interface SessionUpload { ok: boolean; path: string; filename: string; note?: string; file_id: string }
export interface Final { version: number; file: string; url: string; size: number; frames: string[] }
export interface Score { score: number | null; reason: string | null; evidence: string | null }
export interface HardFailure { kind: string; detail: string; evidence?: string }
export interface QualityRound {
  round: number;
  verdict: "PASS" | "FAIL" | string | null;
  summary: string | null;
  scores: Record<string, Score>;
  hard_failures: HardFailure[];
  routing: Array<Record<string, unknown>>;
  min_score: number | null;
  visible_text: string[];
  model: string | null;
  sheets: string[];
  file: string;
  md: string | null;
}
export interface JobError { kind: string; title: string; text: string; next: string; at: string | null; step?: number; code?: string | null
  resolved?: boolean;
}
export interface PaidCalls {
  seedream: number; seedance: number; evaluator: number; total: number;
  budget: { seedream: number; seedance: number; evaluator: number };
  entries: Array<{ step: number; kind: string; id: string | null; status: string | null; note: string | null }>;
}
export interface Usage { input_tokens: number; output_tokens: number; cache_read_input_tokens: number; cache_creation_input_tokens: number; model_requests: number; tool_calls: number }
export interface Budget { seedream: number; seedance: number; evaluator: number }
export interface Reference { file_id: string; filename: string; mount_name?: string; mime_type?: string | null; bytes?: number | null; note?: string; local_name?: string }
export interface PersonPrompt { name: string | null; file: string | null; prompt: string; model?: string | null; size?: string | null; version?: number | string | null; references?: string[] }
export interface ClipPrompt { id: string; file: string; prompt: string }
export interface Prompts { people: PersonPrompt[]; clips: ClipPrompt[] }
export interface JobInputs {
  sample_url?: string; product_url?: string; requirements?: string; budget?: Budget;
  options?: { length_s?: number | null; resolution?: string | null }; auto_approve?: boolean; step_approve?: boolean; message?: string;
}
export interface PlanScene { index: number; sample_scene?: number | string; clip?: string; length_s?: number; description?: string; caption?: string | null }
export interface PlanJson {
  product?: { name?: string; url?: string };
  cast?: Array<{ name: string; role?: string; look?: string; image?: string }>;
  product_options?: Record<string, string>;
  scenes?: PlanScene[];
  captions?: string[];
  end_card?: { product_name?: string; cta?: string; image?: string; price?: string | null };
  disclaimer?: string;
  do_not_copy?: string[];
  paid_call_estimate?: Partial<Budget>;
}
export interface AnalysisBrief {
  summary?: string; duration_s?: number; format?: string;
  hook?: { start?: number; end?: number; type?: string; text?: string; description?: string };
  scenes?: Array<{ index: number; start: number; end: number; shot?: string; description?: string; purpose?: string; personalization_visible?: string }>;
  on_screen_text?: unknown; do_not_copy?: string[];
}
export interface ReplayInfo { t: number; total_s?: number; approve_at_s?: number | null; done_at_s?: number | null }

export interface Job {
  id: string;
  title: string;
  created_at: string;
  demo: boolean;
  read_only?: boolean;
  session_id: string | null;
  inputs: JobInputs;
  status: JobStatus;
  awaiting_approval: boolean;
  awaiting_step?: number | null;
  prompts?: Prompts;
  session_phase: string;
  steps: Step[];
  current_step: number | null;
  plan_text: string | null;
  paid_calls: PaidCalls;
  files: JobFile[];
  errors: JobError[];
  usage: Usage;
  elapsed_s: number | null;
  sample_url: string | null;
  last_agent_message: string | null;
  thumbnail: string | null;
  n_events: number;
  n_events_total: number;
  people: Person[];
  products: Product[];
  clips: Clip[];
  finals: Final[];
  final_url: string | null;
  agent_final_url?: string | null;
  edits?: { version: number; file: string; url: string; thumb?: string | null; clean?: string | null }[];
  quality: QualityRound[];
  analysis: AnalysisBrief | null;
  plan: PlanJson | null;
  product: Record<string, unknown> | null;
  keyframes: string[];
  scene_frames: string[];
  replay?: ReplayInfo;
  syncing?: boolean;
  production?: Production | null;
}
export interface Production {
  production_s: number; steps: Array<{ n: number; active_s: number }>; waiting_s?: number | null;
  // price fields are absent when the backend runs with UI_SHOW_COST=0
  cost_per_video_usd?: number; cost_total_usd?: number; per_video?: Record<string, number>;
  video_clips?: Array<{ clip: string; tokens: number; usd: number; how: string }>; notes?: string[];
  prices?: { source: string };
}

export interface JobRow {
  id: string; title: string; created_at: string | null; demo: boolean; read_only?: boolean; status: JobStatus; thumbnail: string | null;
  current_step: number | null; product_url?: string; elapsed_s?: number | null; verdict?: string | null; paid_total?: number; error?: string;
  production_s?: number | null; cost_per_video_usd?: number | null;
}

export interface RawEvent {
  id: string; type: string; processed_at?: string; index: number; text?: string; name?: string; input_brief?: string;
  input?: Record<string, unknown>; is_error?: boolean; tool_use_id?: string; stop_reason?: { type: string };
  model_usage?: Record<string, number>; error?: unknown;
}

export interface ValidateResult { ok: boolean; reason: string | null; content_type: string | null; size_bytes: number | null; status?: number | null }

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers: { "content-type": "application/json", ...(init?.headers || {}) }, cache: "no-store" });
  } catch {
    throw new ApiError(0, "backend unreachable");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? body);
    } catch { /* keep statusText */ }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

// Gateways cap request bodies (API Gateway: 16 MB), so larger files go up in pieces the server joins again.
const CHUNK_OVER = 12 * 1024 * 1024;
const CHUNK_SIZE = 8 * 1024 * 1024;

async function postForm<T>(path: string, fd: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "POST", body: fd });
  if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({})))?.detail || `Upload failed (${res.status})`);
  return (await res.json()) as T;
}

async function sendFile<T>(path: string, file: File, note: string, jobId?: string): Promise<T> {
  if (file.size <= CHUNK_OVER) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("note", note);
    return postForm<T>(path, fd);
  }
  const total = Math.ceil(file.size / CHUNK_SIZE);
  const uploadId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  let last: unknown = null;
  for (let i = 0; i < total; i++) {
    const fd = new FormData();
    fd.append("chunk", file.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE), file.name);
    fd.append("upload_id", uploadId);
    fd.append("index", String(i));
    fd.append("total", String(total));
    fd.append("filename", file.name);
    fd.append("note", note);
    if (jobId) fd.append("job_id", jobId);
    last = await postForm<unknown>("/api/uploads/chunk", fd);
  }
  return last as T;
}

export const api = {
  health: () => request<{ ok: boolean; api_key_present: boolean; demo_jobs: string[] }>("/api/health"),
  jobs: () => request<{ jobs: JobRow[]; live_running: boolean }>("/api/jobs"),
  parts: (id: string) => request<{ parts: Array<{ group: string; name: string; url: string }> }>(`/api/jobs/${encodeURIComponent(id)}/parts`),
  job: (id: string, replayT?: number | null) =>
    request<Job>(`/api/jobs/${encodeURIComponent(id)}${replayT != null ? `?replay_t=${replayT}` : ""}`),
  events: (id: string, after: number, replayT?: number | null) =>
    request<{ events: RawEvent[]; total: number; next: number; has_more: boolean }>(
      `/api/jobs/${encodeURIComponent(id)}/events?after=${after}${replayT != null ? `&replay_t=${replayT}` : ""}`),
  validateSample: (url: string) => request<ValidateResult>("/api/validate-sample", { method: "POST", body: JSON.stringify({ url }) }),
  createJob: (body: {
    title?: string; sample_url: string; sample_upload?: { file_id: string; filename: string; local_name?: string } | null; product_url: string; requirements: string; budget: Budget;
    options: { length_s: number; resolution: string; captions?: "full" | "cta_only" | "none"; video_model?: string; image_model?: string }; auto_approve: boolean; step_approve?: boolean; references?: Reference[];
  }) => request<Job>("/api/jobs", { method: "POST", body: JSON.stringify(body) }),
  uploadReference: (file: File, note: string): Promise<Reference> => sendFile("/api/uploads", file, note),
  uploadToJob: (id: string, file: File, note: string): Promise<SessionUpload> =>
    sendFile(`/api/jobs/${encodeURIComponent(id)}/references`, file, note, id),
  renameJob: (id: string, title: string) =>
    request<{ ok: boolean; title: string; warning?: string }>(`/api/jobs/${encodeURIComponent(id)}/rename`, { method: "POST", body: JSON.stringify({ title }) }),
  deleteJob: (id: string) => request<{ ok: boolean; deleted: string }>(`/api/jobs/${encodeURIComponent(id)}`, { method: "DELETE" }),
  message: (id: string, text: string) =>
    request<{ ok: boolean; demo?: boolean }>(`/api/jobs/${encodeURIComponent(id)}/message`, { method: "POST", body: JSON.stringify({ text }) }),
};

export type Animation = { in?: string; out?: string; in_s?: number; out_s?: number };
export type CaptionItem = { id: string; text: string; start: number; end: number; style: string; position: number; x: number; enabled: boolean; animation?: Animation; approved_wording?: boolean };
export type InsetItem = { id: string; image: string; start: number; end: number; position: string; top: number; left?: number | null; width: number; arrow_to?: [number, number] | null; enabled: boolean };
export type CaptionDoc = {
  version: number; size: [number, number]; fps: number; base: string | null; captions: CaptionItem[]; insets: InsetItem[];
  reference_captions: string[]; outro_start: number | null; styles?: string[]; animations_in?: string[]; animations_out?: string[];
};
export type ExportState = { state: "idle" | "running" | "done" | "failed"; file?: string | null; error?: string | null; warnings?: string[] };

export const captionsApi = {
  get: (id: string) => request<{ doc: CaptionDoc; base_url: string | null; edits: { name: string; url: string }[]; export: ExportState | null; read_only: boolean }>(
    `/api/jobs/${encodeURIComponent(id)}/captions`),
  save: (id: string, doc: CaptionDoc) => request<{ ok: boolean; doc: CaptionDoc }>(`/api/jobs/${encodeURIComponent(id)}/captions`, { method: "PUT", body: JSON.stringify({ doc }) }),
  export: (id: string, doc: CaptionDoc) => request<ExportState>(`/api/jobs/${encodeURIComponent(id)}/captions/export`, { method: "POST", body: JSON.stringify({ doc }) }),
  status: (id: string) => request<ExportState>(`/api/jobs/${encodeURIComponent(id)}/captions/export`),
  /** A full-frame transparent PNG of one caption or inset, and its grab box [x0, y0, x1, y1] as fractions of the frame. */
  preview: async (id: string, kind: "caption" | "inset", item: object): Promise<{ url: string; box: number[] }> => {
    const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(id)}/captions/preview`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ kind, item }),
    });
    if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({})))?.detail || res.statusText);
    const box = (res.headers.get("X-Box") || "0,0,0,0").split(",").map(Number);
    return { url: URL.createObjectURL(await res.blob()), box };
  },
};

export type GenInput = { file?: string; asset?: string; role: "first_frame" | "reference" };
export type GenCheck = { verdict?: string | null; summary?: string | null; payoff_window?: number[] | null; issues?: { kind: string; detail: string; fix?: string }[] };
export type WebTake = { n: number; kind: "still" | "clip"; clip: string; file: string; model: string; prompt: string; inputs: GenInput[]; check?: GenCheck; accepted: boolean; created: string };
export type GenRun = { state: "running" | "done" | "failed"; kind: "still" | "clip"; clip: string; file?: string | null; error?: string | null; step?: string; check?: GenCheck };
export type Draft = { target?: string; prompt?: string; still_prompt?: string | null; first_frame?: string | null; inputs?: { tag?: string; file: string; role?: string }[]; model?: string; duration?: number; changes?: string[]; warnings?: string[]; file: string };

export const genApi = {
  status: (id: string) => request<{ run: GenRun | null; takes: WebTake[]; models: { video: Record<string, string>; image: Record<string, string> } }>(`/api/jobs/${encodeURIComponent(id)}/generate`),
  generate: (id: string, body: { kind: "still" | "clip"; clip: string; prompt: string; inputs: GenInput[]; model?: string; duration?: number; resolution?: string; audio?: boolean; payoff?: string }) =>
    request<GenRun>(`/api/jobs/${encodeURIComponent(id)}/generate`, { method: "POST", body: JSON.stringify(body) }),
  accept: (id: string, file: string) => request<{ ok: boolean; rebuild?: ExportState | null }>(`/api/jobs/${encodeURIComponent(id)}/takes/accept`, { method: "POST", body: JSON.stringify({ file }) }),
  rebuild: (id: string) => request<ExportState>(`/api/jobs/${encodeURIComponent(id)}/rebuild`, { method: "POST" }),
  draft: (id: string, body: { clip: string; target: string; feedback: string; model?: string; attachments: { path: string; note?: string }[] }) =>
    request<{ ok: boolean; sent: string }>(`/api/jobs/${encodeURIComponent(id)}/draft`, { method: "POST", body: JSON.stringify(body) }),
};

export function fileUrl(localUrl: string | null | undefined): string {
  if (!localUrl) return "";
  if (/^https?:\/\//.test(localUrl)) return localUrl;
  return `${API_BASE}${localUrl}`;
}
