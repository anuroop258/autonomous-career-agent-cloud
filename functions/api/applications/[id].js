import { json, firstRow, allRows, mapApplication } from "../../_lib/common.js";
export async function onRequestGet({ params, env }) {
  const id = Number.parseInt(params.id || "", 10);
  if (!Number.isInteger(id)) return json({ detail: "Invalid application ID" }, 400);
  try {
    const app = await firstRow(env.DB, "SELECT * FROM applications WHERE id=?", id);
    if (!app) return json({ detail: "Application not found" }, 404);
    const questions = await allRows(env.DB, "SELECT id,question,answer,field,created_at FROM qa WHERE job_url=? ORDER BY id DESC LIMIT 100", app.url || "").catch(() => []);
    return json({ application: mapApplication(app), events: [], questions });
  } catch { return json({ detail: "Application data schema is not initialized" }, 503); }
}
