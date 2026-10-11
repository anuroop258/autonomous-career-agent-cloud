export async function onRequestGet({ env }) {
  if (!env.DB) return Response.json({ detail: "D1 binding DB is missing" }, { status: 503 });
  const result = await env.DB.prepare("SELECT task_id,portal,max_jobs,status,requested_at,started_at,finished_at,github_run_id,stop_requested,exit_code,error,updated_at FROM tasks ORDER BY requested_at DESC LIMIT 20").all();
  const tasks = result.results || [];
  const active = tasks.some(t => ["queued", "running", "stopping"].includes(t.status));
  return Response.json({ tasks, active }, { headers: { "Cache-Control": "no-store" } });
}
