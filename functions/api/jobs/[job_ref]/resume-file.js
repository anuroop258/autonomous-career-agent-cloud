import { json, firstRow } from "../../../_lib/common.js";
export async function onRequestGet({ params, env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  const ref = decodeURIComponent(params.job_ref || "");
  try {
    const row = await firstRow(env.DB, "SELECT filename,content_type,content_b64 FROM resume_files WHERE file_key=?", `job:${ref}`);
    if (!row) return json({ detail: "No tailored PDF is stored for this job in the cloud database yet." }, 404);
    const binary = Uint8Array.from(atob(row.content_b64), c => c.charCodeAt(0));
    return new Response(binary, { headers: { "Content-Type": row.content_type || "application/pdf", "Content-Disposition": `inline; filename*=UTF-8''${encodeURIComponent(row.filename || 'resume.pdf')}`, "Cache-Control": "no-store" } });
  } catch { return json({ detail: "Resume file could not be loaded." }, 500); }
}
