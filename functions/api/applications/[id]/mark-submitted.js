import { json, firstRow } from "../../../_lib/common.js";
export async function onRequestPost({ params, env }) {
  const id = Number.parseInt(params.id || "", 10);
  if (!Number.isInteger(id)) return json({ detail: "Invalid application ID" }, 400);
  try {
    const row = await firstRow(env.DB, "SELECT id FROM applications WHERE id=?", id);
    if (!row) return json({ detail: "Application not found" }, 404);
    const stamp = new Date().toISOString();
    await env.DB.prepare("UPDATE applications SET status='submitted',submitted_at=?,updated_at=? WHERE id=?").bind(stamp, stamp, id).run();
    await env.DB.prepare("UPDATE jobs SET status='submitted',application_status='submitted',updated_at=? WHERE application_id=?").bind(stamp, id).run();
    return json({ ok: true });
  } catch { return json({ detail: "Could not update application status" }, 503); }
}
