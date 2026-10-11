export const PORTALS = ["naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"];

export function json(data, status = 200, headers = {}) {
  return Response.json(data, { status, headers: { "Cache-Control": "no-store", ...headers } });
}

export function notConfigured(message = "Cloud database is not configured") {
  return json({ detail: message }, 503);
}

export function parseArray(value) {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string" || !value) return [];
  try { const parsed = JSON.parse(value); return Array.isArray(parsed) ? parsed : []; } catch { return []; }
}

export function mapJob(row) {
  if (!row) return row;
  const score = row.match_score == null ? null : Number(row.match_score);
  return {
    ...row,
    id: Number(row.id),
    match_score: Number.isFinite(score) ? score : null,
    eligible: row.eligible == null ? null : Number(row.eligible),
    matched_skills: parseArray(row.matched_skills),
    missing_skills: parseArray(row.missing_skills),
    resume_version_id: row.resume_version_id == null ? null : Number(row.resume_version_id),
    resume_pdf_available: Boolean(row.resume_pdf_available),
    application_id: row.application_id == null ? null : Number(row.application_id),
    source: row.source || row.platform || "unknown",
    url: row.url || "",
    application_platform: row.application_platform || row.platform || null,
    application_status: row.application_status || row.status || null,
    application_route: row.application_route || routeFromStatus(row.status),
  };
}

export function mapApplication(row) {
  if (!row) return row;
  return {
    ...row,
    id: Number(row.id),
    job_id: Number(row.job_id ?? row.id),
    resume_version_id: row.resume_version_id == null ? null : Number(row.resume_version_id),
    eligible: row.eligible == null ? null : Number(row.eligible),
    resume_pdf_available: Boolean(row.resume_pdf_available),
    application_route: row.application_route || routeFromStatus(row.status),
    url: row.url || "",
    source: row.source || row.platform || "unknown",
  };
}

export function routeFromStatus(status) {
  const s = String(status || "").toLowerCase();
  if (s.startsWith("external")) return "external";
  if (["apply_clicked", "applying", "application_ready", "awaiting_approval", "ready_for_manual_submit", "ready_to_submit", "submitted", "confirmed", "applied", "blocked", "human_intervention", "unknown_question", "no_questions", "answer_not_verified", "resume_upload_failed", "submission_unconfirmed", "submit_not_found", "naukri_apply_error", "application_error", "apply_click_failed", "apply_not_found", "match_found_no_direct_apply"].includes(s)) return "native";
  return "unknown";
}

export async function allRows(db, sql, ...bindings) {
  const stmt = db.prepare(sql);
  const bound = bindings.length ? stmt.bind(...bindings) : stmt;
  const result = await bound.all();
  return result.results || [];
}

export async function firstRow(db, sql, ...bindings) {
  const stmt = db.prepare(sql);
  return bindings.length ? stmt.bind(...bindings).first() : stmt.first();
}

export function cleanLimit(value, fallback = 200, max = 500) {
  const n = Number.parseInt(String(value ?? fallback), 10);
  return Number.isFinite(n) ? Math.max(1, Math.min(max, n)) : fallback;
}

export function emptyConfig() {
  const portals = {};
  for (const portal of PORTALS) {
    portals[portal] = { enabled: true, mode: "cloud-runner", max_per_day: 20, cdp_port: portal === "linkedin" ? 9232 : 9222 };
  }
  return {
    candidate_id: "CareerAgent", db_path: "Cloudflare D1", allow_submit: false, max_retries: 0,
    max_per_day: 20, max_per_platform: 20,
    titles: ["GenAI Engineer", "Generative AI Engineer", "AI Engineer", "AI/ML Engineer", "Machine Learning Engineer"],
    locations: [],
    resume: { tailor: true, use_tailored_for_upload: true, master_resume_path: null, ai_rewrite: false, preserve_metrics: true, max_buzzwords: 0 },
    portals,
    outreach: { enabled: false, mode: "manual", daily_cap: 0, followup_days: 0, max_followups: 0, auto_recruiter_discovery: false, search_provider: "none" },
  };
}

export async function getConfig(db) {
  try {
    const row = await firstRow(db, "SELECT config_json FROM app_config WHERE id=1");
    if (row?.config_json) return { ...emptyConfig(), ...JSON.parse(row.config_json) };
  } catch { /* schema not yet applied */ }
  return emptyConfig();
}
