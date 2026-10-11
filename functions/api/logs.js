import { json, allRows } from "../_lib/common.js";
export async function onRequestGet({ request, env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  const u = new URL(request.url); const limit = Math.max(1, Math.min(300, Number.parseInt(u.searchParams.get("limit") || "100",10) || 100));
  const type = u.searchParams.get("event_type"); const portal = u.searchParams.get("platform");
  try {
    let sql = "SELECT * FROM log_events WHERE 1=1"; const args = [];
    if (type) { sql += " AND event_type=?"; args.push(type); }
    if (portal) { sql += " AND platform=?"; args.push(portal); }
    sql += " ORDER BY created_at DESC,id DESC LIMIT ?"; args.push(limit);
    const events = await allRows(env.DB, sql, ...args);
    const taskRows = await allRows(env.DB, "SELECT task_id,portal,status,error,log_tail,updated_at FROM tasks ORDER BY requested_at DESC LIMIT 10").catch(() => []);
    const taskEvents = taskRows.map((r, i) => ({ id: -1-i, run_id:r.task_id, event_type:`cloud_run_${r.status}`, platform:r.portal, job_id:null, application_id:null, payload_json:JSON.stringify({ error:r.error || null, log_tail:r.log_tail || "" }), payload:{ error:r.error || null, log_tail:r.log_tail || "" }, created_at:r.updated_at }));
    return json([...taskEvents, ...events.map(r => ({ ...r, payload: safeJson(r.payload_json) }))].slice(0, limit));
  } catch { return json([]); }
}
function safeJson(s) { try { return JSON.parse(s || "{}"); } catch { return {}; } }
