// Dhruv's weekly recurring-activity schedule (parent-edited on the dashboard, read
// by the watch/web glance). One KV doc: activities:dhruv. Family-code auth like the rest.
const ID = /^act-[a-z0-9-]{2,40}$/;
const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;
function authorized(request, env) {
  return Boolean(env.SYNC_KEY) && request.headers.get("x-sync-key") === env.SYNC_KEY;
}
const H = { "Content-Type": "application/json", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store" };

export async function onRequestGet({ request, env }) {
  if (!authorized(request, env)) return new Response("unauthorized", { status: 401 });
  const raw = await env.FAMILY_OPS.get("activities:dhruv");
  return new Response(JSON.stringify({ activities: raw ? JSON.parse(raw) : [] }), { headers: H });
}

export async function onRequestPut({ request, env }) {
  if (!authorized(request, env)) return new Response("unauthorized", { status: 401 });
  let body;
  try { body = await request.json(); } catch { return new Response("bad json", { status: 400 }); }
  const list = body?.activities;
  if (!Array.isArray(list) || list.length > 40) return new Response("bad request", { status: 400 });
  const clean = [];
  for (const a of list) {
    if (!a || typeof a !== "object") return new Response("bad item", { status: 400 });
    if (!ID.test(a.id) || typeof a.name !== "string" || a.name.length > 60) return new Response("bad item", { status: 400 });
    if (!Array.isArray(a.days) || a.days.some(d => !Number.isInteger(d) || d < 1 || d > 7)) return new Response("bad item", { status: 400 });
    if (a.time != null && !TIME.test(a.time)) return new Response("bad item", { status: 400 });
    clean.push({ id: a.id, name: a.name.slice(0, 60), days: a.days, time: a.time ?? null, place: (a.place || "").slice(0, 60) });
  }
  await env.FAMILY_OPS.put("activities:dhruv", JSON.stringify(clean));
  return new Response(JSON.stringify({ ok: true }), { headers: H });
}
