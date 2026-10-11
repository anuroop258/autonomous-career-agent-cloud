import { json, firstRow, getConfig } from "../_lib/common.js";
export async function onRequestGet({ env }) {
  if (!env.DB) return json({ overall: "FAIL", checks: [{ name: "d1", status: "FAIL", detail: "D1 binding DB is missing" }], run: "idle" }, 503);
  const checks = [{ name: "cloudflare_pages", status: "OK", detail: "Website is online" }];
  try { await firstRow(env.DB, "SELECT task_id FROM tasks LIMIT 1"); await firstRow(env.DB, "SELECT task_id FROM task_details LIMIT 1"); checks.push({ name: "d1_task_queue", status: "OK", detail: "D1 task queue and operation metadata are reachable" }); }
  catch { checks.push({ name: "d1_task_queue", status: "FAIL", detail: "Run migrations/0002_dashboard_data.sql and verify the tasks table" }); }
  try { await firstRow(env.DB, "SELECT job_ref FROM jobs LIMIT 1"); checks.push({ name: "dashboard_data", status: "OK", detail: "Jobs table reachable" }); }
  catch { checks.push({ name: "dashboard_data", status: "WARN", detail: "Dashboard data schema has not been initialized" }); }
  checks.push({ name: "browser_runner", status: "WARN", detail: "Playwright runs on-demand in GitHub Actions, not in the Pages function" });
  const failed = checks.some(x => x.status === "FAIL");
  const warned = checks.some(x => x.status === "WARN");
  let run = "idle";
  try { const row = await firstRow(env.DB, "SELECT status FROM tasks WHERE status IN ('queued','running','stopping') ORDER BY requested_at DESC LIMIT 1"); if (row) run = row.status; } catch {}
  return json({ overall: failed ? "FAIL" : warned ? "WARN" : "OK", checks, run });
}
