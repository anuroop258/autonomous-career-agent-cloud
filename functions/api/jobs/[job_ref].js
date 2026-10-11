import { json, firstRow, allRows, mapJob, mapApplication } from "../../_lib/common.js";
export async function onRequestGet({ params, env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  const ref = decodeURIComponent(params.job_ref || "");
  try {
    const raw = await firstRow(env.DB, "SELECT * FROM jobs WHERE job_ref=?", ref);
    if (!raw) return json({ detail: "Job record not found" }, 404);
    const j = mapJob(raw);
    const apps = await allRows(env.DB, "SELECT * FROM applications WHERE application_ref=? OR job_id=? ORDER BY id DESC LIMIT 10", ref, Number(raw.id));
    const resumes = await allRows(env.DB, "SELECT id,job_ref,platform,company,role,job_url,metadata_json,report_json,pdf_available,pdf_filename,created_at FROM resume_versions WHERE job_ref=? ORDER BY created_at DESC", ref);
    return json({ job: j, matches: [], applications: apps.map(mapApplication), resume_versions: resumes.map(r => ({ ...r, metadata: safeJson(r.metadata_json), tailoring_report: safeJson(r.report_json), pdf: r.pdf_available ? r.pdf_filename : null })), events: [] });
  } catch { return json({ detail: "Job details schema not initialized." }, 503); }
}
function safeJson(s) { try { return JSON.parse(s || "{}"); } catch { return {}; } }
