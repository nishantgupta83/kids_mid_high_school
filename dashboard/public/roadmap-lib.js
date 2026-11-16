// Pure logic for the roadmap page. Loaded as a plain script (window.RM) and by the
// node tests in dashboard/tests/ (module.exports). No DOM, no network, no Date.now():
// "today" is always passed in, so every rule here is testable.
(function (root) {
  "use strict";
  const DAY = 864e5;
  const ISO = /^\d{4}-\d{2}-\d{2}$/;
  const isISO = (s) => typeof s === "string" && ISO.test(s);
  const utc = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10));

  // Statuses that mean "nothing left to do here".
  const CLOSED = new Set(["submitted", "accepted", "declined", "dropped", "done"]);
  const STATUSES = ["not_started", "in_progress", "submitted", "accepted", "declined", "dropped", "done"];

  // Whole calendar days from a to b (UTC maths, so a clock change never adds or drops a day).
  function daysBetween(a, b) {
    return Math.round((utc(b) - utc(a)) / DAY);
  }

  // One rule for every dated thing on the page. An ESTIMATED date (approx:true, or
  // exact:false on a milestone) never gets a countdown and never counts as passed on its
  // own: a guess must not hide an opportunity that may still be open. It is only "passed"
  // once its stated window (`until`) has closed. `stale` = the guess has gone by.
  function dateState(item, today) {
    const date = isISO(item && item.deadline) ? item.deadline : (isISO(item && item.date) ? item.date : null);
    const until = isISO(item && item.until) ? item.until : null;
    if (!date && !until) return { kind: "rolling", days: null, passed: false, stale: false };
    const estimated = item.approx === true || item.exact === false || !date;
    if (!estimated) {
      const days = daysBetween(today, date);
      return { kind: "exact", days, passed: days < 0, stale: false };
    }
    return {
      kind: "estimated",
      days: null,
      passed: until !== null && until < today,
      stale: date !== null && date < today,
    };
  }

  // What needs attention: `soon` = open items dated inside the horizon (estimates included,
  // flagged by ds.kind), soonest first; `overdue` = exact dates that passed with no closing
  // status; `stale` = estimates whose guessed date has gone by while the window may still be
  // open. Stale items are surfaced for confirming: a guess must never make an item vanish.
  function upcoming(items, state, today, horizon) {
    const soon = [], overdue = [], stale = [];
    for (const item of items || []) {
      const st = (state && state[item.id]) || {};
      if (CLOSED.has(st.status)) continue;
      const ds = dateState(item, today);
      const date = isISO(item.deadline) ? item.deadline : (isISO(item.date) ? item.date : null);
      if (ds.kind === "exact") {
        if (ds.passed) overdue.push({ item, ds, date });
        else if (ds.days <= horizon) soon.push({ item, ds, date });
      } else if (ds.kind === "estimated" && date && !ds.passed) {
        const d = daysBetween(today, date);
        if (d < 0) stale.push({ item, ds, date });
        else if (d <= horizon) soon.push({ item, ds, date });
      }
    }
    const byDate = (x, y) => (x.date < y.date ? -1 : x.date > y.date ? 1 : String(x.item.id).localeCompare(String(y.item.id)));
    soon.sort(byDate);
    overdue.sort(byDate);
    stale.sort(byDate);
    return { soon, overdue, stale };
  }

  function minutes(hhmm) {
    const m = typeof hhmm === "string" && /^(\d{1,2}):(\d{2})$/.exec(hhmm);
    return m ? +m[1] * 60 + +m[2] : null;
  }

  // Hours a week in fixed blocks: {day, start:"17:45", end:"21:30"} or, when the clock time
  // is not known, {day, hours: 1}. Bad blocks count as 0.
  function weeklyHours(blocks) {
    let total = 0;
    for (const b of blocks || []) {
      const s = minutes(b && b.start), e = minutes(b && b.end);
      if (s !== null && e !== null && e > s) total += (e - s) / 60;
      else if (b && typeof b.hours === "number" && isFinite(b.hours) && b.hours > 0) total += b.hours;
    }
    return total;
  }

  // The fixed blocks of a week. A commitment is {id, when:"season"|"year", blocks:[...]};
  // "season" ones (marching band) only count while the season is on.
  function fixedBlocks(commitments, inSeason) {
    const out = [];
    for (const c of commitments || []) {
      if (!c || !Array.isArray(c.blocks)) continue;
      if (c.when === "year" || (c.when === "season" && inSeason)) for (const b of c.blocks) out.push({ ...b, of: c.id });
    }
    return out;
  }

  // Weekly load for a set of courses. `weightOf(course)` is the family's own judgment of
  // homework hours a week; until it returns a real number for every course the total is
  // UNKNOWN (null), never a made-up zero.
  function loadSummary(courses, blocks, weightOf) {
    const fixed = weeklyHours(blocks);
    let estimated = 0;
    const unknown = [];
    for (const c of courses || []) {
      let w = null;
      try { w = weightOf(c); } catch (e) { w = null; }
      if (typeof w === "number" && isFinite(w) && w >= 0) estimated += w;
      else unknown.push(c.title || c.id);
    }
    if (unknown.length) return { fixed, estimated: null, total: null, unknown };
    return { fixed, estimated, total: fixed + estimated, unknown };
  }

  function safeUrl(u) {
    try {
      const p = new URL(u);
      return p.protocol === "https:" || p.protocol === "http:" ? p.href : null;
    } catch (e) {
      return null;
    }
  }

  function fmtDays(n) {
    if (n === 0) return "today";
    if (n === 1) return "tomorrow";
    if (n > 1) return "in " + n + " days";
    return n === -1 ? "1 day ago" : -n + " days ago";
  }

  // A decision counts as made only when the chosen option is a real choice. Options that
  // mean "not yet" keep it on the open list.
  function isOpenChoice(choice) {
    if (typeof choice !== "string" || !choice.trim()) return true;
    return /^(not yet|still\b|decide\b|ask\b)/i.test(choice.trim());
  }

  // How far a date sits after a cut-off date, in whole years and months. `current` is true
  // only when the date is strictly earlier than the cut-off (the way a visa chart is read).
  function gap(cutoff, date) {
    if (!isISO(cutoff) || !isISO(date)) return null;
    if (date < cutoff) return { current: true, years: 0, months: 0 };
    let months = (+date.slice(0, 4) - +cutoff.slice(0, 4)) * 12 + (+date.slice(5, 7) - +cutoff.slice(5, 7));
    if (+date.slice(8, 10) < +cutoff.slice(8, 10)) months -= 1;
    months = Math.max(0, months);
    return { current: false, years: Math.floor(months / 12), months: months % 12 };
  }

  const RM = { CLOSED, STATUSES, isISO, daysBetween, dateState, upcoming, weeklyHours, fixedBlocks, loadSummary, safeUrl, fmtDays, isOpenChoice, gap };
  if (typeof module !== "undefined" && module.exports) module.exports = RM;
  else root.RM = RM;
})(typeof self !== "undefined" ? self : this);
