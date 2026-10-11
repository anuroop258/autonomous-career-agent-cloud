import { json } from "../../../_lib/common.js";
export async function onRequestPost() {
  return json({ ok: false, message: "Indeed human-verification continuation is not yet implemented in the on-demand runner. Do not start another run until the current task finishes." }, 501);
}
