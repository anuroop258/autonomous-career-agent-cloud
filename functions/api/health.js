import { json } from "../_lib/common.js";

export async function onRequestGet({ env }) {
  if (!env.DB) return json({ ok: false, service: "careeragent", database_configured: false, schema_ready: false }, 503);
  try {
    for (const [table, column] of [["tasks", "task_id"], ["task_details", "task_id"], ["jobs", "job_ref"], ["applications", "application_ref"], ["custom_qa", "id"], ["resume_versions", "id"], ["resume_files", "file_key"], ["log_events", "id"]]) {
      await env.DB.prepare(`SELECT ${column} FROM ${table} LIMIT 1`).first();
    }
    return json({ ok: true, service: "careeragent", database_configured: true, schema_ready: true });
  } catch {
    return json({ ok: false, service: "careeragent", database_configured: true, schema_ready: false, detail: "The D1 binding is present, but dashboard tables are missing. Run the complete free-cloud-control/schema.sql in the D1 Console, then publish dashboard data from your PC." }, 503);
  }
}
