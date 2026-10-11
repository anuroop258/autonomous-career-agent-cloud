// Thin fetch wrapper over the FastAPI backend in webapp/backend/main.py.
// Every function here maps 1:1 to a real endpoint -- no mock data.

const configuredBase = import.meta.env.VITE_API_BASE;
// Local Vite development uses the local FastAPI server. Production uses same-origin API routes.
const BASE = configuredBase !== undefined
  ? configuredBase
  : (import.meta.env.DEV ? "http://127.0.0.1:8001" : "");
export const CLOUD_RUNNER_MODE = import.meta.env.PROD && !configuredBase;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers = new Headers({ "Content-Type": "application/json" });
  new Headers(opts.headers).forEach((value, key) => headers.set(key, value));
  const isResumeTailoringAction = String(opts.method || "GET").toUpperCase() === "POST"
    && /^\/api\/jobs\/[^/]+\/tailor-resume(?:\?|$)/.test(path);
  if (isResumeTailoringAction && !headers.has("X-Automation-Password")) {
    const password = typeof window !== "undefined"
      ? window.prompt("Enter your CareerAgent automation password to tailor this resume:")
      : null;
    if (!password) throw new ApiError(401, "Resume tailoring was cancelled because no automation password was provided.");
    headers.set("X-Automation-Password", password);
  }
  const res = await fetch(`${BASE}${path}`, { ...opts, headers });
  const contentType = res.headers.get("content-type") || "";
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    if (contentType.includes("application/json")) {
      try { const body = await res.json(); detail = body.detail || body.message || detail; } catch { /* invalid JSON */ }
    } else {
      detail = `API ${path} returned non-JSON content (HTTP ${res.status}). Check the API route and deployment.`;
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  if (!contentType.includes("application/json")) {
    throw new ApiError(res.status, `API ${path} returned HTML instead of JSON. The API route may be missing or not deployed.`);
  }
  return res.json();
}

const get = <T,>(path: string) => req<T>(path);
const post = <T,>(path: string, body?: unknown, headers?: Record<string, string>) =>
  req<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined, headers });

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
  status: "idle" | "running" | "stopping" | "queued" | "completed" | "failed" | "cancelled";
  portals: string[]; started_at: number | null; pid: number | null; pids?: Record<string, number>;
  returncode: number | null; log_file?: string | null; operation?: string | null; job_ref?: string | null;
  tasks?: CloudTask[];
  runs?: Record<string, { status: string; pid?: number; started_at?: number; returncode?: number | null; log_file?: string | null; human_verification?: boolean; task_id?: string; error?: string | null; max_jobs?: number }>;
}
export interface CloudTask { task_id: string; portal: string; max_jobs: number; status: string; requested_at: string; started_at?: string | null; finished_at?: string | null; error?: string | null; log_tail?: string; operation?: "job_search" | "tailor_resume"; job_ref?: string }
export interface CustomQA { id: number; question: string; answer: string; created_at: string; updated_at: string }

export interface Preferences { titles: string[]; locations: string[]; portals: string[]; min_match: number }
export interface PreferencesResponse {
  preferences: Preferences; agent_titles: string[]; saved: boolean; portals: string[];
  suggested_titles: { title: string; count: number }[]; known_locations: { name: string; count: number }[];
}
export interface GroupedJob extends Job { platform: string; status: string; title_clean: string; group: string }
export interface JobGroup { key: string; label: string; hint: string; count: number; jobs: GroupedJob[] }
export interface SegregatedJobs { total: number; groups: JobGroup[] }

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
  status: () => get<StatusResponse>("/api/status"),
  config: () => get<ConfigResponse>("/api/config"),

  cdpStatus: () => get<CdpStatus>("/api/cdp/status"),
  cdpTest: (portal: string) => post<{ portal: string; port: number; connected: boolean }>(`/api/cdp/test?portal=${portal}`),
  launchPortal: (portal: string, password?: string) => post<{ ok: boolean; portal: string; port: number; url: string; already_running: boolean; profile_dir: string }>("/api/portal/launch", { portal }, password ? { "X-Automation-Password": password } : undefined),

  dashboard: () => get<DashboardSummary>("/api/dashboard"),
  analytics: () => get<Record<string, unknown>>("/api/analytics"),
  needsAttention: () => get<Record<string, unknown>[]>("/api/dashboard/needs-attention"),

  preferences: () => get<PreferencesResponse>("/api/preferences"),
  savePreferences: (p: Preferences & { apply_to_agent?: boolean }) =>
    req<{ ok: boolean; preferences: Preferences; synced_to_agent: boolean }>("/api/preferences", { method: "PUT", body: JSON.stringify(p) }),
  searchJobs: (p: { titles: string[]; locations: string[]; portals: string[]; q?: string; min_match?: number; per_group?: number }) => {
    const qs = new URLSearchParams();
    p.titles.forEach((t) => qs.append("titles", t));
    p.locations.forEach((l) => qs.append("locations", l));
    p.portals.forEach((x) => qs.append("portals", x));
    if (p.q) qs.set("q", p.q);
    if (p.min_match) qs.set("min_match", String(p.min_match));
    qs.set("per_group", String(p.per_group ?? 500));
    return get<SegregatedJobs>(`/api/search/jobs?${qs.toString()}`);
  },

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
  resumePdfUrl: (jobRef: string) => `${BASE}/api/jobs/${encodeURIComponent(jobRef)}/resume-file`,
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

  startAutomation: (portals: string[], password?: string) => post<{ ok: boolean; started: { portal: string; pid: number; already_running: boolean }[]; pids: Record<string, number>; portals: string[] }>("/api/automation/start", { portals }, password ? { "X-Automation-Password": password } : undefined),
  startCloudAutomation: (portal: string, maxJobs: number, password: string) => post<{ ok: boolean; task_id: string; portal: string; max_jobs: number; status: string }>("/api/automation/start", { portal, max_jobs: maxJobs, confirmed: true }, { "X-Automation-Password": password }),
  stopCloudAutomation: (password: string) => post<{ ok: boolean; status?: string }>("/api/automation/stop", {}, { "X-Automation-Password": password }),
  stopAutomation: (password?: string) => post<{ ok: boolean }>("/api/automation/stop", {}, password ? { "X-Automation-Password": password } : undefined),
  continueIndeedHumanVerification: (password?: string) => post<{ ok: boolean; message: string }>("/api/automation/indeed/continue", {}, password ? { "X-Automation-Password": password } : undefined),
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
