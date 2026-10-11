export async function onRequestGet({ request, env }) {
  if (!env.DB) return Response.json({ detail: "D1 binding DB is missing" }, { status: 503 });
  const taskId = new URL(request.url).searchParams.get("task_id") || "";
  if (!taskId) return Response.json({ detail: "task_id is required" }, { status: 400 });
  const row = await env.DB.prepare("SELECT task_id,status,stop_requested FROM tasks WHERE task_id=?").bind(taskId).first();
  if (!row) return Response.json({ detail: "Run not found" }, { status: 404 });
  return Response.json({ task_id: row.task_id, status: row.status, stop_requested: Boolean(row.stop_requested) }, { headers: { "Cache-Control": "no-store" } });
}
