import { json, allRows } from "../../_lib/common.js";
export async function onRequestGet({ request, env }) {
  if (!env.DB) return json({ files: [], tail: [] });
  const lines = Math.max(1, Math.min(500, Number.parseInt(new URL(request.url).searchParams.get("lines") || "200",10) || 200));
  try {
    const rows = await allRows(env.DB, "SELECT task_id,portal,status,log_tail,updated_at FROM tasks ORDER BY requested_at DESC LIMIT 10");
    const tail = [];
    for (const r of rows) {
      tail.push(`[${r.updated_at}] ${r.portal} ${r.status} (${r.task_id})`);
      if (r.log_tail) tail.push(...String(r.log_tail).split(/\r?\n/));
    }
    return json({ files: rows.map(r => `cloud task ${r.task_id}`), tail: tail.slice(-lines), current_file: rows[0] ? `cloud task ${rows[0].task_id}` : undefined });
  } catch { return json({ files: [], tail: [] }); }
}
