// Roadmap API. Two kinds of data, two writers, never mixed:
//   roadmap:content  — one document written by roadmap/push.py on the Mac
//   rm:<kind>:<id>   — one small record per item, written only by the roadmap page
//                      (status, note, decision, shortlist, course picks, added items)
// A content write never touches an rm: key, and a page write never touches the content.
// All access requires the family code (x-sync-key vs the SYNC_KEY Pages secret).

const MAX_CONTENT_BYTES = 400_000;
const ID_RE = /^(app|dec|sum|mon|opt|q|fam|lst|flag|plan|custom):[a-z0-9][a-z0-9-]{1,60}$/;
const ISO_RE = /^\d{4}-\d{2}-\d{2}$/;
const COURSE_RE = /^[a-z0-9][a-z0-9-]{1,60}$/;
const STATUSES = new Set(["not_started", "in_progress", "submitted", "accepted", "declined", "dropped", "done"]);
const OWNERS = new Set(["", "parent", "ridhi", "both"]);
const TRACKS = new Set(["research", "clinical", "music", "project", "college", "scholarship", "other"]);
const JSON_HEADERS = { "Content-Type": "application/json", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store" };

function authorized(request, env) {
  return Boolean(env.SYNC_KEY) && request.headers.get("x-sync-key") === env.SYNC_KEY;
}

const bad = (why) => new Response("bad request: " + why, { status: 400 });
const text = (v, max) => typeof v === "string" && v.length <= max;
// A real calendar date: 2027-02-30 and 2026-13-45 match the pattern but are refused.
const realDate = (s) => typeof s === "string" && ISO_RE.test(s) && new Date(s + "T00:00:00Z").toISOString().slice(0, 10) === s;

function httpUrl(u) {
  try {
    const p = new URL(u);
    return p.protocol === "https:" || p.protocol === "http:";
  } catch {
    return false;
  }
}

async function listPrefix(env, prefix) {
  // Paginate — a truncated first page must never drop records. Values are read in bulk
  // (up to 100 keys per call) so the number of store operations stays small however many
  // records the page has written.
  const names = [];
  let cursor;
  do {
    const page = await env.FAMILY_OPS.list({ prefix, cursor });
    for (const k of page.keys) names.push(k.name);
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  const out = {};
  for (let i = 0; i < names.length; i += 100) {
    const chunk = names.slice(i, i + 100);
    let values;
    try {
      values = await env.FAMILY_OPS.get(chunk);
      if (!(values instanceof Map)) throw new Error("no bulk read");
    } catch {
      // Bulk read unavailable: fall back to one read per key rather than fail the page.
      values = new Map();
      for (const name of chunk) values.set(name, await env.FAMILY_OPS.get(name));
    }
    for (const [name, raw] of values) {
      if (!raw) continue;
      try {
        out[name.slice(prefix.length)] = JSON.parse(raw);
      } catch {
        // Corrupt record: skip, never break the listing.
      }
    }
  }
  return out;
}

// Returns a clean patch object, or a string saying what is wrong. Unknown fields are
// refused rather than dropped, so a typo in the page shows up as an error, not a silent no-op.
function cleanPatch(id, patch) {
  if (!patch || typeof patch !== "object" || Array.isArray(patch)) return "patch must be an object";
  const kind = id.split(":")[0];
  const out = {};
  for (const [k, v] of Object.entries(patch)) {
    if (k === "status") {
      if (!STATUSES.has(v)) return "status";
      out.status = v;
    } else if (k === "note") {
      if (!text(v, 1000)) return "note";
      out.note = v;
    } else if (k === "choice") {
      if (!text(v, 300)) return "choice";
      out.choice = v;
    } else if (k === "owner") {
      if (!OWNERS.has(v)) return "owner";
      out.owner = v;
    } else if (k === "shortlist" || k === "seen" || k === "deleted") {
      if (typeof v !== "boolean") return k;
      out[k] = v;
    } else if (k === "courses") {
      if (kind !== "plan" || !Array.isArray(v) || v.length > 14 || !v.every((c) => typeof c === "string" && COURSE_RE.test(c))) return "courses";
      out.courses = v;
    } else if (k === "item") {
      if (kind !== "custom" || !v || typeof v !== "object" || Array.isArray(v)) return "item";
      if (!text(v.title, 140) || !v.title.trim()) return "item.title";
      const item = { title: v.title.trim() };
      if (v.deadline !== undefined && v.deadline !== "") {
        if (!realDate(v.deadline)) return "item.deadline";
        item.deadline = v.deadline;
      }
      if (v.track !== undefined) {
        if (!TRACKS.has(v.track)) return "item.track";
        item.track = v.track;
      }
      if (v.link !== undefined && v.link !== "") {
        if (!text(v.link, 400) || !httpUrl(v.link)) return "item.link";
        item.link = v.link;
      }
      out.item = item;
    } else {
      return "unknown field " + k;
    }
  }
  if (!Object.keys(out).length) return "empty patch";
  return out;
}

export async function onRequestGet({ request, env }) {
  if (!authorized(request, env)) return new Response("unauthorized", { status: 401 });
  const [content, state] = await Promise.all([env.FAMILY_OPS.get("roadmap:content"), listPrefix(env, "rm:")]);
  let doc = null;
  try {
    doc = content ? JSON.parse(content) : null;
  } catch {
    doc = null;
  }
  return new Response(JSON.stringify({ content: doc, state }), { headers: JSON_HEADERS });
}

export async function onRequestPut({ request, env }) {
  if (!authorized(request, env)) return new Response("unauthorized", { status: 401 });
  let raw, body;
  try {
    raw = await request.text();
    body = JSON.parse(raw);
  } catch {
    return bad("json");
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) return bad("body");
  const hasContent = body.content !== undefined;
  const hasItem = body.id !== undefined || body.patch !== undefined;
  if (hasContent === hasItem) return bad("send either content, or id + patch");

  if (hasContent) {
    if (!body.content || typeof body.content !== "object" || Array.isArray(body.content)) return bad("content");
    const doc = JSON.stringify(body.content);
    if (doc.length > MAX_CONTENT_BYTES) return bad("content too large");
    await env.FAMILY_OPS.put("roadmap:content", doc);
    return Response.json({ ok: true, bytes: doc.length });
  }

  if (typeof body.id !== "string" || !ID_RE.test(body.id)) return bad("id");
  const patch = cleanPatch(body.id, body.patch);
  if (typeof patch === "string") return bad(patch);
  const key = "rm:" + body.id;
  let current = {};
  try {
    const existing = await env.FAMILY_OPS.get(key);
    if (existing) current = JSON.parse(existing) || {};
  } catch {
    current = {}; // a corrupt record is replaced by this write
  }
  const next = { ...current, ...patch, updated_at: new Date().toISOString() };
  await env.FAMILY_OPS.put(key, JSON.stringify(next));
  return Response.json({ ok: true, record: next });
}
