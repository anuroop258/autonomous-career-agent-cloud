import { json, firstRow } from "../../../_lib/common.js";
export async function onRequestPost({ params, request, env }) {
  const id = Number.parseInt(params.id || "", 10); const action = String(params.action || "").toLowerCase();
  if (!Number.isInteger(id) || !["approve", "reject"].includes(action)) return json({ detail: "Invalid approval action" }, 400);
  let body = {}; try { body = await request.json(); } catch {}
  const stamp = new Date().toISOString(); const status = action === "approve" ? "approved" : "rejected";
  try {
    const row = await firstRow(env.DB, "SELECT * FROM approvals WHERE id=?", id);
    if (!row) return json({ detail: "Approval not found" }, 404);
    await env.DB.prepare("UPDATE approvals SET status=?,note=?,decided_at=? WHERE id=?").bind(status, String(body.note || ""), stamp, id).run();
    return json({ ...row, status, note: String(body.note || ""), decided_at: stamp });
  } catch { return json({ detail: "Approval table is not initialized" }, 503); }
}
