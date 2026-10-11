function json(data, status = 200, extra = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...extra },
  });
}

function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length || !a.length) return false;
  let mismatch = 0;
  for (let i = 0; i < a.length; i++) mismatch |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return mismatch === 0;
}

export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  if (!url.pathname.startsWith("/api/")) return context.next();

  const origin = request.headers.get("Origin");
  const allowedOrigin = env.CORS_ORIGIN || url.origin;
  const cors = {};
  if (origin && origin === allowedOrigin) {
    cors["Access-Control-Allow-Origin"] = allowedOrigin;
    cors["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key";
    cors["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS";
    cors["Vary"] = "Origin";
  }
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
  if (url.pathname === "/api/health" || url.pathname === "/api/auth/status") return context.next();

  const expected = env.DASHBOARD_API_KEY;
  const supplied = request.headers.get("X-API-Key") || "";
  if (!expected || !safeEqual(expected, supplied)) return json({ detail: "Invalid or missing API key" }, 401, cors);

  try {
    const response = await context.next();
    const headers = new Headers(response.headers);
    for (const [key, value] of Object.entries(cors)) headers.set(key, value);
    headers.set("Cache-Control", "no-store");
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  } catch (error) {
    return json({ detail: "Internal control API error" }, 500, cors);
  }
}
