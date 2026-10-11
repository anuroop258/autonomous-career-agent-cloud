export async function onRequestGet({ env }) {
  return Response.json(
    { auth_required: Boolean(env.DASHBOARD_API_KEY) },
    { headers: { "Cache-Control": "no-store" } }
  );
}
