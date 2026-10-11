import { json, getConfig } from "../_lib/common.js";
export async function onRequestGet({ env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  const cfg = await getConfig(env.DB);
  // Never return private credentials/config. This is the public-facing UI configuration only.
  delete cfg.master_resume_content;
  delete cfg.resume_content_bank;
  delete cfg.contact;
  delete cfg.email;
  return json(cfg);
}
