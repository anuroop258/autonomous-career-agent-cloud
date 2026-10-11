import { json, firstRow } from "../../_lib/common.js";
export async function onRequestDelete({ params, env }) {
  const id = Number.parseInt(params.id || "", 10);
  if (!Number.isInteger(id)) return json({ detail: "Invalid Q&A ID" }, 400);
  try {
    const row = await firstRow(env.DB, "SELECT id FROM custom_qa WHERE id=?", id);
    if (!row) return json({ detail: "Q&A entry not found" }, 404);
    await env.DB.prepare("DELETE FROM custom_qa WHERE id=?").bind(id).run();
    return json({ ok: true });
  } catch { return json({ detail: "Could not delete Q&A entry" }, 503); }
}
