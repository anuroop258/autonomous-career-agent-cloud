import { json, allRows, mapJob } from "../../_lib/common.js";

const PORTALS = new Set(["naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"]);
const GROUPS = [
  ["applied", "Applied", "Submitted or confirmed on the portal."],
  ["needs_you", "Needs you", "Agent stopped and is waiting on a question, captcha, review or manual submit."],
  ["matched", "Matched, not applied", "Passed the match filter but no application was sent (dry runs, no direct apply)."],
  ["failed", "Failed", "Apply flow errored out or could not be reached."],
  ["skipped", "Skipped", "Low JD match or experience mismatch."],
  ["other", "Other", "Status not recognised yet."],
];
const APPLIED = new Set(["submitted", "confirmed", "applied"]);
const NEEDS = new Set(["unknown_question", "human_intervention", "blocked", "answer_not_verified", "application_incomplete", "awaiting_approval", "ready_for_manual_submit", "ready_to_submit", "application_ready", "external_partial", "external_filled", "native_flow_stopped", "security_check", "submission_unconfirmed", "no_questions", "applying", "apply_clicked"]);
const MATCHED = new Set(["native_dry_run", "match_found_no_direct_apply", "not_applied", "external"]);
const SKIPPED = new Set(["low_match", "experience_mismatch", "external_skipped"]);
const TOKEN_SYNONYMS = { genai: ["generative", "ai"], ml: ["machine", "learning"], aiml: ["ai", "machine", "learning"], developer: ["engineer"], dev: ["engineer"], programmer: ["engineer"] };
const cleanTitle = (value) => { const s = String(value || "").trim(); return s.includes(" - ") ? s.split(" - ")[0].trim() : s; };
function tokens(value) {
  const text = String(value || "").toLowerCase().replace(/ai\/ml/g, "ai ml").replace(/&/g, " ").replace(/[^a-z0-9+#]+/g, " ");
  const out = new Set(); for (const token of text.split(/\s+/).filter(Boolean)) for (const part of (TOKEN_SYNONYMS[token] || [token])) out.add(part); return out;
}
function titleMatches(title, wanted) {
  if (!wanted.length) return true; const actual = tokens(cleanTitle(title));
  return wanted.some((w) => { const required = tokens(w); return required.size > 0 && [...required].every((t) => actual.has(t)); });
}
function groupFor(value) {
  const s = String(value || "").toLowerCase();
  if (APPLIED.has(s)) return "applied";
  if (NEEDS.has(s)) return "needs_you";
  if (MATCHED.has(s)) return "matched";
  if (SKIPPED.has(s)) return "skipped";
  if (s.endsWith("_error") || s.endsWith("_failed") || ["error", "external_blocked", "external_apply_not_reached", "external_apply_not_found", "apply_not_found", "apply_click_failed", "resume_upload_failed", "submit_not_found", "naukri_apply_error", "application_error"].includes(s)) return "failed";
  return "other";
}
function normalizedUrl(value) {
  try { const u = new URL(String(value || "")); u.hash = ""; for (const key of [...u.searchParams.keys()]) if (/^(utm_|source$|ref$|referral-source$)/i.test(key)) u.searchParams.delete(key); return u.toString().replace(/\/$/, ""); } catch { return String(value || "").split("#")[0].split("?")[0].replace(/\/$/, ""); }
}

export async function onRequestGet({ request, env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  const url = new URL(request.url);
  const titles = url.searchParams.getAll("titles").map((s) => s.trim()).filter(Boolean);
  const locations = url.searchParams.getAll("locations").map((s) => s.trim().toLowerCase()).filter(Boolean);
  const portals = url.searchParams.getAll("portals").map((s) => s.trim().toLowerCase()).filter((s) => PORTALS.has(s));
  const query = (url.searchParams.get("q") || "").trim().toLowerCase();
  const minMatch = Math.max(0, Math.min(100, Number(url.searchParams.get("min_match") || 0) || 0));
  const perGroup = Math.max(1, Math.min(500, Number.parseInt(url.searchParams.get("per_group") || "60", 10) || 60));
  try {
    const raw = await allRows(env.DB, "SELECT * FROM jobs ORDER BY COALESCE(updated_at,discovered_at) DESC,id DESC LIMIT 5000");
    const buckets = Object.fromEntries(GROUPS.map(([key]) => [key, []]));
    const seen = new Set();
    for (const source of raw) {
      const row = mapJob(source); const platform = String(row.platform || "").toLowerCase();
      if (portals.length && !portals.includes(platform)) continue;
      if (!titleMatches(row.title, titles)) continue;
      if (locations.length && !locations.some((loc) => `${row.location || ""} ${row.title || ""}`.toLowerCase().includes(loc))) continue;
      if (query && !`${row.title || ""} ${row.company || ""}`.toLowerCase().includes(query)) continue;
      if (minMatch && row.match_score != null && Number(row.match_score) < minMatch) continue;
      const dedupe = normalizedUrl(row.url) || `${platform}:${cleanTitle(row.title).toLowerCase()}:${String(row.company || "").trim().toLowerCase()}`;
      if (seen.has(dedupe)) continue; seen.add(dedupe);
      const group = groupFor(row.status || row.application_status);
      buckets[group].push({ ...row, title_clean: cleanTitle(row.title), group, status: String(row.status || row.application_status || "unknown") });
    }
    const groups = GROUPS.filter(([key]) => buckets[key].length).map(([key, label, hint]) => ({ key, label, hint, count: buckets[key].length, jobs: buckets[key].slice(0, perGroup) }));
    return json({ total: groups.reduce((sum, g) => sum + g.count, 0), groups });
  } catch (error) {
    return json({ detail: "Processed job search failed. Apply migrations/0002_dashboard_data.sql and sync local job data to D1." }, 503);
  }
}
