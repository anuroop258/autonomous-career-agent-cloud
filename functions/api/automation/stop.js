import { findWorkflowRun, cancelWorkflowRun, terminalTaskStatus } from "../../_lib/github.js";

const now = () => new Date().toISOString();

export async function onRequestPost({ request, env }) {
  if (!env.DB) return Response.json({ detail: "D1 binding DB is missing" }, { status: 503 });
  let body = {}; try { body = await request.json(); } catch {}
  let taskId = String(body.task_id || "").trim();
  if (!taskId) {
    const active = await env.DB.prepare("SELECT task_id FROM tasks WHERE status IN ('queued','running','stopping') ORDER BY requested_at DESC LIMIT 1").first();
    taskId = active?.task_id || "";
  }
  if (!taskId) return Response.json({ detail: "There is no active cloud run to stop" }, { status: 409 });
  const row = await env.DB.prepare("SELECT task_id,status,github_run_id,stop_requested FROM tasks WHERE task_id=?").bind(taskId).first();
  if (!row) return Response.json({ detail: "Run not found" }, { status: 404 });
  if (!["queued", "running", "stopping"].includes(row.status)) return Response.json({ detail: `Run is already ${row.status}` }, { status: 409 });

  const stamp = now();
  await env.DB.prepare("UPDATE tasks SET stop_requested=1,status='stopping',updated_at=? WHERE task_id=? AND status IN ('queued','running','stopping')").bind(stamp, taskId).run();

  let runId = row.github_run_id ? String(row.github_run_id) : "";
  let run = null;
  try {
    if (!runId) {
      run = await findWorkflowRun(env, taskId);
      if (run?.id) {
        runId = run.id;
        await env.DB.prepare("UPDATE tasks SET github_run_id=?,updated_at=? WHERE task_id=?").bind(runId, now(), taskId).run();
      }
    }
    if (runId) {
      const cancel = await cancelWorkflowRun(env, runId);
      if (cancel.alreadyCompleted && cancel.run) {
        const finalStatus = terminalTaskStatus(cancel.run);
        if (finalStatus) {
          await env.DB.prepare("UPDATE tasks SET status=?,finished_at=COALESCE(finished_at,?),updated_at=? WHERE task_id=? AND status IN ('queued','running','stopping')")
            .bind(finalStatus, now(), now(), taskId).run();
          return Response.json({ ok: true, task_id: taskId, status: finalStatus, message: "GitHub workflow had already finished; task status reconciled." });
        }
      }
      return Response.json({ ok: true, task_id: taskId, status: "stopping", github_run_id: runId, message: "Stop requested and GitHub Actions cancellation was requested. The workflow callback or next status poll will mark the final state." }, { status: 202 });
    }
  } catch (error) {
    return Response.json({ ok: true, task_id: taskId, status: "stopping", message: "Stop flag is recorded, but GitHub cancellation could not yet be confirmed. Status polling will retry reconciliation.", warning: String(error?.message || "GitHub cancellation unavailable") }, { status: 202 });
  }
  return Response.json({ ok: true, task_id: taskId, status: "stopping", message: "Stop flag is recorded. The workflow run ID is not visible yet; status polling will locate and cancel it when GitHub publishes the run." }, { status: 202 });
}
