const PORTALS = new Set(["naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"]);
const now = () => new Date().toISOString();
export async function onRequestPost({ params, env }) {
  if (!env.DB || !env.GH_DISPATCH_TOKEN || !env.GH_REPO_OWNER || !env.GH_REPO_NAME) {
    return Response.json({ detail: "Cloud resume tailoring is not configured. Check D1 and GitHub Actions dispatch settings." }, { status: 503 });
  }
  const jobRef = decodeURIComponent(String(params.job_ref || "")).trim();
  if (!jobRef) return Response.json({ detail: "job_ref is required" }, { status: 400 });
  let job;
  try { job = await env.DB.prepare("SELECT job_ref,platform,title,company,url FROM jobs WHERE job_ref=?").bind(jobRef).first(); }
  catch { return Response.json({ detail: "Dashboard data tables are not initialized. Apply the full D1 schema and sync job data." }, { status: 503 }); }
  if (!job) return Response.json({ detail: "Job record not found" }, { status: 404 });
  const portal = String(job.platform || "").toLowerCase();
  if (!PORTALS.has(portal)) return Response.json({ detail: "This job has an unsupported portal value" }, { status: 400 });
  if (!job.title || /^https?:\/\//i.test(job.title) || !job.company || job.company === "Unknown_Company") {
    return Response.json({ detail: "The selected job is missing a usable title or company. Open the job and use Refresh Job Data first." }, { status: 409 });
  }
  let active;
  try { active = await env.DB.prepare("SELECT task_id,status FROM tasks WHERE status IN ('queued','running','stopping') ORDER BY requested_at DESC LIMIT 1").first(); }
  catch { return Response.json({ detail: "D1 task queue schema is not initialized. Apply the full schema." }, { status: 503 }); }
  if (active) return Response.json({ detail: `Cloud task ${active.task_id} is already ${active.status}. Wait for it to finish before tailoring another resume.` }, { status: 409 });

  const taskId = crypto.randomUUID();
  const stamp = now();
  try {
    await env.DB.batch([
      env.DB.prepare("INSERT INTO tasks (task_id,portal,max_jobs,status,requested_at,updated_at) VALUES (?,?,1,'queued',?,?)").bind(taskId, portal, stamp, stamp),
      env.DB.prepare("INSERT INTO task_details(task_id,operation,job_ref,created_at) VALUES(?,'tailor_resume',?,?)").bind(taskId, jobRef, stamp),
    ]);
  } catch { return Response.json({ detail: "D1 task_details schema is missing. Run the complete free-cloud-control/schema.sql." }, { status: 503 }); }

  const owner = env.GH_REPO_OWNER; const repo = env.GH_REPO_NAME; const workflow = env.GH_WORKFLOW_FILE || "free-cloud-run.yml";
  let response;
  try {
    response = await fetch(`https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/actions/workflows/${encodeURIComponent(workflow)}/dispatches`, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json", "User-Agent": "careeragent-cloud-control" },
      body: JSON.stringify({ ref: "main", inputs: { operation: "tailor_resume", job_ref: jobRef, portal, max_jobs: "1", request_id: taskId, confirm_submit: "NO" } }),
    });
  } catch {
    await env.DB.prepare("UPDATE tasks SET status='failed',error=?,finished_at=?,updated_at=? WHERE task_id=?").bind("Could not reach GitHub Actions API", now(), now(), taskId).run();
    return Response.json({ detail: "Could not reach GitHub Actions. No resume was produced." }, { status: 502 });
  }
  if (response.status !== 204) {
    const error = `GitHub rejected resume-tailoring dispatch (HTTP ${response.status}). Check Actions: write permission and workflow file.`;
    await env.DB.prepare("UPDATE tasks SET status='failed',error=?,finished_at=?,updated_at=? WHERE task_id=?").bind(error, now(), now(), taskId).run();
    return Response.json({ detail: error }, { status: 502 });
  }
  return Response.json({ ok: true, queued: true, task_id: taskId, job_ref: jobRef, portal, status: "queued", message: "Resume tailoring was queued on a temporary cloud runner. Watch the run status for completion." }, { status: 202 });
}
