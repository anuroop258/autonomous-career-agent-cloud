import { json, allRows, firstRow, getConfig, PORTALS } from "../_lib/common.js";

const uniqueStrings = (values, max = 100) => [...new Set((Array.isArray(values) ? values : [])
  .filter((v) => typeof v === "string")
  .map((v) => v.trim()).filter(Boolean))].slice(0, max);
const cleanTitle = (value) => { const s = String(value || "").trim(); return s.includes(" - ") ? s.split(" - ")[0].trim() : s; };

export async function onRequestGet({ env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  try {
    const cfg = await getConfig(env.DB);
    const saved = cfg.preferences && typeof cfg.preferences === "object" ? cfg.preferences : null;
    const preferences = {
      titles: uniqueStrings(saved?.titles ?? cfg.titles),
      locations: uniqueStrings(saved?.locations ?? cfg.locations),
      portals: uniqueStrings(saved?.portals ?? []).filter((p) => PORTALS.includes(p)),
      min_match: Math.max(0, Math.min(100, Number(saved?.min_match ?? 0) || 0)),
    };
    const rows = await allRows(env.DB, "SELECT title,location,platform FROM jobs ORDER BY updated_at DESC LIMIT 5000");
    const titles = new Map(); const locations = new Map();
    for (const row of rows) {
      const title = cleanTitle(row.title);
      if (title && title !== "Unknown role" && !/^https?:\/\//i.test(title)) titles.set(title, (titles.get(title) || 0) + 1);
      const location = String(row.location || "").trim();
      if (location) locations.set(location, (locations.get(location) || 0) + 1);
    }
    const suggested_titles = [...titles].map(([title, count]) => ({ title, count })).sort((a,b) => b.count - a.count || a.title.localeCompare(b.title)).slice(0,40);
    const known_locations = [...locations].map(([name, count]) => ({ name, count })).sort((a,b) => b.count - a.count || a.name.localeCompare(b.name)).slice(0,20);
    return json({ preferences, agent_titles: uniqueStrings(cfg.titles), suggested_titles, known_locations, portals: PORTALS, saved: Boolean(saved) });
  } catch (error) {
    return json({ detail: "Preferences could not be read. Apply migrations/0001_control.sql and migrations/0002_dashboard_data.sql to the D1 database." }, 503);
  }
}

export async function onRequestPut({ request, env }) {
  if (!env.DB) return json({ detail: "D1 binding DB is missing" }, 503);
  let body;
  try { body = await request.json(); } catch { return json({ detail: "Request body must be JSON" }, 400); }
  const preferences = {
    titles: uniqueStrings(body.titles),
    locations: uniqueStrings(body.locations),
    portals: uniqueStrings(body.portals).filter((p) => PORTALS.includes(p)),
    min_match: Math.max(0, Math.min(100, Number(body.min_match ?? 0) || 0)),
  };
  const now = new Date().toISOString();
  try {
    const old = await firstRow(env.DB, "SELECT config_json FROM app_config WHERE id=1");
    let cfg = {};
    if (old?.config_json) { try { cfg = JSON.parse(old.config_json); } catch { cfg = {}; } }
    cfg = { ...(cfg && typeof cfg === "object" && !Array.isArray(cfg) ? cfg : {}), preferences };
    await env.DB.prepare("INSERT INTO app_config(id,config_json,updated_at) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET config_json=excluded.config_json,updated_at=excluded.updated_at")
      .bind(JSON.stringify(cfg), now).run();
    // Cloudflare cannot edit the source machine's role_config.json. Never claim this updated the agent.
    return json({ ok: true, preferences, synced_to_agent: false });
  } catch (error) {
    return json({ detail: "Preferences could not be saved. Apply migrations/0002_dashboard_data.sql to the D1 database." }, 503);
  }
}
