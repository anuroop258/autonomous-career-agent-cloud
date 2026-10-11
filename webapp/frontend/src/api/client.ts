// Thin fetch wrapper over the FastAPI backend in webapp/backend/main.py.
// Every function here maps 1:1 to a real endpoint -- no mock data.

// Where the API lives:
//  - Vite dev server (port 5175) or a file:// copy -> the local backend on 127.0.0.1:8001
//  - anything else (UI served by the backend itself, locally or through a tunnel) -> same origin
const DEV_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8001";
const BASE =
  typeof location !== "undefined" && (location.port === "5175" || location.protocol === "file:")
    ? DEV_BASE
    : "";

// ---- API key (only needed when the backend runs with CAREER_AGENT_API_KEY) ----
const KEY_NAME = "career-agent-key";
export const getApiKey = (): string => {
  try { return localStorage.getItem(KEY_NAME) || ""; } catch { return ""; }
};
export const setApiKey = (key: string) => {
  try { localStorage.setItem(KEY_NAME, key); } catch { /* storage unavailable */ }
};
export const clearApiKey = () => {
  try { localStorage.removeItem(KEY_NAME); } catch { /* storage unavailable */ }
};
export const AUTH_EVENT = "career-agent-auth-required";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const key = getApiKey();
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(key ? { "X-API-Key": key } : {}), ...(opts.headers || {}) },
  });
  if (res.status === 401 && path !== "/api/auth/check") {
    window.dispatchEvent(new Event(AUTH_EVENT));
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

const get = <T,>(path: string) => req<T>(path);
const post = <T,>(path: string, body?: unknown) =>
  req<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });

// ---- types (mirrors the backend's row shapes) ----------------------------
export interface Check { name: string; status: "OK" | "WARN" | "FAIL"; detail: string }
export interface StatusResponse { overall: string; checks: Check[]; run: string }
export interface PortalConfig { enabled: boolean; mode: string; max_per_day: number; cdp_port: number }
export interface ConfigResponse {
  candidate_id: string; db_path: string; allow_submit: boolean; max_retries: number;
  max_per_day: number; max_per_platform: number; titles: string[]; locations: string[];
  resume: { tailor: boolean; use_tailored_for_upload: boolean; master_resume_path: string | null;
    ai_rewrite: boolean; preserve_metrics: boolean; max_buzzwords: number };
  portals: Record<string, PortalConfig>;
  outreach: { enabled: boolean; mode: string; daily_cap: number; followup_days: number;
    max_followups: number; auto_recruiter_discovery: boolean; search_provider: string };
}
export interface DashboardSummary {
  generated_at: string; candidate_id: string; jobs_discovered: number;
  applications_total: number; applications_submitted: number; awaiting_approval: number;
  ready_for_manual_submit: number; rejections: number; interviews: number; pending_approvals: number;
  jobs: { total: number; discovered_today: number; discovered_week: number; discovered_month: number;
    applied_today: number; eligible: number; by_portal: { name: string; count: number }[];
    by_company: { name: string; count: number }[]; by_title: { name: string; count: number }[] };
  applications: { total: number; submitted: number; by_status: Record<string, number>;
    by_portal: { name: string; count: number; submitted: number }[];
    funnel: { stage: string; count: number }[] };
  outreach: { drafts: number; approved_unsent: number; sent: number; replied: number;
    response_rate: number; positive: number; negative: number; action_required: number;
    send_failed: number; pending_followups: number };
  top_jobs?: Job[];
  recent_applications?: Application[];
  needs_attention?: Application[];
}
export interface Job {
  id: number; job_ref: string; source: string; title: string; company: string; location: string;
  description: string; url: string; discovered_at: string; updated_at: string;
  match_score: number | null; eligible: 0 | 1 | null; matched_skills: string[] | null;
  missing_skills: string[] | null; application_id: number | null;
  application_platform: string | null; application_status: string | null;
  resume_version_id: number | null; resume_pdf_available?: boolean; application_route?: "native" | "external" | "unknown";
}
export interface Application {
  id: number; candidate_id: string; job_id: number; platform: string; status: string;
  resume_version_id: number | null; submitted_at: string | null; last_error: string | null;
  created_at: string; updated_at: string; title: string; company: string; location: string;
  url: string; source: string; eligible?: 0 | 1 | null; resume_pdf_available?: boolean; application_route?: "native" | "external" | "unknown";
}
export interface Approval {
  id: number; kind: "application" | "outreach"; ref_id: number; status: string;
  summary: string; note: string | null; requested_at: string; decided_at: string | null;
}
export interface Recruiter {
  id: number; company: string; name: string; title: string; email: string | null;
  profile_url: string | null; source: string; confidence: number; created_at: string;
}
export interface Outreach {
  id: number; job_id: number | null; recruiter_id: number | null; channel: string;
  subject: string; body: string; status: string; sent_at: string | null;
  follow_up_at: string | null; created_at: string; job_title: string | null;
  company: string | null; recruiter_name: string | null; recruiter_email: string | null;
}
export interface LogEvent {
  id: number; run_id: string | null; event_type: string; platform: string | null;
  job_id: number | null; application_id: number | null; payload_json: string | null;
  payload?: unknown; created_at: string;
}
export interface CdpStatus { [portal: string]: { port: number; connected: boolean } }
export interface AutomationStatus {
  status: "idle" | "queued" | "running" | "stopping"; portals: string[];
  started_at: number | string | null; pid: number | null; pids?: Record<string, number>;
  returncode: number | null; log_file?: string | null;
  runs?: Record<string, { status: string; task_id?: string; pid?: number | null; started_at?: number | string | null; requested_at?: string | null; returncode?: number | null; log_file?: string | null; log_tail?: string; error?: string | null; human_verification?: boolean }>;
  tasks?: Array<{ task_id: string; portal: string; status: string; requested_at?: string; started_at?: string | null; finished_at?: string | null; returncode?: number | null; error?: string | null }>;
  worker?: { worker_id?: string; error?: string; cdp?: Record<string, boolean> };
}
export interface CustomQA { id: number; question: string; answer: string; created_at: string; updated_at: string }

// ---- API surface -----------------------------------------------------------
export interface ResumeContentBank {
  schema_version: number;
  purpose: string;
  source_documents: Array<{ id: string; filename: string; type: string; focus: string[] }>;
  professional_summary_options: Array<{ id: string; text: string; source: string; tags: string[] }>;
  skill_options: Array<{ id: string; label: string; items: string[]; sources: string[] }>;
  keyword_options: Record<string, string[]>;
  project_options: Array<{
    id: string; title: string; year: number; tech_stack: string[]; source: string; tags: string[];
    keywords: string[]; bullets: string[]; metrics: string[];
  }>;
  certification_options: string[];
  selection_policy: Record<string, boolean>;
}

export const api = {
  health: () => get<{ ok: boolean }>("/api/health"),
  authStatus: () => get<{ auth_required: boolean }>("/api/auth/status"),
  authCheck: () => get<{ ok: boolean }>("/api/auth/check"),
  status: () => get<StatusResponse>("/api/status"),
  config: () => get<ConfigResponse>("/api/config"),

  cdpStatus: () => get<CdpStatus>("/api/cdp/status"),
  cdpTest: (portal: string) => post<{ portal: string; port: number; connected: boolean }>(`/api/cdp/test?portal=${portal}`),
  launchPortal: (portal: string) => post<{ ok: boolean; portal: string; port: number; url: string; already_running: boolean; profile_dir: string }>("/api/portal/launch", { portal }),

  dashboard: () => get<DashboardSummary>("/api/dashboard"),
  analytics: () => get<Record<string, unknown>>("/api/analytics"),
  needsAttention: () => get<Record<string, unknown>[]>("/api/dashboard/needs-attention"),

  jobs: (params: { portal?: string; eligible?: boolean; q?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.portal) qs.set("portal", params.portal);
    if (params.eligible !== undefined) qs.set("eligible", String(params.eligible));
    if (params.q) qs.set("q", params.q);
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    if (params.offset !== undefined) qs.set("offset", String(params.offset));
    return get<Job[]>(`/api/jobs?${qs.toString()}`);
  },
  job: (jobRef: string) => get<{ job: Job; matches: unknown[]; applications: Application[]; resume_versions: unknown[]; events: LogEvent[] }>(`/api/jobs/${encodeURIComponent(jobRef)}`),
  refreshJobMetadata: (jobRef: string) => post<{ updated: boolean; job_ref: string; message?: string; metadata?: Record<string, string> }>(`/api/jobs/${encodeURIComponent(jobRef)}/refresh-metadata`),
  tailorResume: (jobRef: string) => post<{
    version_id: number; tex_path: string; pdf_path: string | null; matched_skills: string[];
    compile_error: string | null; metrics_preserved: boolean; company: string; role: string; job_ref: string;
    tailoring_report?: {
      keyword_inventory_count?: number; phrase_inventory_count?: number;
      matched_keywords?: Array<{ keyword: string; in_resume: boolean; match_type?: string; exact_wording_used?: string }>;
      safe_additions?: Array<{ keyword: string; evidence: string; match_type?: string }>;
      unsupported_keywords?: Array<{ keyword: string; reason: string }>;
      added_keywords?: string[]; authenticity_flags?: Array<{ line: string; overlap: string; action: string }>;
      reordered_projects?: string[]; repeated_verb_fixes?: Array<{ from: string; to: string }>;
      repeated_verbs_flagged?: Array<{ verb: string; count: number }>;
      rewritten_bullets?: Array<{ project: string; bullet_index: number; keyword: string; change?: string; reason?: string; new_word_count?: number }>;
      quantification_gaps?: Array<{ project: string; bullet_index: number; reason: string }>;
      analysis_data_repetition_flags?: Array<{ project: string; bullet_index: number; text: string }>;
      second_pass_verified?: boolean; metrics_preserved?: boolean; preserved_metrics?: string[]; missing_metrics?: string[];
      verification?: { page_count?: number; one_page?: boolean; hyperlinks_checked?: boolean; hyperlink_count?: number; linkedin_url?: boolean; github_url?: boolean };
      bullet_word_counts?: number[];
      content_bank_options?: Array<{ type: string; id?: string; title: string; source: string; matched_signals?: string[]; text?: string }>;
      cv_check?: { total_keywords_checked?: number; exact_matches?: number; near_matches?: number; missing_matches?: number; coverage_percent?: number; status?: string };
      stronger_bullet_selections?: Array<{ project: string; bullet_index: number; reason?: string; metric_locks?: string[]; new_word_count?: number }>;
      metric_locks?: Record<string, string[]>;
      bullet_style_check?: { pass?: boolean; issues?: Array<{ project: string; bullet_index: number; issue: string; count?: number }> };
      prompt_spec?: string;
    };
  }>(`/api/jobs/${encodeURIComponent(jobRef)}/tailor-resume`),
  resumeFor: (jobRef: string) => get<Record<string, unknown>>(`/api/jobs/${encodeURIComponent(jobRef)}/resume`),
  resumePdfUrl: (jobRef: string) => {
    const key = getApiKey();
    return `${BASE}/api/jobs/${encodeURIComponent(jobRef)}/resume-file${key ? `?api_key=${encodeURIComponent(key)}` : ""}`;
  },
  masterResume: () => get<{ path: string; content: string }>("/api/resume/master"),

  resumeContentBank: () => get<ResumeContentBank>("/api/resume/content-bank"),

  applications: (status?: string, limit = 200, offset = 0) => {
    const qs = new URLSearchParams();
    if (status) qs.set("status", status);
    qs.set("limit", String(limit));
    qs.set("offset", String(offset));
    return get<Application[]>(`/api/applications?${qs.toString()}`);
  },
  application: (id: number) => get<{ application: Application; events: unknown[]; questions: unknown[] }>(`/api/applications/${id}`),
  markSubmitted: (id: number) => post<{ ok: boolean }>(`/api/applications/${id}/mark-submitted`),

  approvals: (kind?: string) => get<Approval[]>(`/api/approvals${kind ? `?kind=${kind}` : ""}`),
  approve: (id: number, note = "") => post<Approval>(`/api/approvals/${id}/approve`, { note }),
  reject: (id: number, note = "") => post<Approval>(`/api/approvals/${id}/reject`, { note }),

  recruiters: (company?: string) => get<Recruiter[]>(`/api/recruiters${company ? `?company=${company}` : ""}`),
  discoverRecruiters: (jobId?: number) => post<{ discovered: Record<string, unknown> }>(`/api/recruiters/discover${jobId ? `?job_id=${jobId}` : ""}`),

  outreachList: (status?: string) => get<Outreach[]>(`/api/outreach${status ? `?status=${status}` : ""}`),
  draftOutreach: (jobId: number, recruiterId: number) => post<Record<string, unknown>>("/api/outreach/draft", { job_id: jobId, recruiter_id: recruiterId }),
  sendOutreach: () => post<Record<string, number>>("/api/outreach/send"),
  markSentManually: (id: number) => post<{ ok: boolean }>(`/api/outreach/${id}/mark-sent-manually`),

  runFollowups: () => post<{ created: number[] }>("/api/followups/run"),

  startAutomation: (portals: string[]) => post<{ ok: boolean; started: { portal: string; task_id?: string; status?: string; pid?: number | null; already_running: boolean }[]; pids: Record<string, number>; portals: string[] }>("/api/automation/start", { portals }),
  stopAutomation: () => post<{ ok: boolean }>("/api/automation/stop"),
  continueIndeedHumanVerification: () => post<{ ok: boolean; message: string }>("/api/automation/indeed/continue"),
  automationStatus: () => get<AutomationStatus>("/api/automation/status"),

  logs: (params: { limit?: number; event_type?: string; platform?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.limit) qs.set("limit", String(params.limit));
    if (params.event_type) qs.set("event_type", params.event_type);
    if (params.platform) qs.set("platform", params.platform);
    return get<LogEvent[]>(`/api/logs?${qs.toString()}`);
  },
  rawLogs: (lines = 200) => get<{ files: string[]; tail: string[]; current_file?: string }>(`/api/logs/raw?lines=${lines}`),
  qaList: () => get<CustomQA[]>("/api/qa"),
  qaSave: (question: string, answer: string) => post<{ ok: boolean }>("/api/qa", { question, answer }),
  qaDelete: (id: number) => req<{ ok: boolean }>(`/api/qa/${id}`, { method: "DELETE" }),
};
