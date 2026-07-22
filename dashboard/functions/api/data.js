// Content + health document API. Agent PUTs after each scan; the page GETs on load.
// All access requires the family code (x-sync-key vs the SYNC_KEY Pages secret).

function authorized(request, env) {
  return Boolean(env.SYNC_KEY) && request.headers.get("x-sync-key") === env.SYNC_KEY;
}

export async function onRequestGet({ request, env }) {
  if (!authorized(request, env)) return new Response("unauthorized", { status: 401 });
  const [content, health] = await Promise.all([
    env.FAMILY_OPS.get("content:latest"),
    env.FAMILY_OPS.get("health:latest"),
  ]);
  return new Response(
    JSON.stringify({
      content: content ? JSON.parse(content) : null,
      health: health ? JSON.parse(health) : null,
    }),
    { headers: { "Content-Type": "application/json", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store" } }
  );
}

export async function onRequestPut({ request, env }) {
  if (!authorized(request, env)) return new Response("unauthorized", { status: 401 });
  let body;
  try {
    body = await request.json();
  } catch {
    return new Response("bad json", { status: 400 });
  }
  const writes = [];
  if (body?.content && typeof body.content === "object") {
    writes.push(env.FAMILY_OPS.put("content:latest", JSON.stringify(body.content)));
  }
  if (body?.health && typeof body.health === "object") {
    writes.push(env.FAMILY_OPS.put("health:latest", JSON.stringify(body.health)));
  }
  if (!writes.length) return new Response("nothing to write", { status: 400 });
  await Promise.all(writes);
  return Response.json({ ok: true, wrote: writes.length });
}
