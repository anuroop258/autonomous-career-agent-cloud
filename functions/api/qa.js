import { json, allRows } from "../_lib/common.js";
export async function onRequestGet({ env }) {
  try { return json(await allRows(env.DB, "SELECT id,question,answer,created_at,updated_at FROM custom_qa ORDER BY updated_at DESC,id DESC LIMIT 500")); }
  catch { return json({ detail: "Q&A table not initialized" }, 503); }
}
export async function onRequestPost({ request, env }) {
  let b; try { b = await request.json(); } catch { return json({ detail: "Request body must be JSON" }, 400); }
  const q = String(b.question || "").trim(); const a = String(b.answer || "").trim();
  if (!q || !a) return json({ detail: "question and answer are required" }, 400);
  const now = new Date().toISOString();
  try {
    await env.DB.prepare("INSERT INTO custom_qa(question,answer,created_at,updated_at) VALUES(?,?,?,?) ON CONFLICT(question) DO UPDATE SET answer=excluded.answer,updated_at=excluded.updated_at").bind(q,a,now,now).run();
    return json({ ok: true });
  } catch { return json({ detail: "Could not save Q&A entry" }, 503); }
}
