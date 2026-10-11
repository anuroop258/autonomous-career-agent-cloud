import { json, allRows, mapJob, cleanLimit } from "../_lib/common.js";
export async function onRequestGet({ request, env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  try {
    const u = new URL(request.url); const portal = u.searchParams.get("portal"); const q = (u.searchParams.get("q") || "").trim().toLowerCase();
    const eligible = u.searchParams.get("eligible"); const limit = cleanLimit(u.searchParams.get("limit"), 2000, 5000); const offset = Math.max(0, Number.parseInt(u.searchParams.get("offset") || "0",10) || 0);
    let sql = "SELECT * FROM jobs WHERE 1=1"; const args = [];
    if (portal) { sql += " AND lower(platform)=lower(?)"; args.push(portal); }
    if (eligible === "true") sql += " AND eligible=1"; else if (eligible === "false") sql += " AND eligible=0";
    if (q) { sql += " AND (lower(title) LIKE ? OR lower(company) LIKE ? OR lower(location) LIKE ? OR lower(description) LIKE ?)"; const term = `%${q}%`; args.push(term,term,term,term); }
    sql += " ORDER BY CASE WHEN match_score IS NULL THEN 1 ELSE 0 END,match_score DESC,discovered_at DESC,id DESC LIMIT ? OFFSET ?"; args.push(limit,offset);
    return json((await allRows(env.DB, sql, ...args)).map(mapJob));
  } catch { return json({ detail: "Jobs table is not initialized. Apply the D1 dashboard migration." }, 503); }
}
