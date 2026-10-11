import { json, firstRow } from "../../_lib/common.js";
export async function onRequestGet({ env }) {
  try {
    const row = await firstRow(env.DB, "SELECT value_json FROM app_documents WHERE doc_key='master_resume_tex'");
    const content = row ? JSON.parse(row.value_json) : "";
    return json({ path: "public-cloud/master_resume.tex", content: typeof content === "string" ? content : "" });
  } catch { return json({ path: "", content: "" }); }
}
