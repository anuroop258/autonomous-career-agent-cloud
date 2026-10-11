import { json, PORTALS } from "../../_lib/common.js";
export async function onRequestPost({ request }) {
  const portal = new URL(request.url).searchParams.get("portal") || "";
  if (!PORTALS.includes(portal)) return json({ detail: "Unknown portal" }, 404);
  return json({ portal, port: 0, connected: false, remote: true, message: "The temporary cloud runner starts only when a run is dispatched." });
}
