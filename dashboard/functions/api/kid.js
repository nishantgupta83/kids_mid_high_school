// Dhruv homework done/later + streak. Per-key KV (hw:<date>:<id>) so two fast taps
// can't lost-update a shared map; streak bridges weekends but resets on a missed school day.
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const HWID = /^[a-z0-9:_-]{1,80}$/i;
function authorized(request, env) {
  return Boolean(env.SYNC_KEY) && request.headers.get("x-sync-key") === env.SYNC_KEY;
}
const H = { "Content-Type": "application/json", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store" };
function dayDiff(a, b) { return Math.round((Date.parse(a + "T00:00:00Z") - Date.parse(b + "T00:00:00Z")) / 86400000); }
// True iff every calendar day strictly between `from` and `to` is a weekend (Sat/Sun).
function interveningAllWeekend(from, to) {
  for (let d = dayDiff(to, from) - 1; d >= 1; d--) {
    const day = new Date(Date.parse(from + "T00:00:00Z") + d * 86400000).getUTCDay(); // 0=Sun..6=Sat
    if (day !== 0 && day !== 6) return false;
  }
  return true;
}

export async function onRequestGet({ request, env }) {
  if (!authorized(request, env)) return new Response("unauthorized", { status: 401 });
  const date = new URL(request.url).searchParams.get("date") || "";
  if (!DATE.test(date)) return new Response("bad date", { status: 400 });
  const prefix = `hw:${date}:`, map = {};
  let cursor;
  do {
    const page = await env.FAMILY_OPS.list({ prefix, cursor });
    for (const k of page.keys) {
      const raw = await env.FAMILY_OPS.get(k.name);
      if (raw) { try { map[k.name.slice(prefix.length)] = JSON.parse(raw); } catch {} }
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  const streak = await env.FAMILY_OPS.get("streak:dhruv");
  return new Response(JSON.stringify({ homework: map, streak: streak ? JSON.parse(streak) : { count: 0, lastDate: null } }), { headers: H });
}

export async function onRequestPut({ request, env }) {
  if (!authorized(request, env)) return new Response("unauthorized", { status: 401 });
  let b;
  try { b = await request.json(); } catch { return new Response("bad json", { status: 400 }); }
  if (!DATE.test(b?.date || "")) return new Response("bad date", { status: 400 });
  const now = new Date().toISOString();

  if (b.allDone === true) {
    const raw = await env.FAMILY_OPS.get("streak:dhruv");
    let s = raw ? JSON.parse(raw) : { count: 0, lastDate: null };
    if (!s.lastDate || dayDiff(b.date, s.lastDate) > 0) {  // ignore same-day + backdated ticks
      if (s.lastDate && interveningAllWeekend(s.lastDate, b.date)) s = { count: s.count + 1, lastDate: b.date }; // consecutive school day
      else s = { count: 1, lastDate: b.date };              // first tick or a missed school day
      await env.FAMILY_OPS.put("streak:dhruv", JSON.stringify(s));
    }
    return new Response(JSON.stringify({ ok: true }), { headers: H });
  }

  if (!HWID.test(b?.homeworkId || "") || !["done", "later"].includes(b?.status)) return new Response("bad request", { status: 400 });
  await env.FAMILY_OPS.put(`hw:${b.date}:${b.homeworkId}`, JSON.stringify({ status: b.status, at: now }));
  return new Response(JSON.stringify({ ok: true }), { headers: H });
}
