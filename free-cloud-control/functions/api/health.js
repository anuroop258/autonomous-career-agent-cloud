export async function onRequestGet({ env }) {
  const d1Ready = !!env.DB;
  return Response.json({ ok: d1Ready, service: "career-agent-free-control", database_configured: d1Ready }, { status: d1Ready ? 200 : 503, headers: { "Cache-Control": "no-store" } });
}
