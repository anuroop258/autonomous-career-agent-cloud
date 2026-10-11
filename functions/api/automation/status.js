import { json } from "../../_lib/common.js";
export async function onRequestGet({ env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  try {
    const result = await env.DB.prepare(`SELECT t.task_id,t.portal,t.max_jobs,t.status,t.requested_at,t.started_at,t.finished_at,t.github_run_id,t.stop_requested,t.exit_code,t.error,t.log_tail,t.updated_at,COALESCE(d.operation,'job_search') AS operation,COALESCE(d.job_ref,'') AS job_ref FROM tasks t LEFT JOIN task_details d ON d.task_id=t.task_id ORDER BY t.requested_at DESC LIMIT 30`).all();
    const tasks = result.results || [];
    const active = tasks.find(t => ["queued", "running", "stopping"].includes(t.status));
    const recent = active || tasks[0] || null;
    const runs = {};
    for (const portal of ["naukri","indeed","linkedin","shine","timesjobs","glassdoor"]) {
      const row = tasks.find(t => t.portal === portal && ["queued","running","stopping"].includes(t.status) && t.operation === "job_search") || tasks.find(t => t.portal === portal && t.operation === "job_search");
      runs[portal] = row ? { status: row.status === "queued" ? "running" : row.status, human_verification: false, started_at: row.started_at ? Date.parse(row.started_at) / 1000 : null, returncode: row.exit_code, log_file: row.log_tail ? `cloud task ${row.task_id}` : null, task_id: row.task_id, error: row.error, max_jobs: row.max_jobs } : { status: "idle", human_verification: false };
    }
    return json({ status: active ? (active.status === "queued" ? "running" : active.status) : "idle", portals: active && active.operation === "job_search" ? [active.portal] : [], started_at: recent?.started_at ? Date.parse(recent.started_at) / 1000 : null, pid: null, pids: {}, returncode: recent?.exit_code ?? null, log_file: recent?.log_tail ? `cloud task ${recent.task_id}` : null, operation: recent?.operation || null, job_ref: recent?.job_ref || null, runs, tasks });
  } catch { return json({ detail: "Cloud task state schema is not initialized. Run the complete free-cloud-control/schema.sql." }, 503); }
}
