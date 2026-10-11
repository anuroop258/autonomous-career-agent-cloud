const PORTALS = new Set(["naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"]);
const now = () => new Date().toISOString();

export async function onRequestPost({ request, env }) {
  if (!env.DB || !env.GH_DISPATCH_TOKEN || !env.GH_REPO_OWNER || !env.GH_REPO_NAME) {
    return Response.json({ detail: "Cloud control is not configured. Finish the Pages environment variables and D1 binding first." }, { status: 503 });
  }
  let body;
  try { body = await request.json(); } catch { return Response.json({ detail: "Request body must be JSON" }, { status: 400 }); }
  const portal = String(body.portal || "").toLowerCase();
  const maxJobs = Number.parseInt(String(body.max_jobs ?? "1"), 10);
  if (!PORTALS.has(portal)) return Response.json({ detail: "Unsupported portal" }, { status: 400 });
  if (!Number.isInteger(maxJobs) || maxJobs < 1 || maxJobs > 5) return Response.json({ detail: "max_jobs must be from 1 to 5" }, { status: 400 });
  if (body.confirmed !== true) return Response.json({ detail: "Explicit confirmation is required before starting a run" }, { status: 400 });

  const active = await env.DB.prepare("SELECT task_id, status FROM tasks WHERE status IN ('queued','running','stopping') ORDER BY requested_at DESC LIMIT 1").first();
  if (active) return Response.json({ detail: `Run ${active.task_id} is already ${active.status}. Wait until it finishes.` }, { status: 409 });

  const taskId = crypto.randomUUID();
  const timestamp = now();
  await env.DB.prepare("INSERT INTO tasks (task_id,portal,max_jobs,status,requested_at,updated_at) VALUES (?,?,?,'queued',?,?)")
    .bind(taskId, portal, maxJobs, timestamp, timestamp).run();

  const owner = env.GH_REPO_OWNER;
  const repo = env.GH_REPO_NAME;
  const workflow = env.GH_WORKFLOW_FILE || "free-cloud-run.yml";
  let dispatchResponse;
  try {
    dispatchResponse = await fetch(`https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/actions/workflows/${encodeURIComponent(workflow)}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "career-agent-free-control",
      },
      body: JSON.stringify({ ref: "main", inputs: { portal, max_jobs: String(maxJobs), request_id: taskId, confirm_submit: "YES" } }),
    });
  } catch {
    await env.DB.prepare("UPDATE tasks SET status='failed', error=?, finished_at=?, updated_at=? WHERE task_id=?")
      .bind("Could not reach GitHub Actions API", now(), now(), taskId).run();
    return Response.json({ detail: "Could not reach GitHub Actions. No job was started." }, { status: 502 });
  }

  if (dispatchResponse.status !== 204) {
    await env.DB.prepare("UPDATE tasks SET status='failed', error=?, finished_at=?, updated_at=? WHERE task_id=?")
      .bind(`GitHub rejected workflow dispatch (HTTP ${dispatchResponse.status})`, now(), now(), taskId).run();
    return Response.json({ detail: `GitHub rejected workflow dispatch (HTTP ${dispatchResponse.status}). Check the fine-grained token's Actions: write permission and the workflow file on main.` }, { status: 502 });
  }
  return Response.json({ ok: true, task_id: taskId, portal, max_jobs: maxJobs, status: "queued" }, { status: 202 });
}
