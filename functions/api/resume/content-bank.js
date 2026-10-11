import { json, firstRow } from "../../_lib/common.js";
const EMPTY = { schema_version: 1, purpose: "CareerAgent resume source content", source_documents: [], professional_summary_options: [], skill_options: [], keyword_options: {}, project_options: [], certification_options: [], selection_policy: {} };
export async function onRequestGet({ env }) {
  try {
    const row = await firstRow(env.DB, "SELECT value_json FROM app_documents WHERE doc_key='resume_content_bank'");
    if (!row) return json(EMPTY);
    return json(JSON.parse(row.value_json));
  } catch { return json(EMPTY); }
}
