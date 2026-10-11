import { json, PORTALS, getConfig } from "../../_lib/common.js";
export async function onRequestGet({ env }) {
  const cfg = env.DB ? await getConfig(env.DB) : null;
  const output = {};
  for (const portal of PORTALS) output[portal] = { port: cfg?.portals?.[portal]?.cdp_port || 0, connected: false, remote: true };
  return json(output);
}
