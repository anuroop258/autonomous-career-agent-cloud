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
  const error = body.error == null ? null : String(body.error).slice(0, 2000);
  const finished = ["completed", "failed", "cancelled"].includes(status) ? stamp : null;
  await env.DB.prepare(`UPDATE tasks SET status=?,started_at=CASE WHEN ?='running' AND started_at IS NULL THEN ? ELSE started_at END,finished_at=COALESCE(?,finished_at),github_run_id=COALESCE(?,github_run_id),log_tail=?,exit_code=COALESCE(?,exit_code),error=COALESCE(?,error),updated_at=? WHERE task_id=?`)
    .bind(status, status, stamp, finished, workflowRunId, logTail, exitCode, error, stamp, taskId).run();
  return Response.json({ ok: true, task_id: taskId, status });
}
