import { json } from "../../_lib/common.js";
export async function onRequestPost() { return json({ detail: "Email sending is not configured for the free cloud deployment. No email was sent." }, 501); }
