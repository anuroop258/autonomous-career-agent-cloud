import { json, allRows } from "../_lib/common.js";
export async function onRequestGet({ request, env }) {
  const company = new URL(request.url).searchParams.get("company");
  try { return json(company ? await allRows(env.DB,"SELECT * FROM recruiters WHERE lower(company) LIKE lower(?) ORDER BY company,name",`%${company}%`) : await allRows(env.DB,"SELECT * FROM recruiters ORDER BY company,name LIMIT 500")); }
  catch { return json([]); }
}
