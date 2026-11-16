// Run: node --test /Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school/dashboard/tests/middleware.test.mjs
// The site-wide gate: no page or list file is served without the family code.
import { test } from "node:test";
import assert from "node:assert/strict";
import { onRequest } from "../functions/_middleware.js";

const ENV = { SYNC_KEY: "test-family-code" };
const PAGE = "<title>Ridhi's Roadmap</title>";

async function run(url, { method = "GET", cookie, form, env = ENV } = {}) {
  let served = false;
  const headers = {};
  if (cookie) headers.cookie = cookie;
  let body;
  if (form) { body = new URLSearchParams(form); headers["content-type"] = "application/x-www-form-urlencoded"; }
  const request = new Request("https://site.example" + url, { method, headers, body });
  const res = await onRequest({ request, env, next: async () => { served = true; return new Response(PAGE, { headers: { "content-type": "text/html" } }); } });
  return { res, served, text: await res.clone().text() };
}

async function login(code = ENV.SYNC_KEY, next = "/roadmap") {
  return run("/__login", { method: "POST", form: { code, next } });
}
const cookieOf = (res) => (res.headers.get("set-cookie") || "").split(";")[0];
// After a good code the browser gets a short page that keeps the code and moves on.
const nextOf = (text) => (text.match(/data-next="([^"]*)"/) || [])[1];

test("API calls pass straight through: they carry their own key", async () => {
  for (const path of ["/api/roadmap", "/api/kid?date=2026-11-12", "/api/data"]) assert.equal((await run(path)).served, true, path);
});

test("odd API-looking paths do not skip the gate", async () => {
  for (const path of ["/api/..%2froadmap", "/api/%2e%2e/roadmap.html", "/API/x", "/api"]) {
    assert.equal((await run(path)).served, false, path);
  }
});

test("robots.txt stays public", async () => {
  assert.equal((await run("/robots.txt")).served, true);
});

test("a page without the cookie gets the login form, never the page", async () => {
  for (const path of ["/", "/roadmap", "/roadmap.html", "/index.html"]) {
    const { res, served, text } = await run(path);
    assert.equal(served, false, path);
    assert.equal(res.status, 401, path);
    assert.match(text, /<form[^>]+method="post"[^>]+action="\/__login"/i);
    assert.doesNotMatch(text, /ridhi|pari|gupta|roadmap'/i, "the login page names nobody");
  }
});

test("list files and scripts are refused without the cookie", async () => {
  for (const path of ["/lists/rit-bme.json", "/lists/index.json", "/roadmap-lib.js"]) {
    const { res, served } = await run(path);
    assert.equal(served, false, path);
    assert.equal(res.status, 401, path);
  }
});

test("a wrong code sets no cookie and keeps no code", async () => {
  const { res, served, text } = await login("guess");
  assert.equal(served, false);
  assert.equal(res.status, 401);
  assert.equal(res.headers.get("set-cookie"), null);
  assert.doesNotMatch(text, /localStorage\.setItem/);
});

test("HEAD without the cookie is refused too", async () => {
  assert.equal((await run("/roadmap", { method: "HEAD" })).served, false);
});

test("redirects and not-modified replies from the file server pass through intact", async () => {
  const cookie = cookieOf((await login()).res);
  for (const [status, headers] of [[308, { location: "/roadmap" }], [304, { etag: '"x"' }]]) {
    const request = new Request("https://site.example/roadmap.html", { headers: { cookie } });
    const res = await onRequest({ request, env: ENV, next: async () => new Response(null, { status, headers }) });
    assert.equal(res.status, status);
    for (const [k, v] of Object.entries(headers)) assert.equal(res.headers.get(k), v);
  }
});

test("the right code sets a locked-down cookie and returns to the page asked for", async () => {
  const { res, text } = await login();
  assert.equal(res.status, 200);
  assert.equal(nextOf(text), "/roadmap");
  assert.match(text, /localStorage\.setItem\("si\.code"/, "the code is kept only once it worked");
  const sc = res.headers.get("set-cookie");
  for (const part of ["HttpOnly", "Secure", "SameSite=Lax", "Path=/"]) assert.ok(sc.includes(part), part);
  assert.ok(!sc.includes(ENV.SYNC_KEY), "the cookie is not the code itself");
  const after = await run("/roadmap", { cookie: cookieOf(res) });
  assert.equal(after.served, true);
  assert.equal(after.res.status, 200);
  assert.match(after.res.headers.get("cache-control"), /no-store/);
});

test("the return address can only be a page on this site", async () => {
  for (const next of ["//evil.example/x", "https://evil.example/", "/\\evil.example", "/\t/evil.example", "/\n/evil.example", "/é", "roadmap", ""]) {
    const { text } = await login(ENV.SYNC_KEY, next);
    assert.equal(nextOf(text), "/", JSON.stringify(next));
  }
});

test("a tampered, expired or old-code cookie is refused", async () => {
  const good = cookieOf((await login()).res);
  const [name, value] = good.split("=");
  const [exp, sig] = value.split(".");
  const tampered = `${name}=${Number(exp) + 1000}.${sig}`;
  for (const cookie of [tampered, `${name}=garbage`]) {
    assert.equal((await run("/roadmap", { cookie })).served, false, cookie);
  }
  // a correctly signed cookie stops working after 60 days
  const realNow = Date.now;
  try {
    Date.now = () => realNow() + 61 * 24 * 3600 * 1000;
    assert.equal((await run("/roadmap", { cookie: good })).served, false, "expired");
  } finally { Date.now = realNow; }
  assert.equal((await run("/roadmap", { cookie: good })).served, true, "still good today");
  // changing the family code signs everyone out
  assert.equal((await run("/roadmap", { cookie: good, env: { SYNC_KEY: "new-code" } })).served, false);
});

test("with no family code configured nothing is served", async () => {
  const { res, served } = await run("/roadmap", { env: {} });
  assert.equal(served, false);
  assert.equal(res.status, 503);
  const l = await run("/__login", { method: "POST", form: { code: "", next: "/" }, env: {} });
  assert.equal(l.res.headers.get("set-cookie"), null);
});
