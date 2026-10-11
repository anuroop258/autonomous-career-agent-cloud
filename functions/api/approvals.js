import { json, allRows } from "../_lib/common.js";
export async function onRequestGet({ request, env }) {
  const kind = new URL(request.url).searchParams.get("kind");
  try { const rows = kind ? await allRows(env.DB, "SELECT * FROM approvals WHERE kind=? ORDER BY requested_at DESC", kind) : await allRows(env.DB, "SELECT * FROM approvals ORDER BY requested_at DESC"); return json(rows); }
  catch { return json([]); }
}
