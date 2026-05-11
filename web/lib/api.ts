const API = process.env.NEXT_PUBLIC_API_URL ?? "";
// SSE streams must bypass the Next.js proxy (which buffers responses).
// In local dev this goes directly to :8000; in production NEXT_PUBLIC_API_URL is set.
const STREAM_API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function authHeader(token?: string | null): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface UsageInfo {
  tier: "mini" | "pro";
  jobs_used: number;
  jobs_limit: number;
  reset_date: string;
}

export async function getVersion(): Promise<string> {
  try {
    const res = await fetch(`${API}/api/version`);
    if (!res.ok) return "";
    const data = await res.json();
    return data.version ?? "";
  } catch {
    return "";
  }
}

export async function getUsage(token?: string | null): Promise<UsageInfo> {
  const res = await fetch(`${API}/api/me/usage`, { headers: authHeader(token) });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface FigureInfo {
  index: number;
  url: string;
  page: number;
}

export interface VideoHistoryEntry {
  label: string;
  video_url: string;
  trigger: string | null;
  critic_score: number | null;
  mode?: string; // present when entry is a multi-mode comparison result
  failed?: boolean; // mode failed to render
}

export interface ConceptResult {
  index: number;
  name: string;
  visual_type: string;
  description: string | null;
  figure_url: string | null;
  figure_index: number | null;
  video_url: string | null;
  storyboard: string | null;
  critique_md: string | null;
  regen_status: string | null;
  history: VideoHistoryEntry[];
  subtitle_url: string | null;
  duration_ms: number | null;
}

export interface ConceptStub {
  index: number;
  name: string;
  visual_type: string;
  description?: string | null;
}

export interface JobState {
  job_id: string;
  status: JobStatus;
  pdf_name: string;
  options: Record<string, unknown>;
  progress: string[];
  concepts: ConceptResult[];
  concept_stubs: ConceptStub[];
  figures: FigureInfo[];
  graph_video_url: string | null;
  concept_edges: Array<{ from: number; to: number; label: string }> | null;
  awaiting_selection: boolean;
  novelty: { contribution: string; key_mechanism: string; prior_limitation: string; focus_keywords: string[] } | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ProgressEvent {
  type: string;
  message?: string;
  index?: number;
  name?: string;
  url?: string;
  page?: number;
  concepts?: Array<{ name: string; visual_type: string }>;
  stage?: string;
  content?: string;
  novelty?: { contribution: string; key_mechanism: string; prior_limitation: string; focus_keywords: string[] };
  // concept_stage fields
  status?: "running" | "done" | "error";
  detail?: string;
  attempt?: number;
  max_attempts?: number;
  score?: number;
  // mode key for per-mode event routing ("two_pass", "direct", "lean", etc.)
  mode?: string;
}

export async function submitJob(
  file: File,
  opts: { maxConcepts: number; quality: string; figureContext: boolean; parallelConcepts: number; maxRetries: number; voice: boolean; generationModes: string[]; conceptSelection: boolean; useRag: boolean; noveltyFocus: boolean; userHint: string; llmModel: string; codegenModel: string; criticModel: string },
  token?: string | null,
): Promise<JobState> {
  const form = new FormData();
  form.append("pdf", file);
  form.append("max_concepts", String(opts.maxConcepts));
  form.append("quality", opts.quality);
  form.append("figure_context", String(opts.figureContext));
  form.append("parallel_concepts", String(opts.parallelConcepts));
  form.append("max_retries", String(opts.maxRetries));
  form.append("voice", String(opts.voice));
  form.append("generation_mode", opts.generationModes.join(","));
  form.append("concept_selection", String(opts.conceptSelection));
  form.append("use_rag", String(opts.useRag));
  form.append("novelty_focus", String(opts.noveltyFocus));
  form.append("user_hint", opts.userHint);
  form.append("llm_model_override", opts.llmModel);
  form.append("codegen_model_override", opts.codegenModel);
  form.append("critic_model_override", opts.criticModel);

  const res = await fetch(`${API}/api/jobs`, { method: "POST", body: form, headers: authHeader(token) });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listJobs(token?: string | null): Promise<JobState[]> {
  const res = await fetch(`${API}/api/jobs`, { headers: authHeader(token) });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getJob(jobId: string, token?: string | null): Promise<JobState> {
  const res = await fetch(`${API}/api/jobs/${jobId}`, { headers: authHeader(token) });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function streamJob(
  jobId: string,
  onEvent: (e: ProgressEvent) => void,
  onDone: () => void,
  onError?: (msg: string) => void,
): () => void {
  const es = new EventSource(`${STREAM_API}/api/jobs/${jobId}/stream`);
  let terminated = false;
  es.onmessage = (ev) => {
    const data: ProgressEvent = JSON.parse(ev.data);
    onEvent(data);
    if (data.type === "done" || data.type === "error" || data.type === "cancelled") {
      terminated = true;
      es.close();
      onDone();
    }
  };
  es.onerror = () => {
    es.close();
    if (!terminated) {
      onError?.("Lost connection to server — refresh to see latest status.");
    }
    if (!terminated) onDone();
  };
  return () => es.close();
}

export async function regenerateConcept(
  jobId: string,
  conceptIndex: number,
  figureIndex: number,
  token?: string | null,
): Promise<void> {
  const res = await fetch(
    `${API}/api/jobs/${jobId}/concepts/${conceptIndex}/regenerate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeader(token) },
      body: JSON.stringify({ figure_index: figureIndex }),
    }
  );
  if (!res.ok) throw new Error(await res.text());
}

export async function selectConcepts(jobId: string, selectedIndices: number[], token?: string | null): Promise<void> {
  const res = await fetch(`${API}/api/jobs/${jobId}/select-concepts`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader(token) },
    body: JSON.stringify({ selected_indices: selectedIndices }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export interface TierConfig {
  llm_provider: string;
  llm_model: string;
  codegen_provider: string;
  codegen_model: string;
  max_concepts_limit: number;
  quality_limit: string;
  jobs_per_month: number;
}

export async function getAdminConfig(token?: string | null): Promise<Record<string, TierConfig>> {
  const res = await fetch(`${API}/api/admin/config`, { headers: authHeader(token) });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveAdminConfig(
  config: Record<string, Partial<TierConfig>>,
  token?: string | null,
): Promise<Record<string, TierConfig>> {
  const res = await fetch(`${API}/api/admin/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader(token) },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function cancelJob(jobId: string, token?: string | null): Promise<void> {
  const res = await fetch(`${API}/api/jobs/${jobId}/cancel`, { method: "POST", headers: authHeader(token) });
  if (!res.ok) throw new Error(await res.text());
}

export interface AdminUser {
  clerk_id: string;
  tier: string;
  created_at: string;
  job_count: number;
  email?: string;
  estimated_cost_usd?: number;
}

export interface AdminJobSummary {
  job_id: string;
  pdf_name: string;
  status: string;
  created_at: string;
  completed_at: string | null;
  options: Record<string, unknown>;
  concept_count: number;
}

export async function adminListUsers(secret: string): Promise<AdminUser[]> {
  const res = await fetch(`/api/admin/users`, { headers: { "x-admin-secret": secret } });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function adminListAllJobs(secret: string): Promise<AdminJobSummary[]> {
  const res = await fetch(`/api/admin/jobs`, { headers: { "x-admin-secret": secret } });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listAllJobs(token?: string | null): Promise<AdminJobSummary[]> {
  const res = await fetch(`${API}/api/admin/jobs`, { headers: authHeader(token) });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function adminListUserJobs(secret: string, clerkId: string): Promise<AdminJobSummary[]> {
  const res = await fetch(`/api/admin/users/${clerkId}/jobs`, { headers: { "x-admin-secret": secret } });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function fileUrl(path: string): string {
  if (path.startsWith("/api/")) return path; // served via Next.js rewrite proxy (same origin)
  return path;
}
