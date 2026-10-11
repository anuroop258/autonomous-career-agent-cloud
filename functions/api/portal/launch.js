import { json, PORTALS } from "../../_lib/common.js";
export async function onRequestPost({ request }) {
  let body = {}; try { body = await request.json(); } catch {}
  const portal = String(body.portal || "").toLowerCase();
  if (!PORTALS.includes(portal)) return json({ detail: "Unknown portal" }, 400);
  return json({ detail: "Cloud mode does not launch a persistent local browser. Use Start cloud run to launch Playwright on GitHub Actions." }, 409);
}
