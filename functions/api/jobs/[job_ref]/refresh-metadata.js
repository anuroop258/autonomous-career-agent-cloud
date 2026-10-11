import { json, firstRow } from "../../../_lib/common.js";
export async function onRequestPost({ params, env }) {
  const ref = decodeURIComponent(params.job_ref || "");
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  const row = await firstRow(env.DB, "SELECT job_ref FROM jobs WHERE job_ref=?", ref).catch(() => null);
  if (!row) return json({ updated: false, job_ref: ref, message: "Job not found" }, 404);
  return json({ updated: false, job_ref: ref, message: "Metadata refresh requires a live portal browser. The cloud runner will update metadata when the portal agent runs." });
}
