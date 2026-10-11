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

function corsHeaders(request, env) {
  const url = new URL(request.url);
  const origin = request.headers.get("Origin");
  const allowed = (env.CORS_ORIGIN || url.origin).split(",").map((v) => v.trim()).filter(Boolean);
  const headers = {};
  if (origin && allowed.includes(origin)) {
    headers["Access-Control-Allow-Origin"] = origin;
    headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key, X-Automation-Password";
    headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS";
    headers["Vary"] = "Origin";
  }
  return headers;
}

function unauthorized(message, status, cors) {
  return json({ detail: message }, status, cors);
}

export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);
  if (!url.pathname.startsWith("/api/")) return context.next();

  const cors = corsHeaders(request, env);
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

  const pathname = url.pathname.replace(/\/+$/, "") || "/";
  const internalRoute = pathname.startsWith("/api/worker/") || pathname === "/api/data/sync";
  const resumeTailoringAction = /^\/api\/jobs\/[^/]+\/tailor-resume$/.test(pathname);
  const automationAction = request.method !== "GET" && (
    [
      "/api/automation/start",
      "/api/automation/stop",
      "/api/automation/indeed/continue",
      "/api/portal/launch",
    ].includes(pathname) || resumeTailoringAction
  );

  // Public read APIs and ordinary dashboard interactions intentionally remain public.
  // Internal runner callbacks/data sync use the integration key; only remote automation
  // actions use the owner's chosen password.
  if (internalRoute) {
    const key = env.DASHBOARD_API_KEY || env.CLOUD_CONTROL_API_KEY || "";
    const supplied = request.headers.get("X-API-Key") || "";
    if (!key) return unauthorized("Internal API secret is not configured", 503, cors);
    if (!safeEqual(key, supplied)) return unauthorized("Invalid internal API key", 401, cors);
  }
  if (automationAction) {
    const password = env.AUTOMATION_PASSWORD || "";
    const supplied = request.headers.get("X-Automation-Password") || "";
    if (!password) return unauthorized("The owner has not configured AUTOMATION_PASSWORD in Cloudflare Production secrets", 503, cors);
    if (!safeEqual(password, supplied)) return unauthorized("Incorrect automation password", 401, cors);
  }

  try {
    const response = await context.next();
    const headers = new Headers(response.headers);
    for (const [key, value] of Object.entries(cors)) headers.set(key, value);
    headers.set("Cache-Control", "no-store");
    const contentType = headers.get("content-type") || "";
    // Never let a missing API endpoint return the SPA index.html; the UI then gets a
    // precise JSON error rather than `Unexpected token '<'`.
    const isAllowedFile = pathname.endsWith("/resume-file") && contentType.includes("application/pdf");
    if (!contentType.includes("application/json") && !isAllowedFile) {
      return json({ detail: `Cloud API route not found or not JSON: ${pathname}` }, response.status === 200 ? 404 : response.status, cors);
    }
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  } catch (error) {
    return json({ detail: "Cloud API handler failed. Check the Cloudflare Pages Functions logs." }, 500, cors);
  }
}
