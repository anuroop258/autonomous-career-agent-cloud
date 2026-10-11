import { json, allRows, mapApplication, cleanLimit } from "../../_lib/common.js";
export async function onRequestGet({ request, env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  try {
    const limit = cleanLimit(new URL(request.url).searchParams.get("limit"), 50, 100);
    const rows = await allRows(env.DB, "SELECT * FROM applications WHERE lower(status) IN ('error','unknown_question','ready_to_submit','no_questions','external_error','human_intervention','resume_upload_failed') ORDER BY updated_at DESC,id DESC LIMIT ?", limit);
    return json(rows.map(mapApplication));
  } catch { return json([]); }
}
