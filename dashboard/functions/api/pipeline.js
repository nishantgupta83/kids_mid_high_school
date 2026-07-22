// Per-opportunity pipeline status + proposal decisions. One KV key per record,
// last-write-wins with updated_at — right-sized for one family (no device merge).

const OPP_RE = /^opp-[a-z0-9-]{4,64}$/;
const PROPOSAL_RE = /^[a-z0-9][a-z0-9-]{2,80}$/;
const STATUSES = new Set(["new", "discuss", "applied", "enrolled", "passed"]);
const DECISIONS = new Set(["approve", "dismiss"]);

function authorized(request, env) {
  return Boolean(env.SYNC_KEY) && request.headers.get("x-sync-key") === env.SYNC_KEY;
}

async function listPrefix(env, prefix) {
  // Paginate — a truncated first page must never drop records (PSAT-Pari lesson).
  const out = {};
  let cursor;
  do {
    const page = await env.FAMILY_OPS.list({ prefix, cursor });
    for (const k of page.keys) {
      const raw = await env.FAMILY_OPS.get(k.name);
      if (!raw) continue;
      try {
        out[k.name.slice(prefix.length)] = JSON.parse(raw);
      } catch {
        // Corrupt record: skip, never break the listing.
      }
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return out;
}

export async function onRequestGet({ request, env }) {
  if (!authorized(request, env)) return new Response("unauthorized", { status: 401 });
  const [statuses, proposals] = await Promise.all([
    listPrefix(env, "opp:"),
    listPrefix(env, "proposal:"),
  ]);
  return new Response(JSON.stringify({ statuses, proposals }), {
    headers: { "Content-Type": "application/json", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store" },
  });
}

export async function onRequestPut({ request, env }) {
  if (!authorized(request, env)) return new Response("unauthorized", { status: 401 });
  let body;
  try {
    body = await request.json();
  } catch {
    return new Response("bad json", { status: 400 });
  }
  const now = new Date().toISOString();
  if (typeof body?.oppId === "string" && typeof body?.status === "string") {
    if (!OPP_RE.test(body.oppId) || !STATUSES.has(body.status)) {
      return new Response("bad request", { status: 400 });
    }
    await env.FAMILY_OPS.put(`opp:${body.oppId}`, JSON.stringify({ status: body.status, updated_at: now, by: "dashboard" }));
    return Response.json({ ok: true });
  }
  if (typeof body?.proposalId === "string" && typeof body?.decision === "string") {
    if (!PROPOSAL_RE.test(body.proposalId) || !DECISIONS.has(body.decision)) {
      return new Response("bad request", { status: 400 });
    }
    await env.FAMILY_OPS.put(`proposal:${body.proposalId}`, JSON.stringify({ decision: body.decision, updated_at: now, by: "dashboard" }));
    return Response.json({ ok: true });
  }
  return new Response("bad request", { status: 400 });
}
