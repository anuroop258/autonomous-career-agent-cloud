import { json } from "../../_lib/common.js";
import { findWorkflowRun, getWorkflowRun, cancelWorkflowRun, terminalTaskStatus } from "../../_lib/github.js";

async function reconcileOne(env, row) {
  if (!row || !["queued", "running", "stopping"].includes(row.status)) return;
  try {
    let run = row.github_run_id ? await getWorkflowRun(env, row.github_run_id) : await findWorkflowRun(env, row.task_id);
    if (!run) return;
    if (!row.github_run_id && run.id) {
      await env.DB.prepare("UPDATE tasks SET github_run_id=?,updated_at=? WHERE task_id=?").bind(run.id, new Date().toISOString(), row.task_id).run();
    }
    if (row.status === "stopping" || Number(row.stop_requested) === 1) {
      if (run.status !== "completed") {
        await cancelWorkflowRun(env, run.id);
        return;
      }
    }
    const finalStatus = terminalTaskStatus(run);
    if (finalStatus) {
      await env.DB.prepare("UPDATE tasks SET status=?,finished_at=COALESCE(finished_at,?),updated_at=?,error=CASE WHEN error IS NULL AND ?='failed' THEN 'GitHub Actions workflow failed' ELSE error END WHERE task_id=? AND status IN ('queued','running','stopping')")
        .bind(finalStatus, new Date().toISOString(), new Date().toISOString(), finalStatus, row.task_id).run();
    } else if (row.status === "queued" && run.status === "in_progress") {
      await env.DB.prepare("UPDATE tasks SET status='running',started_at=COALESCE(started_at,?),updated_at=? WHERE task_id=? AND status='queued' AND stop_requested=0")
        .bind(new Date().toISOString(), new Date().toISOString(), row.task_id).run();
    }
  } catch {
    // Polling should remain available even when GitHub's API is temporarily unavailable.
  }
}

export async function onRequestGet({ env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  try {
    let result = await env.DB.prepare(`SELECT t.task_id,t.portal,t.max_jobs,t.status,t.requested_at,t.started_at,t.finished_at,t.github_run_id,t.stop_requested,t.exit_code,t.error,t.log_tail,t.updated_at,COALESCE(d.operation,'job_search') AS operation,COALESCE(d.job_ref,'') AS job_ref FROM tasks t LEFT JOIN task_details d ON d.task_id=t.task_id ORDER BY t.requested_at DESC LIMIT 30`).all();
    let tasks = result.results || [];
    const active = tasks.find((t) => ["queued", "running", "stopping"].includes(t.status));
    if (active) {
      await reconcileOne(env, active);
      result = await env.DB.prepare(`SELECT t.task_id,t.portal,t.max_jobs,t.status,t.requested_at,t.started_at,t.finished_at,t.github_run_id,t.stop_requested,t.exit_code,t.error,t.log_tail,t.updated_at,COALESCE(d.operation,'job_search') AS operation,COALESCE(d.job_ref,'') AS job_ref FROM tasks t LEFT JOIN task_details d ON d.task_id=t.task_id ORDER BY t.requested_at DESC LIMIT 30`).all();
      tasks = result.results || [];
    }
    const current = tasks.find((t) => ["queued", "running", "stopping"].includes(t.status)) || null;
    const recent = current || tasks[0] || null;
    const runs = {};
    for (const portal of ["naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"]) {
      const row = tasks.find((t) => t.portal === portal && ["queued", "running", "stopping"].includes(t.status) && t.operation === "job_search") || tasks.find((t) => t.portal === portal && t.operation === "job_search");
      runs[portal] = row ? { status: row.status === "queued" ? "running" : row.status, human_verification: false, started_at: row.started_at ? Date.parse(row.started_at) / 1000 : null, returncode: row.exit_code, log_file: row.log_tail ? `cloud task ${row.task_id}` : null, task_id: row.task_id, error: row.error, max_jobs: row.max_jobs } : { status: "idle", human_verification: false };
    }
    return json({ status: current ? (current.status === "queued" ? "running" : current.status) : "idle", portals: current && current.operation === "job_search" ? [current.portal] : [], started_at: recent?.started_at ? Date.parse(recent.started_at) / 1000 : null, pid: null, pids: {}, returncode: recent?.exit_code ?? null, log_file: recent?.log_tail ? `cloud task ${recent.task_id}` : null, operation: recent?.operation || null, job_ref: recent?.job_ref || null, runs, tasks });
  } catch {
    return json({ detail: "Cloud task state schema is not initialized. Run the complete free-cloud-control/schema.sql." }, 503);
  }
}
