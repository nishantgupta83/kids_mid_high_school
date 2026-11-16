// Run: node --test /Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school/dashboard/tests/
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const RM = require("../public/roadmap-lib.js");

const BAND = [
  { day: 1, start: "17:45", end: "21:30" },
  { day: 3, start: "17:45", end: "21:30" },
  { day: 5, start: "17:30", end: "21:30" },
  { day: 6, start: "09:00", end: "14:15" },
];

test("daysBetween counts calendar days across DST and year ends", () => {
  assert.equal(RM.daysBetween("2026-11-09", "2026-11-30"), 21);
  assert.equal(RM.daysBetween("2027-03-13", "2027-03-15"), 2); // US clocks change Mar 14, 2027
  assert.equal(RM.daysBetween("2026-12-31", "2027-01-01"), 1);
  assert.equal(RM.daysBetween("2026-11-09", "2026-11-01"), -8);
});

test("an exact date gets a countdown and can be passed", () => {
  const s = RM.dateState({ deadline: "2026-11-01" }, "2026-11-09");
  assert.deepEqual(s, { kind: "exact", days: -8, passed: true, stale: false });
  assert.equal(RM.dateState({ deadline: "2027-02-15" }, "2026-11-09").days, 98);
});

test("an estimated date never gets a countdown and never counts as passed", () => {
  const s = RM.dateState({ deadline: "2026-11-01", approx: true }, "2026-11-09");
  assert.equal(s.kind, "estimated");
  assert.equal(s.days, null);
  assert.equal(s.passed, false);
  assert.equal(s.stale, true); // the guess has gone by: ask to confirm, do not hide
  // milestones use date + exact:false for the same idea
  assert.equal(RM.dateState({ date: "2027-05-03", exact: false }, "2026-11-09").kind, "estimated");
});

test("an estimated window that has closed is passed", () => {
  const s = RM.dateState({ deadline: "2026-10-15", approx: true, until: "2026-10-31" }, "2026-11-09");
  assert.equal(s.passed, true);
});

test("no date at all is rolling", () => {
  assert.deepEqual(RM.dateState({}, "2026-11-09"), { kind: "rolling", days: null, passed: false, stale: false });
  assert.equal(RM.dateState({ deadline: "soon" }, "2026-11-09").kind, "rolling");
});

test("upcoming: exact dates inside the horizon, soonest first; estimates flagged", () => {
  const items = [
    { id: "far", deadline: "2027-06-01" },
    { id: "b", deadline: "2026-12-01" },
    { id: "a", deadline: "2026-11-20" },
    { id: "est", deadline: "2026-11-30", approx: true },
    { id: "roll" },
  ];
  const u = RM.upcoming(items, {}, "2026-11-09", 90);
  assert.deepEqual(u.soon.map((r) => r.item.id), ["a", "est", "b"]);
  assert.equal(u.soon[1].ds.kind, "estimated");
  assert.deepEqual(u.overdue, []);
});

test("upcoming: a passed exact date is overdue unless its status closes it", () => {
  const items = [{ id: "x", deadline: "2026-11-01" }, { id: "y", deadline: "2026-11-02" }];
  const open = RM.upcoming(items, {}, "2026-11-09", 90);
  assert.deepEqual(open.overdue.map((r) => r.item.id), ["x", "y"]);
  const closed = RM.upcoming(items, { x: { status: "submitted" }, y: { status: "in_progress" } }, "2026-11-09", 90);
  assert.deepEqual(closed.overdue.map((r) => r.item.id), ["y"]);
});

test("upcoming: closed items drop out of the soon list too", () => {
  const items = [{ id: "a", deadline: "2026-11-20" }];
  assert.equal(RM.upcoming(items, { a: { status: "dropped" } }, "2026-11-09", 90).soon.length, 0);
});

test("upcoming: an estimate whose guessed date has gone by is listed as stale, not dropped", () => {
  const items = [
    { id: "gone", deadline: "2026-11-01", approx: true },                       // guess passed, no window
    { id: "open-window", deadline: "2026-11-01", approx: true, until: "2026-12-15" }, // guess passed, window still open
    { id: "closed-window", deadline: "2026-10-01", approx: true, until: "2026-10-31" }, // window shut: not stale, just over
    { id: "exact-past", deadline: "2026-11-01" },
  ];
  const u = RM.upcoming(items, {}, "2026-11-09", 90);
  assert.deepEqual(u.stale.map((r) => r.item.id), ["gone", "open-window"]);
  assert.deepEqual(u.overdue.map((r) => r.item.id), ["exact-past"]);
  assert.deepEqual(u.soon, []);
  assert.deepEqual(RM.upcoming(items, { gone: { status: "done" } }, "2026-11-09", 90).stale.map((r) => r.item.id), ["open-window"]);
});

test("blocks may give hours instead of clock times", () => {
  assert.equal(RM.weeklyHours([{ day: 2, hours: 1 }, { day: 3, hours: 2 }, { day: 7, hours: 2 }]), 5);
  assert.equal(RM.weeklyHours([...BAND, { day: 2, hours: 1 }]), 17.75);
  assert.equal(RM.weeklyHours([{ day: 2, hours: -1 }, { day: 2, hours: "two" }]), 0);
});

test("fixedBlocks picks commitments by season", () => {
  const commitments = [
    { id: "band", when: "season", blocks: BAND },
    { id: "flute", when: "year", blocks: [{ day: 2, hours: 1 }] },
  ];
  assert.equal(RM.weeklyHours(RM.fixedBlocks(commitments, true)), 17.75);
  assert.equal(RM.weeklyHours(RM.fixedBlocks(commitments, false)), 1);
  assert.equal(RM.fixedBlocks(commitments, true)[0].title, undefined); // blocks carry their commitment id, not a title
  assert.equal(RM.fixedBlocks(commitments, true)[0].of, "band");
  assert.deepEqual(RM.fixedBlocks(null, true), []);
});

test("band blocks add up to 16.75 hours a week", () => {
  assert.equal(RM.weeklyHours(BAND), 16.75);
  assert.equal(RM.weeklyHours([]), 0);
  assert.equal(RM.weeklyHours([{ day: 1, start: "bad", end: "21:30" }]), 0);
});

test("load: with no weights set, the estimate is unknown, never zero", () => {
  const courses = [{ id: "ap-bio", title: "AP Biology", level: "ap" }];
  const s = RM.loadSummary(courses, BAND, () => null);
  assert.equal(s.fixed, 16.75);
  assert.equal(s.estimated, null);
  assert.equal(s.total, null);
  assert.deepEqual(s.unknown, ["AP Biology"]);
});

test("load: weights from the family's function are summed", () => {
  const courses = [
    { id: "ap-bio", title: "AP Biology", level: "ap" },
    { id: "ush", title: "US History", level: "regular" },
  ];
  const s = RM.loadSummary(courses, BAND, (c) => (c.level === "ap" ? 6 : 2.5));
  assert.equal(s.estimated, 8.5);
  assert.equal(s.total, 25.25);
  assert.deepEqual(s.unknown, []);
});

test("load: a bad weight (negative, NaN, text) counts as unknown", () => {
  const courses = [{ id: "a", title: "A", level: "ap" }, { id: "b", title: "B", level: "ap" }];
  const s = RM.loadSummary(courses, [], (c) => (c.id === "a" ? -3 : "lots"));
  assert.equal(s.total, null);
  assert.deepEqual(s.unknown, ["A", "B"]);
});

test("safeUrl lets http(s) through and nothing else", () => {
  assert.equal(RM.safeUrl("https://example.org/a"), "https://example.org/a");
  assert.equal(RM.safeUrl("javascript:alert(1)"), null);
  assert.equal(RM.safeUrl("not a url"), null);
  assert.equal(RM.safeUrl(null), null);
});

test("a decision stays open until a real choice is made", () => {
  assert.equal(RM.isOpenChoice(undefined), true);
  assert.equal(RM.isOpenChoice(""), true);
  for (const c of ["Not yet", "Still thinking", "Still open", "Decide later", "Decide with the summer plan", "Ask the counsellor first"]) {
    assert.equal(RM.isOpenChoice(c), true, c);
  }
  for (const c of ["Apply", "Skip", "Cleveland in late summer", "Asked, answer recorded", "Keep the Feb 2026 plan"]) {
    assert.equal(RM.isOpenChoice(c), false, c);
  }
});

test("gap between a cut-off date and a later date, in whole years and months", () => {
  assert.deepEqual(RM.gap("2013-11-01", "2015-02-01"), { current: false, years: 1, months: 3 });
  assert.deepEqual(RM.gap("2013-11-01", "2013-11-20"), { current: false, years: 0, months: 0 });
  assert.deepEqual(RM.gap("2013-11-15", "2014-11-14"), { current: false, years: 0, months: 11 });
  assert.deepEqual(RM.gap("2013-11-01", "2013-10-31"), { current: true, years: 0, months: 0 });
  assert.deepEqual(RM.gap("2013-11-01", "2013-11-01"), { current: false, years: 0, months: 0 }); // the cut-off itself is not yet current
  assert.equal(RM.gap("2013-11-01", "soon"), null);
  assert.equal(RM.gap(null, "2015-01-01"), null);
});

test("fmtDays reads naturally", () => {
  assert.equal(RM.fmtDays(0), "today");
  assert.equal(RM.fmtDays(1), "tomorrow");
  assert.equal(RM.fmtDays(21), "in 21 days");
  assert.equal(RM.fmtDays(-1), "1 day ago");
  assert.equal(RM.fmtDays(-8), "8 days ago");
});
