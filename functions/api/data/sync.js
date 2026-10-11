import { json, firstRow } from "../../_lib/common.js";
const NOW = () => new Date().toISOString();
const str = (v, fallback="") => v == null ? fallback : String(v);
const numOrNull = v => v == null || v === "" || !Number.isFinite(Number(v)) ? null : Number(v);
const asJson = v => typeof v === "string" ? v : JSON.stringify(v ?? []);

export async function onRequestPost({ request, env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  let body; try { body = await request.json(); } catch { return json({ detail: "Request body must be JSON" }, 400); }
  const allowed = ["jobs","applications","custom_qa","qa","resume_versions","resume_files","logs"];
  if (body.reset_snapshot === true) {
    if (Object.keys(body).length !== 1) return json({ detail: "Snapshot reset must be sent as a standalone authenticated request" }, 400);
    try {
      // These tables are the replaceable mirror of the private runner's local data.
      // Keep user-created recruiters/outreach/approvals and saved preferences untouched.
      await env.DB.batch([
        env.DB.prepare("DELETE FROM applications"),
        env.DB.prepare("DELETE FROM jobs"),
        env.DB.prepare("DELETE FROM custom_qa"),
        env.DB.prepare("DELETE FROM qa"),
        env.DB.prepare("DELETE FROM resume_versions"),
        env.DB.prepare("DELETE FROM resume_files"),
        env.DB.prepare("DELETE FROM log_events"),
        env.DB.prepare("DELETE FROM app_documents"),
      ]);
      return json({ ok: true, reset: true, synced: 0 });
    } catch (error) {
      return json({ detail: "Dashboard snapshot reset failed. Apply migrations/0002_dashboard_data.sql and verify the D1 schema." }, 503);
    }
  }
  if (Object.keys(body).some(k => !allowed.includes(k) && k !== "config" && k !== "documents")) return json({ detail: "Unexpected sync payload field" }, 400);
  const statements = [];
  const stamp = NOW();
  for (const r of (Array.isArray(body.jobs) ? body.jobs : []).slice(0, 60)) {
    if (!r.job_ref || !r.platform || !r.id) continue;
    statements.push(env.DB.prepare(`INSERT INTO jobs(id,job_ref,platform,source,job_key,title,company,location,description,url,discovered_at,updated_at,match_score,eligible,matched_skills,missing_skills,application_id,application_platform,application_status,resume_version_id,resume_pdf_available,application_route,status)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(job_ref) DO UPDATE SET id=excluded.id,platform=excluded.platform,source=excluded.source,job_key=excluded.job_key,title=excluded.title,company=excluded.company,location=excluded.location,description=excluded.description,url=excluded.url,discovered_at=excluded.discovered_at,updated_at=excluded.updated_at,match_score=excluded.match_score,eligible=excluded.eligible,matched_skills=excluded.matched_skills,missing_skills=excluded.missing_skills,application_id=excluded.application_id,application_platform=excluded.application_platform,application_status=excluded.application_status,resume_version_id=excluded.resume_version_id,resume_pdf_available=excluded.resume_pdf_available,application_route=excluded.application_route,status=excluded.status`)
      .bind(Number(r.id),str(r.job_ref),str(r.platform),str(r.source,r.platform),str(r.job_key),str(r.title,"Unknown role"),str(r.company,"Unknown_Company"),str(r.location),str(r.description),str(r.url),str(r.discovered_at),str(r.updated_at,stamp),numOrNull(r.match_score),numOrNull(r.eligible),asJson(r.matched_skills),asJson(r.missing_skills),numOrNull(r.application_id),str(r.application_platform,r.platform),str(r.application_status,r.status),numOrNull(r.resume_version_id),r.resume_pdf_available ? 1 : 0,str(r.application_route,"unknown"),str(r.status,"discovered")));
  }
  for (const r of (Array.isArray(body.applications) ? body.applications : []).slice(0, 60)) {
    if (!r.application_ref || !r.id || !r.job_id || !r.platform) continue;
    statements.push(env.DB.prepare(`INSERT INTO applications(id,application_ref,candidate_id,job_id,platform,status,resume_version_id,submitted_at,last_error,created_at,updated_at,title,company,location,url,source,eligible,resume_pdf_available,application_route,description,match_score,matched_skills)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(application_ref) DO UPDATE SET id=excluded.id,candidate_id=excluded.candidate_id,job_id=excluded.job_id,platform=excluded.platform,status=excluded.status,resume_version_id=excluded.resume_version_id,submitted_at=excluded.submitted_at,last_error=excluded.last_error,created_at=excluded.created_at,updated_at=excluded.updated_at,title=excluded.title,company=excluded.company,location=excluded.location,url=excluded.url,source=excluded.source,eligible=excluded.eligible,resume_pdf_available=excluded.resume_pdf_available,application_route=excluded.application_route,description=excluded.description,match_score=excluded.match_score,matched_skills=excluded.matched_skills`)
      .bind(Number(r.id),str(r.application_ref),"public",Number(r.job_id),str(r.platform),str(r.status,"discovered"),numOrNull(r.resume_version_id),r.submitted_at || null,r.last_error || null,str(r.created_at),str(r.updated_at,stamp),str(r.title,"Unknown role"),str(r.company,"Unknown_Company"),str(r.location),str(r.url),str(r.source,r.platform),numOrNull(r.eligible),r.resume_pdf_available ? 1 : 0,str(r.application_route,"unknown"),str(r.description),numOrNull(r.match_score),asJson(r.matched_skills)));
  }
  for (const r of (Array.isArray(body.custom_qa) ? body.custom_qa : []).slice(0, 60)) {
    if (!r.question) continue;
    statements.push(env.DB.prepare("INSERT INTO custom_qa(id,question,answer,created_at,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(question) DO UPDATE SET answer=excluded.answer,updated_at=excluded.updated_at")
      .bind(Number(r.id) || Math.abs(hashText(r.question)),str(r.question),str(r.answer),str(r.created_at,stamp),str(r.updated_at,stamp)));
  }
  for (const r of (Array.isArray(body.qa) ? body.qa : []).slice(0, 60)) {
    if (!r.id) continue;
    statements.push(env.DB.prepare("INSERT INTO qa(id,job_url,question,answer,field,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET job_url=excluded.job_url,question=excluded.question,answer=excluded.answer,field=excluded.field,created_at=excluded.created_at")
      .bind(Number(r.id),str(r.job_url),str(r.question),str(r.answer),str(r.field),str(r.created_at,stamp)));
  }
  for (const r of (Array.isArray(body.resume_versions) ? body.resume_versions : []).slice(0, 50)) {
    if (!r.id || !r.job_ref) continue;
    statements.push(env.DB.prepare("INSERT INTO resume_versions(id,job_ref,platform,company,role,job_url,metadata_json,report_json,pdf_available,pdf_filename,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET job_ref=excluded.job_ref,platform=excluded.platform,company=excluded.company,role=excluded.role,job_url=excluded.job_url,metadata_json=excluded.metadata_json,report_json=excluded.report_json,pdf_available=excluded.pdf_available,pdf_filename=excluded.pdf_filename,created_at=excluded.created_at")
      .bind(Number(r.id),str(r.job_ref),str(r.platform),str(r.company),str(r.role),str(r.job_url),asJson(r.metadata),asJson(r.report),r.pdf_available ? 1 : 0,str(r.pdf_filename),str(r.created_at,stamp)));
  }
  for (const r of (Array.isArray(body.resume_files) ? body.resume_files : []).slice(0, 5)) {
    if (!r.file_key || !r.content_b64 || String(r.content_b64).length > 1850000) continue;
    statements.push(env.DB.prepare("INSERT INTO resume_files(file_key,filename,content_type,content_b64,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(file_key) DO UPDATE SET filename=excluded.filename,content_type=excluded.content_type,content_b64=excluded.content_b64,updated_at=excluded.updated_at")
      .bind(str(r.file_key),str(r.filename,"resume.pdf"),str(r.content_type,"application/pdf"),str(r.content_b64),stamp));
  }
  for (const r of (Array.isArray(body.logs) ? body.logs : []).slice(0, 60)) {
    if (!r.id) continue;
    statements.push(env.DB.prepare("INSERT INTO log_events(id,run_id,event_type,platform,job_id,application_id,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id,event_type=excluded.event_type,platform=excluded.platform,job_id=excluded.job_id,application_id=excluded.application_id,payload_json=excluded.payload_json,created_at=excluded.created_at")
      .bind(Number(r.id),r.run_id || null,str(r.event_type,"imported"),r.platform || null,numOrNull(r.job_id),numOrNull(r.application_id),r.payload_json || null,str(r.created_at,stamp)));
  }
  if (body.config && typeof body.config === "object") {
    // A runner config refresh must not erase the preferences saved from the public Find Jobs page.
    let incoming = body.config;
    try {
      const current = await firstRow(env.DB, "SELECT config_json FROM app_config WHERE id=1");
      const currentConfig = current?.config_json ? JSON.parse(current.config_json) : {};
      if (currentConfig?.preferences && !Object.prototype.hasOwnProperty.call(incoming, "preferences")) {
        incoming = { ...incoming, preferences: currentConfig.preferences };
      }
    } catch { /* app_config may be empty before the first migration/sync */ }
    statements.push(env.DB.prepare("INSERT INTO app_config(id,config_json,updated_at) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET config_json=excluded.config_json,updated_at=excluded.updated_at").bind(JSON.stringify(incoming), stamp));
  }
  if (body.documents && typeof body.documents === "object") {
    for (const [key,value] of Object.entries(body.documents).slice(0, 5)) {
      if (!["master_resume_tex","resume_content_bank"].includes(key)) continue;
      statements.push(env.DB.prepare("INSERT INTO app_documents(doc_key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(doc_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at").bind(key,JSON.stringify(value),stamp));
    }
  }
  if (!statements.length) return json({ ok: true, synced: 0 });
  try {
    await env.DB.batch(statements);
    return json({ ok: true, synced: statements.length, jobs: (body.jobs || []).length, applications: (body.applications || []).length });
  } catch (error) {
    return json({ detail: "D1 sync failed. Make sure migration 0002_dashboard_data.sql ran successfully and each request contains at most 100 rows." }, 503);
  }
}
function hashText(s) { let h=2166136261; for (const c of String(s)) h=Math.imul(h ^ c.charCodeAt(0),16777619); return h >>> 0; }
