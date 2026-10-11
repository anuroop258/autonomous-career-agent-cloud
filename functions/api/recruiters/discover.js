import { json } from "../../_lib/common.js";

export async function onRequestPost() {
  // The legacy local backend intentionally returns no discovered contacts. Keep this
  // endpoint JSON-shaped and truthful until a public-source search provider is configured.
  return json({ discovered: {}, message: "Recruiter discovery is not configured in this deployment. No email addresses were guessed or fabricated." });
}
