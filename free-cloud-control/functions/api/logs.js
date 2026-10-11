export async function onRequestGet({ request, env }) {
  if (!env.DB) return Response.json({ detail: "D1 binding DB is missing" }, { status: 503 });
  const id = new URL(request.url).searchParams.get("task_id");
  const query = id
    ? env.DB.prepare("SELECT task_id,portal,status,log_tail,error,updated_at FROM tasks WHERE task_id=?").bind(id)
    : env.DB.prepare("SELECT task_id,portal,status,log_tail,error,updated_at FROM tasks ORDER BY requested_at DESC LIMIT 10");
  const result = id ? await query.first() : await query.all();
  if (id && !result) return Response.json({ detail: "Run not found" }, { status: 404 });
  return Response.json({ logs: id ? [result] : (result.results || []) }, { headers: { "Cache-Control": "no-store" } });
}
