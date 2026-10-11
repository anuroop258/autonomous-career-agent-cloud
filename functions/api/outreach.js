import { json, allRows } from "../_lib/common.js";
export async function onRequestGet({ request, env }) {
  const status = new URL(request.url).searchParams.get("status");
  try { return json(status ? await allRows(env.DB,"SELECT * FROM outreach WHERE lower(status)=lower(?) ORDER BY created_at DESC",status) : await allRows(env.DB,"SELECT * FROM outreach ORDER BY created_at DESC LIMIT 500")); }
  catch { return json([]); }
}
