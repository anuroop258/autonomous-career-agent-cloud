import { json, allRows } from "../../../_lib/common.js";
export async function onRequestGet({ params, env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  try {
    const versions = await allRows(env.DB, "SELECT id,job_ref,platform,company,role,job_url,metadata_json,report_json,pdf_available,pdf_filename,created_at FROM resume_versions WHERE job_ref=? ORDER BY created_at DESC", decodeURIComponent(params.job_ref || ""));
    return json({ versions: versions.map(r => ({ ...r, metadata: safeJson(r.metadata_json), tailoring_report: safeJson(r.report_json), pdf: r.pdf_available ? r.pdf_filename : null })) });
  } catch { return json({ versions: [] }); }
}
function safeJson(s) { try { return JSON.parse(s || "{}"); } catch { return {}; } }
