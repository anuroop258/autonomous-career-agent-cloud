import { cancelWorkflowRun } from "../../_lib/github.js";
const ALLOWED = new Set(["queued", "running", "stopping", "completed", "failed", "cancelled"]);
export async function onRequestPost({ request, env }) {
  if (!env.DB) return Response.json({ detail: "D1 binding DB is missing" }, { status: 503 });
  let body;
  try { body = await request.json(); } catch { return Response.json({ detail: "Request body must be JSON" }, { status: 400 }); }
  const taskId = String(body.task_id || "").trim();
  const status = String(body.status || "");
  if (!taskId || !ALLOWED.has(status)) return Response.json({ detail: "task_id and a valid status are required" }, { status: 400 });
  const stamp = new Date().toISOString();
  const logTail = String(body.log_tail || "").slice(-14000);
  const workflowRunId = body.github_run_id == null ? null : String(body.github_run_id).slice(0, 80);
  const exitCode = Number.isInteger(body.exit_code) ? body.exit_code : null;
  const error = body.error == null || body.error === "" ? null : String(body.error).slice(0, 2000);
  const finished = ["completed", "failed", "cancelled"].includes(status) ? stamp : null;
  const existing = await env.DB.prepare("SELECT status,stop_requested,github_run_id FROM tasks WHERE task_id=?").bind(taskId).first();
  if (!existing) return Response.json({ detail: "Run not found" }, { status: 404 });
  await env.DB.prepare(`UPDATE tasks SET
      status=CASE WHEN status IN ('completed','failed','cancelled') THEN status WHEN status='stopping' AND ?='running' THEN 'stopping' ELSE ? END,
      started_at=CASE WHEN ?='running' AND started_at IS NULL THEN ? ELSE started_at END,
      finished_at=COALESCE(?,finished_at),github_run_id=COALESCE(?,github_run_id),log_tail=?,
      exit_code=COALESCE(?,exit_code),error=COALESCE(?,error),updated_at=? WHERE task_id=?`)
    .bind(status, status, status, stamp, finished, workflowRunId, logTail, exitCode, error, stamp, taskId).run();
  const effectiveRunId = workflowRunId || existing.github_run_id;
  if ((existing.status === "stopping" || Number(existing.stop_requested) === 1) && effectiveRunId && !["completed", "failed", "cancelled"].includes(existing.status)) {
    try { await cancelWorkflowRun(env, effectiveRunId); } catch { /* status poll retries GitHub cancellation */ }
  }
  const updated = await env.DB.prepare("SELECT status FROM tasks WHERE task_id=?").bind(taskId).first();
  return Response.json({ ok: true, task_id: taskId, status: updated?.status || status });
}
