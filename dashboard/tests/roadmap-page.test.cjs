// Renders every tab of roadmap.html with the real published content, without a browser.
// Run: node --test /Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school/dashboard/tests/roadmap-page.test.cjs
// It catches what unit tests on roadmap-lib.js cannot: a view that throws, prints
// "undefined", or leaves out a section when given the data the Mac actually publishes.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { execFileSync } = require("node:child_process");

const PUBLIC = path.join(__dirname, "..", "public");
const ROADMAP = path.join(__dirname, "..", "..", "roadmap");

function loadPage() {
  const html = fs.readFileSync(path.join(PUBLIC, "roadmap.html"), "utf8");
  const script = html.match(/<script>\n([\s\S]*?)<\/script>/)[1];
  const el = () => ({ classList: { add() {}, remove() {}, contains: () => true, toggle() {} }, addEventListener() {}, textContent: "", innerHTML: "", value: "", click() {} });
  const store = {};
  const handlers = {};
  const calls = { fetch: 0 };
  const ctx = {
    console, setTimeout, URL, Date, Math, JSON, Promise, Object, Array, String, Number, Set, Map, RegExp, Error,
    document: { querySelector: el, getElementById: (id) => (ctx.__els && ctx.__els[id]) || null, addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); } },
    localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } },
    window: { scrollTo() {} },
    fetch: async (...a) => { calls.fetch++; if (ctx.__fetch) return ctx.__fetch(...a); throw new Error("no network in tests"); },
  };
  ctx.self = ctx;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(PUBLIC, "roadmap-lib.js"), "utf8"), ctx);
  vm.runInContext(script, ctx);
  return { ctx, store, handlers, calls };
}

const content = JSON.parse(execFileSync("/usr/bin/python3", ["-c",
  "import sys, json; sys.path.insert(0, sys.argv[1]); import push; print(json.dumps(push.build_content()))", ROADMAP], { encoding: "utf8" }));
const bme = JSON.parse(fs.readFileSync(path.join(PUBLIC, "lists", "rit-bme.json"), "utf8"));
const listIndex = JSON.parse(fs.readFileSync(path.join(PUBLIC, "lists", "index.json"), "utf8"));
const listNotes = JSON.parse(fs.readFileSync(path.join(PUBLIC, "lists", "notes.json"), "utf8"));

function render(tab, state, today) {
  const { ctx, store } = loadPage();
  ctx.__c = content; ctx.__s = state || {}; ctx.__tab = tab; ctx.__today = today || "2026-11-10";
  ctx.__lists = { index: listIndex, notes: listNotes, docs: { bme } };
  const html = vm.runInContext(`
    C = __c; STATE = __s; TAB = __tab;
    Object.assign(LISTS, __lists); UI.list = "bme";
    ({ start: viewStart, options: viewOptions, apply: viewApply, courses: viewCourses, summers: viewSummers, money: viewMoney,
       status: viewStatus, families: viewFamilies, lists: viewLists, timeline: viewTimeline, sources: viewSources })[__tab](__today)`, ctx);
  return { html, ctx, store };
}

const TABS = ["start", "options", "apply", "courses", "summers", "money", "status", "families", "lists", "timeline", "sources"];

test("every tab renders real content without junk text", () => {
  for (const tab of TABS) {
    const { html } = render(tab);
    assert.equal(typeof html, "string", tab);
    assert.ok(html.length > 400, tab + " is nearly empty");
    const text = html.replace(/<[^>]*>/g, " ");
    assert.ok(!/\bundefined\b|\bNaN\b|\[object /.test(text), tab + " prints junk: " + (text.match(/.{30}(undefined|NaN|\[object ).{30}/) || [""])[0]);
  }
});

test("the tab bar offers every view the page can render", () => {
  const { ctx } = loadPage();
  const ids = vm.runInContext("TABS.map(t => t[0])", ctx);
  assert.deepEqual([...ids].sort(), [...TABS].sort());
});

test("no stored or published text can break out into markup", () => {
  const evil = '"><img src=x onerror=alert(1)><script>alert(2)</script>';
  const state = {
    "app:ucsc-sip": { note: evil, status: "in_progress" }, "dec:summer-2027": { note: evil, choice: evil },
    "opt:uc-resident": { note: evil, choice: "active" }, "q:attorney-cspa": { note: evil, seen: true },
    "fam:file-early": { note: evil }, "mon:alabama-automatic": { note: evil, shortlist: true }, "sum:bay-ucsc-sip": { note: evil },
    "custom:x1": { item: { title: evil, link: "javascript:alert(3)", deadline: "2027-01-01", track: "other" } },
  };
  for (const tab of TABS) {
    const { html } = render(tab, state);
    assert.ok(!html.includes("<img src=x"), tab + " let an <img> through");
    assert.ok(!/<script>alert/.test(html), tab + " let a <script> through");
    assert.ok(!html.includes('href="javascript:'), tab + " rendered a javascript: link");
  }
});

test("options: an active route moves to the top, a parked one to the bottom", () => {
  const { html } = render("options", { "opt:canada-first-degree": { choice: "active" }, "opt:uc-resident": { choice: "parked" } });
  const order = [...html.matchAll(/data-opt="([a-z-]+)" data-choice="active"/g)].map(m => m[1]);
  assert.equal(order[0], "canada-first-degree");
  assert.equal(order[order.length - 1], "uc-resident");
});

test("status: the family's date is read from this browser only and never from the content", () => {
  const { ctx } = loadPage();
  ctx.__c = content;
  ctx.localStorage.setItem("rm.pd", JSON.stringify({ row: "eb2-india", date: "2015-02-10" }));
  const html = vm.runInContext('C = __c; STATE = {}; viewStatus("2026-11-10")', ctx);
  assert.match(html, /1 year 3 months<\/b> after the final action cut-off/);
  assert.match(html, /not a forecast/);
  assert.ok(!JSON.stringify(content).includes("2015-02-10"));
  const none = render("status").html;
  assert.match(none, /Enter your priority date/);
});

test("status: a date earlier than the cut-off reads as current, without a gap", () => {
  const { ctx } = loadPage();
  ctx.__c = content;
  ctx.localStorage.setItem("rm.pd", JSON.stringify({ row: "eb2-india", date: "2012-05-01" }));
  const html = vm.runInContext('C = __c; STATE = {}; viewStatus("2026-11-10")', ctx);
  assert.match(html, /earlier than the final action cut-off/);
});

test("lists: tiles and filters reflect the scan, and the tab stands alone", () => {
  const { html, ctx } = render("lists");
  assert.match(html, new RegExp(`<b>${bme.summary.entries}</b><span>programs listed`));
  assert.match(html, new RegExp(`<b>${bme.summary.links.ok}</b><span>links still work`));
  assert.match(html, /not connected to the applications/);
  const counts = vm.runInContext(`(() => { const d = LISTS.docs.bme, out = {};
    for (const f of ["all", "live", "hs", "ca", "cit", "intl"]) { UI.listF = f; UI.listQ = ""; out[f] = listRows(d).length; }
    UI.listF = "all"; UI.listQ = "cleveland"; out.search = listRows(d).length; return out; })()`, ctx);
  assert.equal(counts.all, bme.summary.entries);
  assert.equal(counts.live, bme.summary.links.ok);
  assert.equal(counts.hs, bme.summary.pages_mentioning.high_school);
  assert.equal(counts.cit, bme.summary.pages_mentioning.citizenship);
  assert.ok(counts.search >= 1 && counts.search < counts.all);
});

test("lists: a dead link is shown as text, not as a clickable link", () => {
  const gone = bme.entries.find(e => e.link && e.link.status === "gone");
  const { ctx } = render("lists");
  ctx.__q = gone.org;
  const html = vm.runInContext('UI.listF = "all"; UI.listQ = __q; listRowsHTML(LISTS.docs.bme)', ctx);
  assert.ok(html.includes("page gone"));
  assert.ok(!/<a /.test(html), "a dead entry must not render any link");
});

test("lists: hostile text in a scanned list cannot break out into markup", () => {
  const evil = '"><img src=x onerror=alert(1)><script>alert(2)</script>';
  const { ctx } = render("lists");
  ctx.__doc = { slug: "bme", title: evil, source_url: "javascript:alert(1)", source_last_modified: evil, scanned_on: evil,
    summary: { entries: 1, by_state: { [evil]: 1 }, by_listed_year: { [evil]: 1 }, links: { [evil]: 1, ok: 1 }, pages_read: 1, pages_mentioning: { [evil]: 1 } },
    entries: [{ org: evil, unit: evil, city: evil, state: evil, region: evil, listed_year: evil, desc: evil, url: "javascript:alert(1)", link: { status: "ok", code: 200, words: { high_school: true }, snippets: { high_school: evil, age_rule: evil, [evil]: evil } } },
              { org: evil, unit: "", city: "", state: "", listed_year: null, desc: evil, url: 'https://example.org/"onmouseover="x', link: { status: evil, words: null } }] };
  ctx.__notes = { bme: { what: [evil], useful: [evil], limits: [evil] } };
  const html = vm.runInContext('LISTS.docs.bme = __doc; LISTS.notes = __notes; UI.listF = "all"; UI.listQ = ""; viewLists()', ctx);
  assert.ok(!html.includes("<img src=x") && !/<script>alert/.test(html) && !html.includes('href="javascript:'));
  assert.ok(!/"onmouseover="x/.test(html));
});

test("lists: a list that cannot be loaded shows an error once instead of retrying forever", async () => {
  const { ctx, calls } = loadPage();
  ctx.__fetch = async (p) => ({ ok: true, json: async () => (String(p).includes("index") ? { lists: [{ slug: "bme", file: "../../secret.json" }] } : {}) });
  vm.runInContext('C = {}; TAB = "lists"; render = () => { __renders = (__renders || 0) + 1; }; var __renders = 0;', ctx);
  await vm.runInContext("loadLists()", ctx);
  const first = vm.runInContext("viewLists()", ctx);
  assert.match(first, /could not be loaded/);
  const before = calls.fetch;
  vm.runInContext("viewLists(); viewLists();", ctx);
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(calls.fetch, before, "an error state must not trigger more requests");
});

test("status: changing the family's date makes no network request and stores it locally only", () => {
  const { ctx, store, handlers, calls } = loadPage();
  ctx.__c = content;
  ctx.__els = { pdRow: { value: "eb2-india" }, pdDate: { value: "2015-02-10" } };
  vm.runInContext('C = __c; STATE = {}; TAB = "status";', ctx);
  for (const fn of handlers.change) fn({ target: { id: "pdDate", value: "2015-02-10", dataset: {} } });
  assert.equal(calls.fetch, 0);
  assert.deepEqual(JSON.parse(store["rm.pd"]), { row: "eb2-india", date: "2015-02-10" });
  assert.ok(!JSON.stringify(vm.runInContext("STATE", ctx)).includes("2015-02-10"));
  assert.ok(!JSON.stringify(vm.runInContext("DRAFT", ctx)).includes("2015-02-10"));
  for (const fn of handlers.click) fn({ target: { id: "pdClear", dataset: {} } });
  assert.equal(store["rm.pd"], undefined);
  assert.equal(calls.fetch, 0);
});

test("lists: buttons use each list's label, the newest list opens first, and the region filter works", async () => {
  const { ctx, handlers } = loadPage();
  const idx = { lists: [{ slug: "bme", label: "Biomedical engineering", file: "rit-bme.json" }, { slug: "cstate1-ca", label: "California", file: "rit-cstate1-ca.json" }] };
  const ca = { slug: "cstate1-ca", label: "California", summary: { entries: 3, by_region: { "Bay Area": 2, "Southern California": 1 }, by_state: { CA: 3 }, by_listed_year: { 2020: 3 }, links: { ok: 3 }, pages_read: 3, pages_mentioning: { age_rule: 1 } },
    entries: [{ org: "Near A", state: "CA", city: "Stanford", region: "Bay Area", desc: "x", url: "https://a.example/", link: { status: "ok", words: { age_rule: true } } },
              { org: "Near B", state: "CA", city: "Berkeley", region: "Bay Area", desc: "y", url: "https://b.example/", link: { status: "ok", words: {} } },
              { org: "Far C", state: "CA", city: "La Jolla", region: "Southern California", desc: "z", url: "https://c.example/", link: { status: "ok", words: {} } }] };
  ctx.__fetch = async (p) => ({ ok: true, json: async () => (String(p).includes("index") ? idx : String(p).includes("notes") ? {} : ca) });
  vm.runInContext('C = {}; TAB = "lists"; render = () => {};', ctx);
  await vm.runInContext("loadLists()", ctx);
  assert.equal(vm.runInContext("UI.list", ctx), "cstate1-ca");
  const html = vm.runInContext("viewLists()", ctx);
  assert.match(html, />Biomedical engineering<\/button>/);
  assert.match(html, />California<\/button>/);
  assert.match(html, /Where in California/);
  assert.match(html, /data-listf="near"/);
  assert.match(html, /states an age/);
  const near = vm.runInContext('UI.listF = "near"; listRows(LISTS.docs["cstate1-ca"]).map(e => e.org)', ctx);
  assert.deepEqual([...near], ["Near A", "Near B"]);
  // switching lists must not keep a filter the other list does not offer
  vm.runInContext('LISTS.docs.bme = { slug: "bme", summary: { entries: 1, by_state: {}, links: {} }, entries: [{ org: "Far", state: "MA", url: "https://x.example/", link: { status: "ok" } }] };', ctx);
  for (const fn of handlers.click) fn({ target: { dataset: { list: "bme" } } });
  assert.equal(vm.runInContext("UI.listF", ctx), "all");
  assert.equal(vm.runInContext("listRows(LISTS.docs.bme).length", ctx), 1);
  // the heading is the list's label, not the whole page's title
  vm.runInContext('LISTS.docs["cstate1-ca"].title = "AL-DE"; UI.list = "cstate1-ca";', ctx);
  assert.match(vm.runInContext("viewLists()", ctx), /<div class="sec teal">California<\/div>/);
});

test("lists: each program can be marked interested or not, saved under its own id", async () => {
  const { ctx, handlers, calls } = loadPage();
  const doc = { slug: "bayarea-local", label: "Bay Area, local",
    summary: { entries: 3, by_section: { Labs: 2, Zoos: 1 }, by_listed_year: { "no year": 3 }, by_state: { CA: 3 }, links: { ok: 3 }, pages_read: 3, pages_mentioning: {} },
    entries: [{ id: "bayarea-local-aaaaaaaaaa", org: "Lab A", section: "Labs", source: "Listing", state: "CA", region: "Bay Area", url: "https://a.example/", link: { status: "ok" } },
              { id: "bayarea-local-bbbbbbbbbb", org: "Lab B", section: "Labs", source: "Listing", state: "CA", region: "Bay Area", url: "https://b.example/", link: { status: "ok" } },
              { id: "bayarea-local-cccccccccc", org: "Zoo C", section: "Zoos", source: "Listing", state: "CA", region: "Bay Area", url: "https://c.example/", link: { status: "ok" } }] };
  const puts = [];
  ctx.__fetch = async (p, o) => { if (o && o.method === "PUT") { const b = JSON.parse(o.body); puts.push(b); return { ok: true, status: 200, json: async () => ({ ok: true, record: b.patch }) }; }
    return { ok: true, status: 200, json: async () => ({}) }; };
  ctx.__doc = doc;
  vm.runInContext('C = {}; STATE = { "lst:bayarea-local-bbbbbbbbbb": { choice: "not interested" } }; TAB = "lists"; LISTS.index = { lists: [{ slug: "bayarea-local", file: "bayarea-local.json" }] }; LISTS.docs["bayarea-local"] = __doc; UI.list = "bayarea-local"; render = () => {};', ctx);
  let html = vm.runInContext("viewLists()", ctx);
  assert.match(html, /data-lst="bayarea-local-aaaaaaaaaa" data-choice="interested"/);
  assert.match(html, /data-lst="bayarea-local-aaaaaaaaaa" data-choice="not interested"/);
  assert.match(html, /Sections/);
  assert.ok(!/When the list last touched each entry/.test(html), "a list without years shows no year chart");
  assert.match(html, /<span class="pill">Labs<\/span>/);
  for (const fn of handlers.click) fn({ target: { dataset: { lst: "bayarea-local-aaaaaaaaaa", choice: "interested" } } });
  await new Promise((r) => setTimeout(r, 10));
  assert.deepEqual(puts[0], { id: "lst:bayarea-local-aaaaaaaaaa", patch: { choice: "interested" } });
  const rows = (f) => [...vm.runInContext(`UI.listF = "${f}"; listRows(LISTS.docs["bayarea-local"]).map(e => e.org)`, ctx)];
  assert.deepEqual(rows("mine"), ["Lab A"]);
  assert.deepEqual(rows("all"), ["Lab A", "Lab B", "Zoo C"]);
  vm.runInContext('UI.hideNo = true;', ctx);
  assert.deepEqual(rows("all"), ["Lab A", "Zoo C"]);
  // clicking the chosen answer again clears it
  for (const fn of handlers.click) fn({ target: { dataset: { lst: "bayarea-local-aaaaaaaaaa", choice: "interested" } } });
  await new Promise((r) => setTimeout(r, 10));
  assert.deepEqual(puts[1], { id: "lst:bayarea-local-aaaaaaaaaa", patch: { choice: "" } });
  assert.ok(calls.fetch >= 2);
});

test("lists: notes can be short titled points, and stay escaped", () => {
  const { ctx } = render("lists");
  const evil = '"><img src=x onerror=alert(1)>';
  ctx.__notes = { bme: { useful: [{ title: "J. Craig Venter Institute" + evil, points: ["High school through graduate" + evil, "At least 16"] }, "plain line"] } };
  const html = vm.runInContext('LISTS.notes = __notes; UI.list = "bme"; viewLists()', ctx);
  assert.match(html, /<b>J\. Craig Venter Institute/);
  assert.match(html, /<li>At least 16<\/li>/);
  assert.match(html, /plain line/);
  assert.ok(!html.includes("<img src=x"));
});

test("lists: the checked 'who is it for' tag shows with its quote and can be filtered", () => {
  const { ctx } = loadPage();
  const evil = '"><img src=x onerror=alert(1)>';
  ctx.__doc = { slug: "cstate1-ca", label: "California",
    summary: { entries: 3, by_audience: { high_school: 1, graduate: 1, "not checked": 1 }, links: { ok: 3 }, pages_read: 3, pages_mentioning: {}, by_state: {} },
    entries: [
      { id: "cstate1-ca-aaaaaaaaaa", org: "Venter", url: "https://a.example/", link: { status: "ok" },
        audience: { tag: "high_school", quote: "students (high school through graduate)" + evil, quote_verified: true, citizenship_verified: true, evidence_url: "https://a.example/elig", min_age: "16", citizenship: "must be eligible to work in the United States", dates: "June 2027", checked_on: "2026-11-11" } },
      { id: "cstate1-ca-bbbbbbbbbb", org: "Genentech", url: "https://b.example/", link: { status: "ok" },
        audience: { tag: "graduate", quote: "PhD students", evidence_url: "javascript:alert(1)", checked_on: "2026-11-11" } },
      { id: "cstate1-ca-cccccccccc", org: "Other", url: "https://c.example/", link: { status: "ok" } }] };
  vm.runInContext('C = {}; STATE = {}; LISTS.index = { lists: [{ slug: "cstate1-ca", file: "x.json" }] }; LISTS.docs["cstate1-ca"] = __doc; UI.list = "cstate1-ca";', ctx);
  const html = vm.runInContext("viewLists()", ctx);
  assert.match(html, /Who it is for/);
  assert.match(html, /High school: yes/);
  assert.match(html, /Graduate or PhD/);
  assert.match(html, /students \(high school through graduate\)/);
  assert.match(html, /Minimum age: 16/);
  assert.match(html, /exact words on the page/);
  assert.match(html, /status rule: exact words/);
  assert.match(html, /page could not be re-read/);   // Genentech's tag has no verification result
  assert.match(html, /must be eligible to work in the United States/);
  assert.match(html, /href="https:\/\/a\.example\/elig"/);
  assert.ok(!html.includes('href="javascript:') && !html.includes("<img src=x"));
  assert.match(html, /data-listf="hsyes"/);
  const rows = (f) => [...vm.runInContext(`UI.listF = "${f}"; listRows(LISTS.docs["cstate1-ca"]).map(e => e.org)`, ctx)];
  assert.deepEqual(rows("hsyes"), ["Venter"]);
  assert.match(html, /data-listf="rule"/);
  assert.match(html, />Citizenship or residency required</);
  assert.match(html, /data-listf="norule"/);
  // "rule" = the checker found a citizenship, residency or work-eligibility rule; "norule" = tagged and none found
  vm.runInContext('LISTS.docs["cstate1-ca"].entries[1].audience.citizenship = "U.S. citizens or permanent residents";', ctx);
  assert.deepEqual(rows("rule"), ["Venter", "Genentech"]);
  vm.runInContext('LISTS.docs["cstate1-ca"].entries[1].audience.citizenship = "Not stated";', ctx);
  assert.deepEqual(rows("rule"), ["Venter"]);
  assert.deepEqual(rows("norule"), ["Genentech"]);
  // stored wordings that say there is NO such rule must not count as one
  const requires = (t) => vm.runInContext(`requiresStatus({ citizenship: ${JSON.stringify(t)} })`, ctx);
  for (const t of ["None stated; must be full-time student at a U.S. university or college",
                   "None stated; international applicants must show English proficiency (interview or TOEFL)",
                   "No general citizenship requirement stated; AHA projects accept international students",
                   "Page lists no citizenship rule; says NDnano helps international students",
                   "Open to international students; no citizenship restriction stated",
                   "Not required for the program; honorarium requires being legally eligible to work in the US",
                   "Open to domestic and international students.", "Not stated", ""]) assert.equal(requires(t), false, t);
  for (const t of ["U.S. citizens or permanent residents", "Must be authorized to work in the U.S.",
                   "Applicants must be \"U.S. citizens or lawful permanent residents (green card holders).\"",
                   "Eligible to be employed in the US."]) assert.equal(requires(t), true, t);
  assert.deepEqual(rows("all"), ["Venter", "Genentech", "Other"]);   // tags never remove anything
  // a program the checker could not find is shown as text, not as a link (one such site now serves spam)
  vm.runInContext('LISTS.docs["cstate1-ca"].entries[2].audience = { tag: "gone", quote: "Page is a gambling-link page" };', ctx);
  const goneHtml = vm.runInContext('UI.listF = "all"; listRowsHTML(LISTS.docs["cstate1-ca"])', ctx);
  assert.ok(!goneHtml.includes('href="https://c.example/"'));
  assert.match(goneHtml, /Program not found/);
});

test("lists: who can take each program (non-citizens, other colleges, pay) shows with quotes and filters", () => {
  const { ctx } = loadPage();
  const evil = '"><img src=x onerror=alert(1)>';
  ctx.__doc = { slug: "premed", label: "Pre-med",
    summary: { entries: 4, by_audience: { college: 2 }, by_noncitizen: { open: 1, some_tracks: 1, closed: 1, "not checked": 1 }, links: { ok: 4 }, pages_read: 4, pages_mentioning: {}, by_state: {} },
    entries: [
      { id: "premed-aaaaaaaaaa", org: "Stowers", url: "https://a.example/", link: { status: "ok" },
        fit: { noncitizen: "open", noncitizen_quote: "Open to domestic and international students." + evil, who: "any_college", who_quote: "from any college",
               pay: "stipend", pay_quote: "$5000 stipend", work_auth: false, evidence_url: "https://a.example/elig", verified: { noncitizen: true, who: false }, checked_on: "2026-11-12" } },
      { id: "premed-bbbbbbbbbb", org: "Colorado", url: "https://b.example/", link: { status: "ok" },
        fit: { noncitizen: "some_tracks", who: "own_students", pay: "wage", work_auth: true, work_auth_quote: "must be authorized to work", evidence_url: "javascript:alert(1)", checked_on: "2026-11-12" } },
      { id: "premed-cccccccccc", org: "Harvard", url: "https://c.example/", link: { status: "ok" },
        fit: { noncitizen: "closed", who: "any_college", pay: "stipend", work_auth: false, checked_on: "2026-11-12" } },
      { id: "premed-dddddddddd", org: "Other", url: "https://d.example/", link: { status: "ok" } }] };
  vm.runInContext('C = {}; STATE = {}; LISTS.index = { lists: [{ slug: "premed", file: "x.json" }] }; LISTS.docs["premed"] = __doc; UI.list = "premed";', ctx);
  const html = vm.runInContext("viewLists()", ctx);
  assert.match(html, /Who can take it/);
  assert.match(html, /Open to non-citizens/);
  assert.match(html, /Some places open to non-citizens/);
  assert.match(html, /Citizenship, residency or US work eligibility required/);
  assert.match(html, /Students from any college/);
  assert.match(html, /Own students only/);
  assert.match(html, /Hourly pay/);
  assert.match(html, /Asks for US work authorization/);
  assert.match(html, /Open to domestic and international students\./);
  assert.match(html, /href="https:\/\/a\.example\/elig"/);
  assert.ok(!html.includes('href="javascript:') && !html.includes("<img src=x"));
  assert.match(html, /data-listf="noncit"/);
  assert.match(html, /data-listf="noncitany"/);
  const rows = (f) => [...vm.runInContext(`UI.listF = "${f}"; listRows(LISTS.docs["premed"]).map(e => e.org)`, ctx)];
  assert.deepEqual(rows("noncit"), ["Stowers", "Colorado"]);
  assert.deepEqual(rows("noncitany"), ["Stowers"]);
  assert.match(html, /data-listf="noncitfree"/);
  assert.deepEqual(rows("noncitfree"), ["Stowers"]);   // Colorado asks for US work authorization
  vm.runInContext('LISTS.docs["premed"].entries[1].fit.verified = { work_auth: true };', ctx);
  assert.match(vm.runInContext('UI.listF = "all"; listRowsHTML(LISTS.docs["premed"])', ctx), /must be authorized to work”<\/i> <span class="pill open">exact words on the page/);
  assert.deepEqual(rows("all"), ["Stowers", "Colorado", "Harvard", "Other"]);   // never removes anything
  // a list with no such checks offers no such filters
  vm.runInContext('delete LISTS.docs["premed"].summary.by_noncitizen;', ctx);
  assert.ok(!vm.runInContext("viewLists()", ctx).includes('data-listf="noncit"'));
});

test("lists: the college-years card comes from the private content only", () => {
  const { ctx } = loadPage();
  ctx.__doc = { slug: "premed", label: "Pre-med", summary: { entries: 0, by_noncitizen: { open: 0 }, links: {}, pages_mentioning: {}, by_state: {} }, entries: [] };
  vm.runInContext('STATE = {}; LISTS.index = { lists: [{ slug: "premed", file: "x.json" }] }; LISTS.docs["premed"] = __doc; UI.list = "premed";', ctx);
  vm.runInContext("C = {};", ctx);
  assert.ok(!vm.runInContext("viewLists()", ctx).includes("Before you pick from this list"));
  ctx.__c = content;
  vm.runInContext("C = __c;", ctx);
  const html = vm.runInContext("viewLists()", ctx);
  assert.match(html, /Before you pick from this list/);
  for (const id of ["cpt-one-year", "f1-on-campus"]) assert.ok(content.status.facts.some(f => f.id === id), id);
  assert.match(html, /one full academic year/);
});

test("money: every row shows how far it was confirmed, and unconfirmed rows carry no link", () => {
  const { html } = render("money");
  const rows = content.money.awards.length + content.money.points.length;
  const pills = (html.match(/<span class="pill (open|verify|closed)">(confirmed at the source|partly confirmed|not confirmed)<\/span>/g) || []).length;
  assert.equal(pills, rows);
  for (const a of content.money.awards) if (a.confidence === "unconfirmed") assert.equal(a.url, undefined, a.id);
  assert.match(html, /Canadian universities/);
});

test("courses: the fixed week changes with the band season", () => {
  const inSeason = render("courses", {}, "2026-11-10").html;
  const after = render("courses", {}, "2026-12-01").html;
  assert.match(inSeason, /Band season is on now/);
  assert.match(inSeason, /Marching band 5:45 pm to 9:30 pm/);
  assert.match(after, /Band season is over for this year/);
  assert.ok(!/Marching band 5:45 pm/.test(after));
  assert.match(after, /<b>21.75 hours a week<\/b> in band season, <b>5 hours<\/b> the rest of the year/);
  assert.match(after, /Homework estimate not set/);
});
