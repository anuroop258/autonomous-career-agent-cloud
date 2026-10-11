const apiBase = "https://api.github.com";

function headers(env) {
  return {
    Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "careeragent-cloud-control",
  };
}

function config(env) {
  const owner = String(env.GH_REPO_OWNER || "").trim();
  const repo = String(env.GH_REPO_NAME || "").trim();
  const workflow = String(env.GH_WORKFLOW_FILE || "free-cloud-run.yml").trim();
  const token = String(env.GH_DISPATCH_TOKEN || "").trim();
  return owner && repo && token ? { owner, repo, workflow, token } : null;
}

export async function findWorkflowRun(env, taskId) {
  const cfg = config(env);
  if (!cfg || !taskId) return null;
  const url = `${apiBase}/repos/${encodeURIComponent(cfg.owner)}/${encodeURIComponent(cfg.repo)}/actions/workflows/${encodeURIComponent(cfg.workflow)}/runs?branch=main&event=workflow_dispatch&per_page=100`;
  const response = await fetch(url, { headers: headers(env) });
  if (!response.ok) throw new Error(`GitHub workflow lookup failed (HTTP ${response.status})`);
  const payload = await response.json();
  const runs = Array.isArray(payload.workflow_runs) ? payload.workflow_runs : [];
  const matches = runs.filter((run) => {
    const title = `${run.display_title || ""} ${run.name || ""}`;
    return title.includes(taskId);
  });
  if (!matches.length) return null;
  matches.sort((a, b) => Number(b.run_number || b.id) - Number(a.run_number || a.id));
  const run = matches[0];
  return { id: String(run.id), status: run.status || "unknown", conclusion: run.conclusion || null, html_url: run.html_url || "" };
}

export async function getWorkflowRun(env, runId) {
  const cfg = config(env);
  if (!cfg || !runId) return null;
  const response = await fetch(`${apiBase}/repos/${encodeURIComponent(cfg.owner)}/${encodeURIComponent(cfg.repo)}/actions/runs/${encodeURIComponent(String(runId))}`, { headers: headers(env) });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`GitHub run lookup failed (HTTP ${response.status})`);
  const run = await response.json();
  return { id: String(run.id), status: run.status || "unknown", conclusion: run.conclusion || null, html_url: run.html_url || "" };
}

export async function cancelWorkflowRun(env, runId) {
  const cfg = config(env);
  if (!cfg || !runId) return { requested: false, reason: "GitHub cancellation is not configured" };
  const response = await fetch(`${apiBase}/repos/${encodeURIComponent(cfg.owner)}/${encodeURIComponent(cfg.repo)}/actions/runs/${encodeURIComponent(String(runId))}/cancel`, {
    method: "POST",
    headers: { ...headers(env), "Content-Type": "application/json" },
  });
  if (response.status === 202 || response.status === 204) return { requested: true };
  if (response.status === 409) {
    const current = await getWorkflowRun(env, runId);
    if (current?.status === "completed") return { requested: false, alreadyCompleted: true, run: current };
  }
  const details = (await response.text().catch(() => "")).slice(0, 300);
  throw new Error(`GitHub run cancellation failed (HTTP ${response.status})${details ? `: ${details}` : ""}`);
}

export function terminalTaskStatus(run) {
  if (!run || run.status !== "completed") return null;
  if (run.conclusion === "success") return "completed";
  if (run.conclusion === "cancelled" || run.conclusion === "skipped") return "cancelled";
  return "failed";
}
