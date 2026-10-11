import { json, allRows, firstRow } from "../_lib/common.js";
export async function onRequestGet({ env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  try {
    const status = await allRows(env.DB, "SELECT status,COUNT(*) AS count FROM applications GROUP BY status ORDER BY count DESC");
    const applications = Number((await firstRow(env.DB, "SELECT COUNT(*) AS n FROM applications"))?.n || 0);
    const resumes = Number((await firstRow(env.DB, "SELECT COUNT(*) AS n FROM resume_versions"))?.n || 0);
    const jobs = Number((await firstRow(env.DB, "SELECT COUNT(*) AS n FROM jobs"))?.n || 0);
    return json({ applications_by_status: Object.fromEntries(status.map(r => [r.status || "unknown", Number(r.count || 0)])), applications, resumes, jobs, cdp: {} });
  } catch { return json({ detail: "Dashboard schema not initialized. Apply migrations/0002_dashboard_data.sql first." }, 503); }
}
