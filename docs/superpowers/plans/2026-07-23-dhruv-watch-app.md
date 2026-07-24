# Dhruv's Apple Watch App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Dhruv (11) a glanceable, tap-only Apple Watch surface — today's homework with Done/Later + streak, his day's activities, and countdowns — fed by the existing family-dashboard KV API, with a spike-first gate because installing a custom app on a Family Setup watch is unproven.

**Architecture:** A shared **backend** (new Cloudflare Pages Functions + a dashboard weekly-activities editor + agent/digest integration) that is identical whether the client ends up native or web. A **feasibility spike** (Slice 0) decides the client: a standalone SwiftUI watchOS app if it installs on Dhruv's Family Setup watch, else a phone-sized auth-gated web glance. Backend tasks are TDD-tested against `wrangler pages dev`; the watchOS app is authored here and built/installed by the operator via Xcode with on-device QA (watchOS can't be unit-tested in this workflow).

**Tech Stack:** Cloudflare Pages Functions (JS) + Workers KV, vanilla-JS dashboard, Python agent (`/usr/bin/python3`), SwiftUI/watchOS, WidgetKit complications, `UNUserNotificationCenter`.

## Global Constraints

- Cloudflare account `cf4e17207cd036cd992130e86b339e24` — pin `CLOUDFLARE_ACCOUNT_ID` on every wrangler command. Direct-upload Pages only; never git-connect. Verify against the deployment URL first, then the project domain.
- Dashboard project: `school-compass` (`school-compass-anq.pages.dev`), KV binding `FAMILY_OPS`. All API access requires header `x-sync-key === env.SYNC_KEY`; current family code = `gupta-family`, stored in Keychain `school-intel-family-code`.
- Free tier only. No purple anywhere. No AI/assistant branding. noindex. First names only. `/usr/bin/python3` for agent code.
- The watch app is dev-signed (Apple Team `ZW6PP4YAN4`, automatic signing) → weekly re-sign. Family code is compiled in from a **gitignored** xcconfig, never committed.
- Existing files to respect: `dashboard/functions/api/{data,pipeline}.js`, `dashboard/public/index.html`, `agent/push_content.py`, `agent/send_digest.py`, `data/` state schema.

---

## Slice 0 — Feasibility spike (OPERATOR-RUN GATE)

This gate decides everything downstream. It is manual (needs the operator's Mac, Xcode, Apple ID, and Dhruv's actual Family Setup watch). Do not build Slice B-native until this passes.

### Task 0: Prove a custom watch app installs on Dhruv's Family Setup watch

**Files:**
- Create: `watch/spike/HelloDhruv/` (throwaway Xcode project — not committed unless it passes)

- [ ] **Step 1: Confirm the watch's watchOS version and model.** On the operator's iPhone: Watch app → General → About. Record `watchOS <version>` and model. This sets the deployment-target floor for every later watchOS API (complications, notifications).

- [ ] **Step 2: Create a minimal standalone watchOS app in Xcode.** File → New → Project → watchOS → App. Product name `HelloDhruv`. **Uncheck** "Include Companion iOS App" (must be standalone — there is no iPhone on Dhruv's side). Interface: SwiftUI. Set the deployment target to the version from Step 1. Replace `ContentView` body with `Text("Hi Dhruv")`.

- [ ] **Step 3: Sign it.** Target → Signing & Capabilities → Automatic, Team `ZW6PP4YAN4`.

- [ ] **Step 4: Attempt to install on Dhruv's watch.** With the watch on the charger and near the Mac, select the watch as the run destination in Xcode and Run. If the watch does not appear as a destination, in Xcode → Window → Devices and Simulators, check whether a Family Setup watch under a child Apple ID is listed/pairable for development.

- [ ] **Step 5: Record the outcome in the plan/RESUME.** One of:
  - **PASS** — the app installs and launches on Dhruv's watch. → Proceed to Slice A, then Slice B-native. Keep the spike project as the seed for Slice B-native.
  - **FAIL** — the watch won't accept a dev build (not a valid destination, provisioning blocked under the child Apple ID, etc.). → Proceed to Slice A, then **Slice B-web** (skip B-native). Write the exact failure into `docs/superpowers/plans/2026-07-23-dhruv-watch-app.md` under this task so it isn't re-attempted blindly.

**Gate:** Slice A is safe to build regardless of outcome (it serves both clients). The Slice-B branch is chosen here.

---

## Slice A — Shared backend (build regardless of spike outcome)

All Slice-A work is testable locally with `cd dashboard && npx wrangler pages dev public` (serves Functions + KV emulation) and `curl`. Use `CODE=gupta-family` in tests.

### Task A1: Weekly-activities KV + `/api/activities` endpoint

**Files:**
- Create: `dashboard/functions/api/activities.js`
- Test: `dashboard/functions/api/_test-activities.sh` (curl-based, committed as living doc)

**Interfaces:**
- Produces: `GET /api/activities` → `{ activities: Activity[] }`; `PUT /api/activities` body `{ activities: Activity[] }` → `{ ok: true }`. `Activity = { id: string(/^act-[a-z0-9-]{2,40}$/), name: string(≤60), days: number[] (1=Mon..7=Sun), time: "HH:MM"|null, place: string(≤60) }`. KV key `activities:dhruv`.
- Consumes: `env.FAMILY_OPS`, `env.SYNC_KEY` (existing bindings).

- [ ] **Step 1: Write the failing test** — `dashboard/functions/api/_test-activities.sh`:

```bash
#!/bin/bash
set -e
BASE="${1:-http://localhost:8788}"; CODE="${2:-gupta-family}"
echo "bare GET → 401"; test "$(curl -s -o /dev/null -w '%{http_code}' $BASE/api/activities)" = 401
echo "authed empty GET → {activities:[]}"; curl -s -H "x-sync-key: $CODE" $BASE/api/activities | grep -q '"activities"'
echo "PUT valid"; curl -s -X PUT -H "x-sync-key: $CODE" -H 'content-type: application/json' \
  -d '{"activities":[{"id":"act-badminton","name":"Badminton","days":[2,4],"time":"16:00","place":"Gym"}]}' $BASE/api/activities | grep -q '"ok":true'
echo "GET returns it"; curl -s -H "x-sync-key: $CODE" $BASE/api/activities | grep -q '"act-badminton"'
echo "PUT bad id → 400"; test "$(curl -s -o /dev/null -w '%{http_code}' -X PUT -H "x-sync-key: $CODE" -H 'content-type: application/json' -d '{"activities":[{"id":"BAD ID","name":"x","days":[9],"time":"25:00"}]}' $BASE/api/activities)" = 400
echo "ALL PASS"
```

- [ ] **Step 2: Run it to confirm it fails** — `bash dashboard/functions/api/_test-activities.sh` → fails (endpoint 404/500).

- [ ] **Step 3: Implement `dashboard/functions/api/activities.js`:**

```js
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
```

- [ ] **Step 4: Run the test to confirm it passes** — start `npx wrangler pages dev public` in `dashboard/`, then `bash dashboard/functions/api/_test-activities.sh` → `ALL PASS`.

- [ ] **Step 5: Commit** —

```bash
git add dashboard/functions/api/activities.js dashboard/functions/api/_test-activities.sh
git commit -m "feat(watch): /api/activities — Dhruv weekly-activity schedule in KV"
```

### Task A2: Weekly-activities editor on the dashboard

**Files:**
- Modify: `dashboard/public/index.html` (add an "Activities" management block on the Watchlist tab, reusing the existing `api()` helper, `esc()`, `badge()`, gate, and `.card`/`.sbtn` styles)

**Interfaces:**
- Consumes: `GET/PUT /api/activities` (Task A1); existing client `api(path, opts)` wrapper that injects `x-sync-key`.
- Produces: none (UI only).

- [ ] **Step 1: Add a render function + load call.** After the proposed-sources block in the Watchlist render, append an activities editor. In `render()` where `#tWatch` is built, append:

```js
// Dhruv's weekly activities editor (feeds the watch)
const DAYS = ["","Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
const acts = (window.ACTS || []);
$("#tWatch").innerHTML +=
  `<div class="sec sage">Dhruv's weekly activities</div>` +
  acts.map(a => `<div class="card">${esc(a.name)} <span class="muted">${a.days.map(d=>DAYS[d]).join(" ")}${a.time?" · "+esc(a.time):""}${a.place?" · "+esc(a.place):""}</span>` +
    ` <button class="sbtn" data-actdel="${esc(a.id)}">remove</button></div>`).join("") +
  `<div class="card"><input id="actName" placeholder="name (e.g. Badminton)" style="width:100%;margin:2px 0;padding:6px;border:1px solid var(--line);border-radius:6px">` +
  `<input id="actDays" placeholder="days e.g. 2,4 (Mon=1..Sun=7)" style="width:100%;margin:2px 0;padding:6px;border:1px solid var(--line);border-radius:6px">` +
  `<input id="actTime" placeholder="time HH:MM (optional)" style="width:100%;margin:2px 0;padding:6px;border:1px solid var(--line);border-radius:6px">` +
  `<input id="actPlace" placeholder="place (optional)" style="width:100%;margin:2px 0;padding:6px;border:1px solid var(--line);border-radius:6px">` +
  `<button class="sbtn on" id="actAdd">Add activity</button></div>`;
```

- [ ] **Step 2: Load activities on app open.** In `load()`, after fetching data/pipeline, add:

```js
try { window.ACTS = (await api("/api/activities")).activities || []; } catch { window.ACTS = []; }
```

- [ ] **Step 3: Wire add/remove in the document click handler** (next to the existing `data-prop` handling):

```js
if (t.id === "actAdd") {
  const name = $("#actName").value.trim();
  const days = $("#actDays").value.split(",").map(s => parseInt(s.trim(),10)).filter(d => d>=1 && d<=7);
  const time = $("#actTime").value.trim() || null;
  const place = $("#actPlace").value.trim();
  if (!name || !days.length) { alert("need a name and at least one day (1–7)"); return; }
  const id = "act-" + name.toLowerCase().replace(/[^a-z0-9]+/g,"-").slice(0,30).replace(/-+$/,"");
  window.ACTS = [...window.ACTS.filter(a=>a.id!==id), { id, name, days, time, place }];
  try { await api("/api/activities", { method:"PUT", body: JSON.stringify({ activities: window.ACTS }) }); render(); }
  catch { alert("save failed"); }
}
if (t.dataset?.actdel) {
  window.ACTS = window.ACTS.filter(a => a.id !== t.dataset.actdel);
  try { await api("/api/activities", { method:"PUT", body: JSON.stringify({ activities: window.ACTS }) }); render(); }
  catch { alert("save failed"); }
}
```

- [ ] **Step 4: Verify locally with Playwright-free manual check.** `npx wrangler pages dev public`, open `localhost:8788`, enter code, Watchlist tab → add "Badminton / 2,4 / 16:00 / Gym" → it appears and persists across reload (confirm via `curl -H "x-sync-key: gupta-family" localhost:8788/api/activities`).

- [ ] **Step 5: Commit** —

```bash
git add dashboard/public/index.html
git commit -m "feat(watch): dashboard editor for Dhruv's weekly activities"
```

### Task A3: Homework Done/Later write-back + streak — `/api/kid`

**Files:**
- Create: `dashboard/functions/api/kid.js`
- Test: `dashboard/functions/api/_test-kid.sh`

**Interfaces:**
- Produces:
  - `PUT /api/kid` body `{ date:"YYYY-MM-DD", homeworkId:string(/^[a-z0-9:_-]{1,80}$/), status:"done"|"later" }` → `{ ok:true }`. Stores KV `hw:<date>` = `{ [homeworkId]: { status, at } }`.
  - `PUT /api/kid` body `{ date, allDone:true }` → ticks KV `streak:dhruv` = `{ count, lastDate }` (idempotent per date; +1 if date == lastDate+1, reset to 1 on a gap, no-op if date == lastDate).
  - `GET /api/kid?date=YYYY-MM-DD` → `{ homework: {..}, streak: { count, lastDate } }`.
- Consumes: `env.FAMILY_OPS`, `env.SYNC_KEY`.

- [ ] **Step 1: Write the failing test** — `dashboard/functions/api/_test-kid.sh`:

```bash
#!/bin/bash
set -e
BASE="${1:-http://localhost:8788}"; CODE="${2:-gupta-family}"
D=2026-09-01
echo "bare 401"; test "$(curl -s -o /dev/null -w '%{http_code}' $BASE/api/kid)" = 401
echo "mark done"; curl -s -X PUT -H "x-sync-key: $CODE" -H 'content-type: application/json' -d "{\"date\":\"$D\",\"homeworkId\":\"evt-hw-1\",\"status\":\"done\"}" $BASE/api/kid | grep -q '"ok":true'
echo "GET reflects"; curl -s -H "x-sync-key: $CODE" "$BASE/api/kid?date=$D" | grep -q '"evt-hw-1"'
echo "streak tick"; curl -s -X PUT -H "x-sync-key: $CODE" -H 'content-type: application/json' -d "{\"date\":\"$D\",\"allDone\":true}" $BASE/api/kid | grep -q '"ok":true'
echo "streak=1"; curl -s -H "x-sync-key: $CODE" "$BASE/api/kid?date=$D" | grep -q '"count":1'
echo "same-day tick idempotent (still 1)"; curl -s -X PUT -H "x-sync-key: $CODE" -H 'content-type: application/json' -d "{\"date\":\"$D\",\"allDone\":true}" $BASE/api/kid >/dev/null; curl -s -H "x-sync-key: $CODE" "$BASE/api/kid?date=$D" | grep -q '"count":1'
echo "next-day tick → 2"; curl -s -X PUT -H "x-sync-key: $CODE" -H 'content-type: application/json' -d '{"date":"2026-09-02","allDone":true}' $BASE/api/kid >/dev/null; curl -s -H "x-sync-key: $CODE" "$BASE/api/kid?date=2026-09-02" | grep -q '"count":2'
echo "gap resets → 1"; curl -s -X PUT -H "x-sync-key: $CODE" -H 'content-type: application/json' -d '{"date":"2026-09-05","allDone":true}' $BASE/api/kid >/dev/null; curl -s -H "x-sync-key: $CODE" "$BASE/api/kid?date=2026-09-05" | grep -q '"count":1'
echo "bad status → 400"; test "$(curl -s -o /dev/null -w '%{http_code}' -X PUT -H "x-sync-key: $CODE" -H 'content-type: application/json' -d "{\"date\":\"$D\",\"homeworkId\":\"x\",\"status\":\"nope\"}" $BASE/api/kid)" = 400
echo "ALL PASS"
```

- [ ] **Step 2: Run it → fails** (`bash dashboard/functions/api/_test-kid.sh`).

- [ ] **Step 3: Implement `dashboard/functions/api/kid.js`:**

```js
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const HWID = /^[a-z0-9:_-]{1,80}$/i;
function authorized(request, env) {
  return Boolean(env.SYNC_KEY) && request.headers.get("x-sync-key") === env.SYNC_KEY;
}
const H = { "Content-Type": "application/json", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store" };
function dayDiff(a, b) { return Math.round((Date.parse(a + "T00:00:00Z") - Date.parse(b + "T00:00:00Z")) / 86400000); }

export async function onRequestGet({ request, env }) {
  if (!authorized(request, env)) return new Response("unauthorized", { status: 401 });
  const date = new URL(request.url).searchParams.get("date") || "";
  if (!DATE.test(date)) return new Response("bad date", { status: 400 });
  const [hw, streak] = await Promise.all([env.FAMILY_OPS.get(`hw:${date}`), env.FAMILY_OPS.get("streak:dhruv")]);
  return new Response(JSON.stringify({ homework: hw ? JSON.parse(hw) : {}, streak: streak ? JSON.parse(streak) : { count: 0, lastDate: null } }), { headers: H });
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
    if (s.lastDate === b.date) { /* idempotent */ }
    else if (s.lastDate && dayDiff(b.date, s.lastDate) === 1) s = { count: s.count + 1, lastDate: b.date };
    else s = { count: 1, lastDate: b.date };
    await env.FAMILY_OPS.put("streak:dhruv", JSON.stringify(s));
    return new Response(JSON.stringify({ ok: true }), { headers: H });
  }

  if (!HWID.test(b?.homeworkId || "") || !["done", "later"].includes(b?.status)) return new Response("bad request", { status: 400 });
  const raw = await env.FAMILY_OPS.get(`hw:${b.date}`);
  const map = raw ? JSON.parse(raw) : {};
  map[b.homeworkId] = { status: b.status, at: now };
  await env.FAMILY_OPS.put(`hw:${b.date}`, JSON.stringify(map));
  return new Response(JSON.stringify({ ok: true }), { headers: H });
}
```

- [ ] **Step 4: Run the test → `ALL PASS`.**

- [ ] **Step 5: Commit** —

```bash
git add dashboard/functions/api/kid.js dashboard/functions/api/_test-kid.sh
git commit -m "feat(watch): /api/kid — homework done/later status + streak"
```

### Task A4: Surface Dhruv's homework progress on the dashboard + digest

**Files:**
- Modify: `dashboard/public/index.html` (Today tab: a "Dhruv's homework" line reading `/api/kid?date=<today>`)
- Modify: `agent/push_content.py` (fold today's `hw:<date>` + streak into the digest summary source)
- Modify: `agent/send_digest.py` (one digest line)

**Interfaces:**
- Consumes: `GET /api/kid?date` (Task A3); existing content doc events (homework rows: `type=="homework"`, `kid in {dhruv,both}`).
- Produces: none.

- [ ] **Step 1: Dashboard Today line.** In the Today render, after the action/agenda blocks, add:

```js
// Dhruv homework progress (from /api/kid)
const today = localISO();
const hw = (c.events||[]).filter(e => e.type==="homework" && ["dhruv","both"].includes(e.kid) && e.date===today && e.status==="active");
if (hw.length) {
  api("/api/kid?date="+today).then(k => {
    const done = hw.filter(e => k.homework?.[e.id]?.status==="done").length;
    const el = document.createElement("div"); el.className="card";
    el.innerHTML = `${badge("dhruv")} Homework today: <b>${done}/${hw.length} done</b>` + (k.streak?.count?` · streak ${k.streak.count}`:"");
    $("#tToday").appendChild(el);
  }).catch(()=>{});
}
```

- [ ] **Step 2: Agent reads homework status for the digest.** In `agent/push_content.py`, the agent already talks to the API via `call(cfg, path)`. Add a helper used by `send_digest` instead — simplest: in `agent/send_digest.py` `collect()`, read the local last-known via a new field. But the status lives only in KV. Add to `push_content.py` a `--kidstatus` mode that GETs `/api/kid?date=<today>` and writes `data/local/kid_status.json` (`{done, total, streak}`) computed against today's homework events. Implement:

```python
def kidstatus(cfg):
    import datetime
    today = datetime.date.today().isoformat()
    events = read_json(os.path.join(DATA, "events.json"), {"events": []})["events"]
    hw = [e for e in events if e.get("type") == "homework" and e.get("kid") in ("dhruv", "both")
          and e.get("date") == today and e.get("status") == "active"]
    try:
        k = call(cfg, f"/api/kid?date={today}")
    except Exception as e:
        log(f"push_content: kidstatus fetch failed {e}"); return 0
    done = sum(1 for e in hw if (k.get("homework", {}).get(e["id"], {}) or {}).get("status") == "done")
    write_json(os.path.join(LOCAL, "kid_status.json"),
               {"date": today, "done": done, "total": len(hw), "streak": (k.get("streak") or {}).get("count", 0)})
    return 0
```

  Wire `--kidstatus` in `main()` (same pattern as `--pull`/`--push`) and call it from `scan.sh` right after the KV pull (step 3), guarded by `kv_enabled`.

- [ ] **Step 3: Digest line.** In `agent/send_digest.py` `collect()`, add:

```python
ks = read_json(os.path.join(LOCAL, "kid_status.json"), {})
if ks.get("date") != today.isoformat():
    ks = {}
```

  and return `"kid_status": ks` in the sections dict; in `render_html`/`render_text`, when `ks.get("total")`, emit a line: `Dhruv's homework: {done}/{total} done` + (`· {streak}-day streak` if streak). Text mirror.

- [ ] **Step 4: Verify.** Locally: seed one `type=homework kid=dhruv date=<today>` event, `PUT /api/kid` mark it done, run `push_content.py --kidstatus`, then `send_digest.py --mode full --dry-run` → the digest shows `Dhruv's homework: 1/1 done`. Dashboard Today shows the line.

- [ ] **Step 5: Commit** —

```bash
git add dashboard/public/index.html agent/push_content.py agent/send_digest.py agent/scan.sh
git commit -m "feat(watch): surface Dhruv's homework progress + streak on dashboard and digest"
```

### Task A5: Deploy the backend and confirm live

- [ ] **Step 1: Deploy.** `cd dashboard && CLOUDFLARE_ACCOUNT_ID=cf4e17207cd036cd992130e86b339e24 npx wrangler pages deploy`.
- [ ] **Step 2: Verify against the deployment URL first, then the domain** — run `_test-activities.sh` and `_test-kid.sh` against `https://<deployment>.school-compass-anq.pages.dev` (retry until the new deployment serves; per the propagation lesson). Then re-run against `https://school-compass-anq.pages.dev`.
- [ ] **Step 3: Commit** any deploy-note updates to `docs/runbook.md` (new endpoints, `activities:dhruv`, `hw:<date>`, `streak:dhruv` KV keys).

---

## Slice B-native — watchOS app (ONLY if Slice 0 PASSED)

Authored here; **built and installed by the operator via Xcode**, with on-device QA (no unit tests — watchOS UI can't be tested in this workflow). Project lives in `watch/DhruvWatch/`.

### Task B1: Project + family-code provisioning + data layer

**Files:**
- Create: `watch/DhruvWatch/` (Xcode watchOS app, standalone), `watch/DhruvWatch/Secrets.xcconfig` (gitignored), `watch/DhruvWatch/DhruvWatch/Api.swift`, `.gitignore` entry `watch/**/Secrets.xcconfig`

**Interfaces:**
- Produces: `ApiClient.fetchToday() async throws -> TodayData` where `TodayData = (homework: [HW], activities: [Act], countdowns: [String])`, `HW = (id, title, status: String?)`, `Act = (name, time)`. `ApiClient.setHomework(id, status)` / `ApiClient.tickStreak()`.
- Consumes: Slice A endpoints; `FAMILY_CODE` build setting.

- [ ] **Step 1: Create the standalone watchOS app** in Xcode (as in Task 0), product `DhruvWatch`, deployment target = the recorded watchOS version, Team `ZW6PP4YAN4`.

- [ ] **Step 2: Provision the family code without committing it.** Create `watch/DhruvWatch/Secrets.xcconfig`:

```
FAMILY_CODE = gupta-family
API_BASE = https:/$()/school-compass-anq.pages.dev
```

  (the `$()` splits `//` so xcconfig doesn't treat it as a comment). Set the target's Base Configuration to this file. Add `FAMILY_CODE`/`API_BASE` to Info.plist (`$(FAMILY_CODE)` / `$(API_BASE)`). Append to repo `.gitignore`: `watch/**/Secrets.xcconfig`. Provide a committed `Secrets.xcconfig.example` with placeholder values.

- [ ] **Step 3: Write `Api.swift`** (models + client):

```swift
import Foundation

struct HW: Identifiable { let id: String; let title: String; var status: String? }
struct Act: Identifiable { var id: String { name + time }; let name: String; let time: String }

struct TodayData { var homework: [HW]; var activities: [Act]; var countdowns: [String]; var streak: Int }

enum ApiClient {
    static var base: String { Bundle.main.object(forInfoDictionaryKey: "API_BASE") as? String ?? "" }
    static var code: String { Bundle.main.object(forInfoDictionaryKey: "FAMILY_CODE") as? String ?? "" }

    private static func req(_ path: String, method: String = "GET", body: Data? = nil) -> URLRequest {
        var r = URLRequest(url: URL(string: base + path)!)
        r.httpMethod = method
        r.setValue(code, forHTTPHeaderField: "x-sync-key")
        if let body { r.httpBody = body; r.setValue("application/json", forHTTPHeaderField: "content-type") }
        return r
    }

    static func fetchToday() async throws -> TodayData {
        let today = ISO8601DateFormatter.dateOnly(Date())
        async let dataResp = URLSession.shared.data(for: req("/api/data"))
        async let actResp  = URLSession.shared.data(for: req("/api/activities"))
        async let kidResp  = URLSession.shared.data(for: req("/api/kid?date=\(today)"))
        let content = try JSONSerialization.jsonObject(with: try await dataResp.0) as? [String: Any]
        let acts = try JSONSerialization.jsonObject(with: try await actResp.0) as? [String: Any]
        let kid = try JSONSerialization.jsonObject(with: try await kidResp.0) as? [String: Any]

        let events = ((content?["content"] as? [String: Any])?["events"] as? [[String: Any]]) ?? []
        let hwStatus = (kid?["homework"] as? [String: [String: Any]]) ?? [:]
        let homework = events.filter {
            ($0["type"] as? String) == "homework"
            && ["dhruv","both"].contains($0["kid"] as? String ?? "")
            && ($0["date"] as? String) == today
            && ($0["status"] as? String) == "active"
        }.map { HW(id: $0["id"] as? String ?? "", title: $0["title"] as? String ?? "",
                   status: (hwStatus[$0["id"] as? String ?? ""]?["status"]) as? String) }

        let weekday = { () -> Int in let w = Calendar.current.component(.weekday, from: Date()); return w == 1 ? 7 : w - 1 }() // 1=Mon..7=Sun
        let activities = ((acts?["activities"] as? [[String: Any]]) ?? [])
            .filter { ($0["days"] as? [Int] ?? []).contains(weekday) }
            .sorted { ($0["time"] as? String ?? "99") < ($1["time"] as? String ?? "99") }
            .map { Act(name: $0["name"] as? String ?? "", time: $0["time"] as? String ?? "") }

        let streak = ((kid?["streak"] as? [String: Any])?["count"] as? Int) ?? 0
        let countdowns = Countdowns.from(events: events)
        return TodayData(homework: homework, activities: activities, countdowns: countdowns, streak: streak)
    }

    static func setHomework(_ id: String, _ status: String) async {
        let today = ISO8601DateFormatter.dateOnly(Date())
        let body = try? JSONSerialization.data(withJSONObject: ["date": today, "homeworkId": id, "status": status])
        _ = try? await URLSession.shared.data(for: req("/api/kid", method: "PUT", body: body))
    }
    static func tickStreak() async {
        let today = ISO8601DateFormatter.dateOnly(Date())
        let body = try? JSONSerialization.data(withJSONObject: ["date": today, "allDone": true])
        _ = try? await URLSession.shared.data(for: req("/api/kid", method: "PUT", body: body))
    }
}

extension ISO8601DateFormatter { static func dateOnly(_ d: Date) -> String {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "America/Los_Angeles"); return f.string(from: d) } }

enum Countdowns {
    static func from(events: [[String: Any]]) -> [String] {
        var out: [String] = []
        let today = Date()
        let cal = Calendar.current
        // next weekend (Saturday)
        if let sat = cal.nextDate(after: today, matching: DateComponents(weekday: 7), matchingPolicy: .nextTime) {
            let d = cal.dateComponents([.day], from: cal.startOfDay(for: today), to: cal.startOfDay(for: sat)).day ?? 0
            if d > 0 { out.append("Weekend in \(d)d") }
        }
        // next break-type event
        let df = DateFormatter(); df.dateFormat = "yyyy-MM-dd"
        let breaks = events.filter { ($0["type"] as? String) == "break" }
            .compactMap { e -> (String, Date)? in guard let ds = e["date"] as? String, let dt = df.date(from: ds), dt > today else { return nil }; return (e["title"] as? String ?? "Break", dt) }
            .sorted { $0.1 < $1.1 }
        if let (title, dt) = breaks.first {
            let d = cal.dateComponents([.day], from: cal.startOfDay(for: today), to: cal.startOfDay(for: dt)).day ?? 0
            out.append("\(title) in \(d)d")
        }
        return Array(out.prefix(2))
    }
}
```

- [ ] **Step 4: On-device QA.** Build+run on Dhruv's watch. Expected: no crash; `ApiClient.fetchToday()` returns data (temporarily print counts in a debug `Text`). If TLS/network fails on the Family Setup watch, note it — the watch needs WiFi/cellular and outbound HTTPS to `school-compass-anq.pages.dev`.

- [ ] **Step 5: Commit** (code only; never the real Secrets.xcconfig):

```bash
git add watch/DhruvWatch watch/DhruvWatch/Secrets.xcconfig.example .gitignore
git commit -m "feat(watch): DhruvWatch app skeleton + API client (family code compiled in, gitignored)"
```

### Task B2: "Today" screen — homework list with Done/Later, activities, countdowns, streak

**Files:**
- Create: `watch/DhruvWatch/DhruvWatch/TodayView.swift`, `watch/DhruvWatch/DhruvWatch/Store.swift`
- Modify: the app's root view to show `TodayView` in a `TabView` (`.tabViewStyle(.page)`) with a second `WeekView`

**Interfaces:**
- Consumes: `ApiClient` (Task B1).
- Produces: `Store` (`@MainActor ObservableObject`) with `@Published var today: TodayData?`, `func load()`, `func mark(_ hw:HW, _ status:String)`.

- [ ] **Step 1: Write `Store.swift`:**

```swift
import SwiftUI

@MainActor final class Store: ObservableObject {
    @Published var today: TodayData?
    @Published var loading = false

    func load() {
        loading = true
        Task { today = try? await ApiClient.fetchToday(); loading = false; maybeTickStreak() }
    }
    func mark(_ hw: HW, _ status: String) {
        guard var t = today, let i = t.homework.firstIndex(where: { $0.id == hw.id }) else { return }
        t.homework[i].status = status; today = t
        Task { await ApiClient.setHomework(hw.id, status); maybeTickStreak() }
    }
    private func maybeTickStreak() {
        guard let t = today, !t.homework.isEmpty, t.homework.allSatisfy({ $0.status == "done" }) else { return }
        Task { await ApiClient.tickStreak() }
    }
}
```

- [ ] **Step 2: Write `TodayView.swift`:**

```swift
import SwiftUI

struct TodayView: View {
    @EnvironmentObject var store: Store
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                if let t = store.today {
                    if let next = t.activities.first {
                        Text("\(next.name) · \(next.time)").font(.headline).foregroundStyle(Color(red: 0.18, green: 0.44, blue: 0.42))
                    } else { Text("No activities today").font(.headline) }
                    ForEach(t.countdowns, id: \.self) { Text($0).font(.caption).foregroundStyle(.secondary) }

                    if t.homework.isEmpty {
                        Text("No homework logged").font(.footnote).foregroundStyle(.secondary).padding(.top, 6)
                    } else if t.homework.allSatisfy({ $0.status == "done" }) {
                        Text("All done — nice.").font(.headline).foregroundStyle(Color(red: 0.31, green: 0.48, blue: 0.36)).padding(.top, 6)
                    } else {
                        ForEach(t.homework) { hw in HWRow(hw: hw) }
                    }
                    if t.streak > 0 { Text("\(t.streak) days all done").font(.caption2).foregroundStyle(.secondary).padding(.top, 4) }
                } else if store.loading {
                    ProgressView()
                } else {
                    Button("Tap to load") { store.load() }
                }
            }.padding(.horizontal, 4)
        }
        .onAppear { if store.today == nil { store.load() } }
    }
}

struct HWRow: View {
    @EnvironmentObject var store: Store
    let hw: HW
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(hw.title).font(.footnote).strikethrough(hw.status == "done")
                .foregroundStyle(hw.status == "done" ? .secondary : .primary)
            if hw.status != "done" {
                HStack {
                    Button { store.mark(hw, "done") } label: { Label("Done", systemImage: "checkmark").font(.caption2) }
                        .tint(Color(red: 0.31, green: 0.48, blue: 0.36))
                    Button { store.mark(hw, "later") } label: { Text("Later").font(.caption2) }
                        .tint(.secondary)
                }
            }
        }.padding(6).background(.white.opacity(0.06)).clipShape(RoundedRectangle(cornerRadius: 8))
    }
}
```

- [ ] **Step 3: Root view = `TabView`.** In the app's `@main` App/ContentView:

```swift
@main struct DhruvWatchApp: App {
    @StateObject var store = Store()
    var body: some Scene { WindowGroup {
        TabView { TodayView(); WeekView() }.tabViewStyle(.page).environmentObject(store)
    } }
}
```

  Create a minimal `WeekView.swift` listing `store.today?.activities` and upcoming events (reuse events already fetched; a stub that lists activities is fine for this task — the full week list is polish).

- [ ] **Step 4: On-device QA (manual checklist).** Build+run on Dhruv's watch:
  - Today screen shows the next activity + a countdown.
  - Homework rows render; tapping **Done** strikes it through and (verify via dashboard) writes `status:done`; **Later** greys it.
  - Clearing all homework shows "All done — nice." and (verify) the streak ticks in `/api/kid`.
  - No purple anywhere; text legible on a 41/45mm face.

- [ ] **Step 5: Commit** —

```bash
git add watch/DhruvWatch/DhruvWatch
git commit -m "feat(watch): Today screen — homework Done/Later, activities, countdowns, streak"
```

### Task B3: Complication + two daily local notifications

**Files:**
- Create: `watch/DhruvWatch/DhruvWatchComplication/` (WidgetKit extension), `watch/DhruvWatch/DhruvWatch/Notifications.swift`

**Interfaces:**
- Consumes: `ApiClient.fetchToday()`.
- Produces: an `accessoryCircular`/`accessoryInline` complication showing remaining homework count or next activity; two scheduled notifications.

- [ ] **Step 1: Add a WidgetKit complication target** (File → New → Target → Widget Extension, check "Include Complication" if offered; watchOS complications use WidgetKit on the recorded version). TimelineProvider fetches `ApiClient.fetchToday()`; entry text = `"\(remaining) to do"` where `remaining = homework.filter{ $0.status != "done" }.count`, or the next activity if none. Family Setup caveat: **verify on-device that the complication is selectable on Dhruv's watch face** — if Family Setup blocks third-party complications, keep the app-only glance and note it here.

- [ ] **Step 2: `Notifications.swift`** — request authorization on first launch; schedule two repeating `UNCalendarNotificationTrigger`s (07:00 and 15:30 America/Los_Angeles) whose body is built from the last cached `TodayData` (persist a small snapshot to `UserDefaults` on each `fetchToday`). Reschedule on each app open so content stays fresh:

```swift
import UserNotifications
enum Notifs {
    static func schedule(morning: String, afternoon: String) {
        let c = UNUserNotificationCenter.current()
        c.requestAuthorization(options: [.alert, .sound]) { _, _ in }
        c.removePendingNotificationRequests(withIdentifiers: ["am", "pm"])
        for (id, hour, min, body) in [("am", 7, 0, morning), ("pm", 15, 30, afternoon)] {
            let content = UNMutableNotificationContent(); content.title = "School"; content.body = body
            var dc = DateComponents(); dc.hour = hour; dc.minute = min
            let t = UNCalendarNotificationTrigger(dateMatching: dc, repeats: true)
            c.add(UNNotificationRequest(identifier: id, content: content, trigger: t))
        }
    }
}
```

  Call `Notifs.schedule(...)` from `Store.load()` after data arrives, with `morning = "\(remaining) due today\(nextActivity)"`, `afternoon = "\(tomorrowCount) due tomorrow"` (tomorrowCount from events).

- [ ] **Step 3: On-device QA.** Verify: authorization prompt appears once; a notification fires at the set times (test by temporarily setting the trigger a minute ahead); **Schooltime suppresses** the mid-day one if active (confirm with Schooltime on). Complication (if available) shows the count and updates.

- [ ] **Step 4: Commit** —

```bash
git add watch/DhruvWatch
git commit -m "feat(watch): complication + morning/after-school local notifications"
```

---

## Slice B-web — Fallback glance (ONLY if Slice 0 FAILED)

A phone-sized, auth-gated web page Dhruv opens (bookmark / shared-face complication link). Reuses all Slice-A endpoints; no App Store, no native constraint.

### Task W1: Dhruv web glance

**Files:**
- Create: `dashboard/public/dhruv.html` (its own page; family code entered once, stored in `localStorage`)
- Modify: `dashboard/public/robots.txt` already `Disallow: /` (covers it)

**Interfaces:**
- Consumes: `/api/data`, `/api/activities`, `/api/kid` (Slice A).
- Produces: none.

- [ ] **Step 1: Build `dhruv.html`** — a single self-contained page (same palette, no purple) with: a gate (code → localStorage), a "Today" view computing homework (from `/api/data` events) + today's activities (`/api/activities`) + countdowns, each homework row with **Done**/**Later** buttons that `PUT /api/kid`, an "All done — nice." state, and the streak. Mirror the `TodayView` logic in JS (reuse the day-of-week filter and the countdown computation from Task B1, ported to JS).

- [ ] **Step 2: Local verify** — `wrangler pages dev public`, open `localhost:8788/dhruv.html`, enter code, mark homework done → reflects in `/api/kid` and the parent dashboard.

- [ ] **Step 3: Deploy + verify live** (deployment URL first), confirm noindex.

- [ ] **Step 4: Operator sets it on the watch** — add `dhruv.html` as a shared-face complication link or a watch bookmark; document the exact steps taken in the runbook.

- [ ] **Step 5: Commit** —

```bash
git add dashboard/public/dhruv.html
git commit -m "feat(watch): Dhruv web glance fallback (Family Setup native install blocked)"
```

---

## Self-review (author checklist — completed)

- **Spec coverage:** watch Today screen (B2/W1) ✓; homework Done/Later + no typing (B2/W1) ✓; streak (A3/B2) ✓; glance + countdowns (B1/B2) ✓; weekly-activities schedule + dashboard editor (A1/A2) ✓; write-back visible on dashboard + digest (A4) ✓; complication + 2 notifications (B3) ✓; no custom face (design note; complication only) ✓; family code compiled-in gitignored (B1) ✓; Family Setup standalone + spike-first (Slice 0) ✓; web-glance pivot (Slice B-web) ✓; Schooltime respect (B3 QA) ✓.
- **Placeholders:** none — every code step shows complete code; `WeekView` is explicitly scoped as a stub-then-polish and named.
- **Type consistency:** `HW`/`Act`/`TodayData` defined in B1 and used unchanged in B2/B3; `ApiClient.fetchToday/setHomework/tickStreak` signatures match Store's calls; `/api/kid` request/response shapes match between A3 (server) and B1 (client) and A4 (agent).
- **Open risks carried from spec:** Family Setup dev-install (gated by Slice 0); Family Setup complication support (verified on-device in B3); watchOS version floor (recorded in Task 0 Step 1); homework-granularity of guardian emails (affects row wording — surfaces at B2/W1 QA).
