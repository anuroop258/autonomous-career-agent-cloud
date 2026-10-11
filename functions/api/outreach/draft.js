import { json, firstRow } from "../../_lib/common.js";

export async function onRequestPost({ request, env }) {
  let body;
  try { body = await request.json(); } catch { return json({ detail: "Request body must be JSON" }, 400); }
  const jobId = Number(body.job_id);
  const recruiterId = Number(body.recruiter_id);
  if (!Number.isSafeInteger(jobId) || !Number.isSafeInteger(recruiterId)) {
    return json({ detail: "job_id and recruiter_id are required" }, 400);
  }
  try {
    const job = await firstRow(env.DB, "SELECT id,title,company,url FROM jobs WHERE id=?", jobId);
    const recruiter = await firstRow(env.DB, "SELECT id,company,name,title,email,profile_url FROM recruiters WHERE id=?", recruiterId);
    if (!job || !recruiter) return json({ detail: "Job or recruiter record not found" }, 404);
    if (!recruiter.email) return json({ detail: "This recruiter has no verified email address; no draft was created." }, 409);
    const role = String(job.title || "the role").trim();
    const company = String(job.company || recruiter.company || "your company").trim();
    const name = String(recruiter.name || "Hiring Team").trim();
    const subject = `Interest in ${role} at ${company}`;
    const message = `Hello ${name},\n\nI am reaching out regarding the ${role} opportunity at ${company}. I would appreciate the opportunity to share my relevant experience and learn more about the role.\n\nThank you for your time.\n\nRegards,\nCareerAgent candidate`;
    const created = new Date().toISOString();
    const result = await env.DB.prepare(`INSERT INTO outreach(job_id,recruiter_id,channel,subject,body,status,created_at,job_title,company,recruiter_name,recruiter_email) VALUES(?,?,'email',?,?,'draft',?,?,?,?,?)`).bind(jobId,recruiterId,subject,message,created,role,company,name,String(recruiter.email)).run();
    const id = Number(result?.meta?.last_row_id || 0);
    return json({ ok: true, id, job_id: jobId, recruiter_id: recruiterId, subject, body: message, status: "draft", message: "Draft saved. Nothing was sent." }, 201);
  } catch {
    return json({ detail: "Could not save the outreach draft. Check the D1 outreach table migration." }, 503);
  }
}
