export async function onRequestPost({ request, env }) {
  if (!env.DB) return Response.json({ detail: "D1 binding DB is missing" }, { status: 503 });
  let body = {}; try { body = await request.json(); } catch {}
  let taskId = String(body.task_id || "").trim();
  if (!taskId) {
    const active = await env.DB.prepare("SELECT task_id FROM tasks WHERE status IN ('queued','running','stopping') ORDER BY requested_at DESC LIMIT 1").first();
    taskId = active?.task_id || "";
  }
  if (!taskId) return Response.json({ detail: "There is no active cloud run to stop" }, { status: 409 });
  const row = await env.DB.prepare("SELECT task_id,status FROM tasks WHERE task_id=?").bind(taskId).first();
  if (!row) return Response.json({ detail: "Run not found" }, { status: 404 });
  if (!["queued", "running", "stopping"].includes(row.status)) return Response.json({ detail: `Run is already ${row.status}` }, { status: 409 });
  await env.DB.prepare("UPDATE tasks SET stop_requested=1,status='stopping',updated_at=? WHERE task_id=?").bind(new Date().toISOString(), taskId).run();
  return Response.json({ ok: true, task_id: taskId, status: "stopping", message: "Stop requested. The cloud runner checks for stop requests periodically." });
}
