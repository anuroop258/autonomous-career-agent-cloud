const PORTALS = new Set(["naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"]);
const now = () => new Date().toISOString();
export async function onRequestPost({ request, env }) {
  if (!env.DB || !env.GH_DISPATCH_TOKEN || !env.GH_REPO_OWNER || !env.GH_REPO_NAME) {
    return Response.json({ detail: "Cloud automation is not configured. Check the D1 binding, GH_DISPATCH_TOKEN, GH_REPO_OWNER and GH_REPO_NAME in Cloudflare Production settings." }, { status: 503 });
  }
  let body; try { body = await request.json(); } catch { return Response.json({ detail: "Request body must be JSON" }, { status: 400 }); }
  const portal = String(body.portal || "").toLowerCase();
  const maxJobs = Number.parseInt(String(body.max_jobs ?? "1"), 10);
  if (!PORTALS.has(portal)) return Response.json({ detail: "Unsupported portal" }, { status: 400 });
  if (!Number.isInteger(maxJobs) || maxJobs < 1 || maxJobs > 5) return Response.json({ detail: "max_jobs must be from 1 to 5 on the free cloud runner" }, { status: 400 });
  if (body.confirmed !== true) return Response.json({ detail: "Confirm the selected portal and target before starting" }, { status: 400 });
  let active;
  try { active = await env.DB.prepare("SELECT task_id,status FROM tasks WHERE status IN ('queued','running','stopping') ORDER BY requested_at DESC LIMIT 1").first(); }
  catch { return Response.json({ detail: "D1 task queue schema is missing. Apply the Cloudflare task schema before starting a run." }, { status: 503 }); }
  if (active) return Response.json({ detail: `Run ${active.task_id} is already ${active.status}. Wait until it finishes.` }, { status: 409 });
  const taskId = crypto.randomUUID(); const timestamp = now();
  try {
    await env.DB.batch([
      env.DB.prepare("INSERT INTO tasks (task_id,portal,max_jobs,status,requested_at,updated_at) VALUES (?,?,?,'queued',?,?)").bind(taskId, portal, maxJobs, timestamp, timestamp),
      env.DB.prepare("INSERT INTO task_details(task_id,operation,job_ref,created_at) VALUES(?,'job_search','',?)").bind(taskId, timestamp),
    ]);
  } catch {
    return Response.json({ detail: "D1 task_details schema is missing. Run the complete free-cloud-control/schema.sql before starting a cloud job." }, { status: 503 });
  }
  const owner = env.GH_REPO_OWNER; const repo = env.GH_REPO_NAME; const workflow = env.GH_WORKFLOW_FILE || "free-cloud-run.yml";
  let response;
  try {
    response = await fetch(`https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/actions/workflows/${encodeURIComponent(workflow)}/dispatches`, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json", "User-Agent": "careeragent-cloud-control" },
      body: JSON.stringify({ ref: "main", inputs: { operation: "job_search", job_ref: "", portal, max_jobs: String(maxJobs), request_id: taskId, confirm_submit: "YES" } }),
    });
  } catch {
    await env.DB.prepare("UPDATE tasks SET status='failed',error=?,finished_at=?,updated_at=? WHERE task_id=?").bind("Could not reach GitHub Actions API", now(), now(), taskId).run();
    return Response.json({ detail: "Could not reach GitHub Actions. No job was started." }, { status: 502 });
  }
  if (response.status !== 204) {
    const error = `GitHub rejected workflow dispatch (HTTP ${response.status}). Check the Actions: write token permission and workflow file on main.`;
    await env.DB.prepare("UPDATE tasks SET status='failed',error=?,finished_at=?,updated_at=? WHERE task_id=?").bind(error, now(), now(), taskId).run();
    return Response.json({ detail: error }, { status: 502 });
  }
  return Response.json({ ok: true, task_id: taskId, portal, max_jobs: maxJobs, status: "queued" }, { status: 202 });
}
