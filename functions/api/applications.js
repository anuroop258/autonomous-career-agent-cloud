import { json, allRows, mapApplication, cleanLimit } from "../_lib/common.js";
export async function onRequestGet({ request, env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  try {
    const u = new URL(request.url); const status = u.searchParams.get("status"); const limit = cleanLimit(u.searchParams.get("limit"), 2000, 5000); const offset = Math.max(0, Number.parseInt(u.searchParams.get("offset") || "0", 10) || 0);
    let sql = "SELECT * FROM applications WHERE 1=1"; const args = [];
    if (status) { sql += " AND lower(status)=lower(?)"; args.push(status); }
    sql += " ORDER BY COALESCE(updated_at,created_at) DESC,id DESC LIMIT ? OFFSET ?"; args.push(limit, offset);
    return json((await allRows(env.DB, sql, ...args)).map(mapApplication));
  } catch { return json({ detail: "Applications table is not initialized. Apply the D1 dashboard migration." }, 503); }
}
