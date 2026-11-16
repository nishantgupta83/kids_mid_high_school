// Site-wide gate: every page, script and list file needs the family code.
// /api/* is left alone (each API checks the x-sync-key header itself, and the Mac jobs and
// the watch app call it directly). robots.txt stays public.
//
// Signing in posts the code to /__login. When it matches the SYNC_KEY secret the browser gets
// a cookie "<expiry>.<signature>", signed with the code, so the cookie is never the code itself,
// it stops working after 60 days, and changing the code signs every device out.

const COOKIE = "sc_auth";
const LOGIN = "/__login";
const MAX_AGE = 60 * 24 * 3600; // seconds
const enc = new TextEncoder();

async function sign(secret, msg) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(msg)));
  return Array.from(mac, (b) => b.toString(16).padStart(2, "0")).join("");
}

function same(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function readCookie(request, name) {
  for (const part of (request.headers.get("cookie") || "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0 && part.slice(0, i).trim() === name) return part.slice(i + 1).trim();
  }
  return "";
}

async function validCookie(request, secret) {
  const [exp, sig] = readCookie(request, COOKIE).split(".");
  if (!/^\d{1,12}$/.test(exp || "") || Number(exp) * 1000 < Date.now()) return false;
  return same(sig, await sign(secret, "page:" + exp));
}

// Only a path on this site: "/x", never "//host", "/\host", a full address, spaces, tabs or
// non-ASCII (browsers drop tabs and newlines, so "/<tab>/host" would become "//host").
const safeNext = (n) => (typeof n === "string" && /^\/(?![\/\\])[\x21-\x7e]*$/.test(n) && n.length <= 300 ? n : "/");

// API paths the pages and jobs really use: plain letters, digits, dashes and slashes, no "..".
const isApi = (path) => /^\/api\/[A-Za-z0-9_\-\/]*$/.test(path) && !path.includes("..");

const SECURITY = {
  "X-Robots-Tag": "noindex, nofollow",
  "X-Frame-Options": "DENY",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Cache-Control": "no-store",
};

const escAttr = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const PAGE_HEAD = `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow">
<title>Family dashboard</title>`;

function loginPage(next, error, status = 401) {
  // The typed code is held in this tab only (sessionStorage) until the server accepts it.
  const html = `${PAGE_HEAD}
<style>body{margin:0;background:#FBF7EE;color:#2A2A25;font:15px/1.45 -apple-system,'Helvetica Neue',Arial,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center}
form{width:290px;text-align:center}h1{font-family:Georgia,serif;color:#2F6F6A;font-size:22px}
input{width:100%;box-sizing:border-box;margin:10px 0;padding:9px;font-size:15px}
button{width:100%;padding:9px;border:0;border-radius:8px;background:#2F6F6A;color:#fff;font-weight:700;font-size:15px;cursor:pointer}
.err{color:#C96F4A;font-size:12px;min-height:16px}</style></head><body>
<form method="post" action="${LOGIN}" id="f">
<h1>Family dashboard</h1><p>Enter the family code</p>
<input name="code" id="code" type="password" autocomplete="current-password" placeholder="family code" required autofocus>
<input type="hidden" name="next" value="${escAttr(next)}">
<div class="err">${escAttr(error)}</div><button>Open</button></form>
<script>try{sessionStorage.removeItem("si.pending")}catch(e){}
document.getElementById("f").addEventListener("submit",function(){try{sessionStorage.setItem("si.pending",document.getElementById("code").value.trim())}catch(e){}});</script>
</body></html>`;
  return new Response(html, { status, headers: { ...SECURITY, "Content-Type": "text/html; charset=utf-8" } });
}

// After a good code: keep it where the pages read it ("si.code", as before) so their API calls
// work without asking again, then go on to the page that was asked for.
function signedInPage(next, cookie) {
  const html = `${PAGE_HEAD}<meta http-equiv="refresh" content="1;url=${escAttr(next)}"></head>
<body data-next="${escAttr(next)}"><script>try{var c=sessionStorage.getItem("si.pending");if(c){localStorage.setItem("si.code",c);sessionStorage.removeItem("si.pending")}}catch(e){}
location.replace(document.body.getAttribute("data-next"));</script></body></html>`;
  return new Response(html, { status: 200, headers: { ...SECURITY, "Content-Type": "text/html; charset=utf-8", "Set-Cookie": cookie } });
}

export async function onRequest({ request, env, next }) {
  const url = new URL(request.url);
  const path = url.pathname;
  if (isApi(path) || path === "/robots.txt") return next();

  const secret = env.SYNC_KEY;
  if (!secret) return new Response("not configured", { status: 503, headers: SECURITY });

  if (path === LOGIN) {
    if (request.method !== "POST") return Response.redirect(url.origin + "/", 303);
    let form;
    try { form = await request.formData(); } catch { form = new FormData(); }
    const target = safeNext(form.get("next"));
    const code = String(form.get("code") || "").trim();
    if (!same(await sign(secret, "code:" + code), await sign(secret, "code:" + secret))) {
      return loginPage(target, "That code did not work.");
    }
    const exp = Math.floor(Date.now() / 1000) + MAX_AGE;
    const value = exp + "." + (await sign(secret, "page:" + exp));
    return signedInPage(target, `${COOKIE}=${value}; Max-Age=${MAX_AGE}; Path=/; HttpOnly; Secure; SameSite=Lax`);
  }

  if (!(await validCookie(request, secret))) {
    // Files fetched by a page get a plain refusal; a page gets the sign-in form.
    if (/\.(json|js|css|txt|png|svg|ico)$/i.test(path)) return new Response("sign in first", { status: 401, headers: SECURITY });
    return loginPage(path + url.search, "");
  }

  const res = await next();
  const out = new Response(res.body, res);
  out.headers.set("Cache-Control", "private, no-store");
  return out;
}
