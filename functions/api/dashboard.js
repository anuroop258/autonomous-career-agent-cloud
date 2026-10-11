import { json, allRows, firstRow, mapApplication, mapJob } from "../_lib/common.js";
const submittedSql = "lower(status) IN ('submitted','confirmed','applied','external_submitted')";
export async function onRequestGet({ env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  try {
    const db = env.DB;
    const jobsTotal = Number((await firstRow(db, "SELECT COUNT(*) AS n FROM jobs"))?.n || 0);
    const appsTotal = Number((await firstRow(db, "SELECT COUNT(*) AS n FROM applications"))?.n || 0);
    const eligible = Number((await firstRow(db, "SELECT COUNT(*) AS n FROM jobs WHERE eligible=1"))?.n || 0);
    const submitted = Number((await firstRow(db, `SELECT COUNT(*) AS n FROM applications WHERE ${submittedSql}`))?.n || 0);
    const awaiting = Number((await firstRow(db, "SELECT COUNT(*) AS n FROM applications WHERE lower(status) IN ('awaiting_approval','approval_pending')"))?.n || 0);
    const manual = Number((await firstRow(db, "SELECT COUNT(*) AS n FROM applications WHERE lower(status) IN ('ready_to_submit','application_ready','ready_for_manual_submit')"))?.n || 0);
    const rejected = Number((await firstRow(db, "SELECT COUNT(*) AS n FROM applications WHERE lower(status) LIKE '%reject%'"))?.n || 0);
    const interviews = Number((await firstRow(db, "SELECT COUNT(*) AS n FROM applications WHERE lower(status) LIKE '%interview%'"))?.n || 0);
    const today = new Date().toISOString().slice(0, 10);
    const discoveredToday = Number((await firstRow(db, "SELECT COUNT(*) AS n FROM jobs WHERE substr(discovered_at,1,10)=?", today))?.n || 0);
    const appliedToday = Number((await firstRow(db, `SELECT COUNT(*) AS n FROM applications WHERE ${submittedSql} AND substr(COALESCE(submitted_at,created_at),1,10)=?`, today))?.n || 0);
    const byPortal = await allRows(db, "SELECT platform AS name,COUNT(*) AS count FROM jobs GROUP BY platform ORDER BY count DESC");
    const byCompany = await allRows(db, "SELECT COALESCE(NULLIF(company,''),'Unknown_Company') AS name,COUNT(*) AS count FROM jobs GROUP BY COALESCE(NULLIF(company,''),'Unknown_Company') ORDER BY count DESC LIMIT 20");
    const byTitle = await allRows(db, "SELECT COALESCE(NULLIF(title,''),'Unknown role') AS name,COUNT(*) AS count FROM jobs GROUP BY COALESCE(NULLIF(title,''),'Unknown role') ORDER BY count DESC LIMIT 20");
    const appByPortal = await allRows(db, `SELECT platform AS name,COUNT(*) AS count,SUM(CASE WHEN ${submittedSql} THEN 1 ELSE 0 END) AS submitted FROM applications GROUP BY platform ORDER BY count DESC`);
    const appByStatus = await allRows(db, "SELECT status,COUNT(*) AS count FROM applications GROUP BY status ORDER BY count DESC");
    const funnel = appByStatus.map(r => ({ stage: r.status || "unknown", count: Number(r.count || 0) }));
    const outreachRows = await allRows(db, "SELECT lower(status) AS status,COUNT(*) AS count FROM outreach GROUP BY lower(status)").catch(() => []);
    const outreach = { drafts: 0, approved_unsent: 0, sent: 0, replied: 0, response_rate: 0, positive: 0, negative: 0, action_required: 0, send_failed: 0, pending_followups: 0 };
    for (const r of outreachRows) {
      const k = String(r.status || ""); const n = Number(r.count || 0);
      if (k === "draft") outreach.drafts = n;
      if (k === "approved_unsent") outreach.approved_unsent = n;
      if (k === "sent") outreach.sent = n;
      if (k === "replied") outreach.replied = n;
      if (k === "positive") outreach.positive = n;
      if (k === "negative") outreach.negative = n;
      if (k === "action_required") outreach.action_required = n;
      if (k === "send_failed") outreach.send_failed = n;
      if (k === "pending_followup") outreach.pending_followups = n;
    }
    outreach.response_rate = outreach.sent ? Math.round(outreach.replied * 100 / outreach.sent) : 0;
    const topJobs = (await allRows(db, "SELECT * FROM jobs ORDER BY CASE WHEN match_score IS NULL THEN 1 ELSE 0 END,match_score DESC,id DESC LIMIT 6")).map(mapJob);
    const recentApps = (await allRows(db, "SELECT * FROM applications ORDER BY COALESCE(updated_at,created_at) DESC,id DESC LIMIT 8")).map(mapApplication);
    const attention = (await allRows(db, "SELECT * FROM applications WHERE lower(status) IN ('error','unknown_question','ready_to_submit','no_questions','external_error','human_intervention','resume_upload_failed') ORDER BY updated_at DESC,id DESC LIMIT 12")).map(mapApplication);
    const jobsTotalToday = discoveredToday;
    return json({
      generated_at: new Date().toISOString(), candidate_id: "CareerAgent", jobs_discovered: jobsTotal,
      applications_total: appsTotal, applications_submitted: submitted, awaiting_approval: awaiting,
      ready_for_manual_submit: manual, rejections: rejected, interviews, pending_approvals: Number((await firstRow(db, "SELECT COUNT(*) AS n FROM approvals WHERE status='pending'").catch(() => ({ n: 0 })))?.n || 0),
      jobs: { total: jobsTotal, discovered_today: jobsTotalToday, discovered_week: Number((await firstRow(db, "SELECT COUNT(*) AS n FROM jobs WHERE substr(discovered_at,1,10) >= date('now','-7 day')"))?.n || 0), discovered_month: Number((await firstRow(db, "SELECT COUNT(*) AS n FROM jobs WHERE substr(discovered_at,1,10) >= date('now','-30 day')"))?.n || 0), applied_today: appliedToday, eligible, by_portal: byPortal.map(r => ({ name:r.name,count:Number(r.count||0) })), by_company: byCompany.map(r => ({ name:r.name,count:Number(r.count||0) })), by_title: byTitle.map(r => ({ name:r.name,count:Number(r.count||0) })) },
      applications: { total: appsTotal, submitted, by_status: Object.fromEntries(appByStatus.map(r => [r.status || "unknown", Number(r.count||0)])), by_portal: appByPortal.map(r => ({ name:r.name,count:Number(r.count||0),submitted:Number(r.submitted||0) })), funnel },
      outreach, top_jobs: topJobs, recent_applications: recentApps, needs_attention: attention
    });
  } catch (error) {
    return json({ detail: "Dashboard data tables are missing or could not be read. Apply migrations/0002_dashboard_data.sql and run the dashboard data sync command." }, 503);
  }
}
