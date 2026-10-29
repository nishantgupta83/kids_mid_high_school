#!/usr/bin/env python3
"""Regression tests for the digest grid + skip rules. Stdlib only; /usr/bin/python3.

Every test here exists because a pre-implementation review named the failure.
Run: /usr/bin/python3 scripts/test_digest.py   (exit 0 = all pass)
"""
import datetime
import json
import os
import sys
import tempfile

REPO = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"
sys.path.insert(0, os.path.join(REPO, "agent"))
import send_digest as sd          # noqa: E402
import summerapps                 # noqa: E402

TODAY = datetime.date(2026, 11, 15)
fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def write_tmp(obj):
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))
    return path


print("== 1. a malformed skip rule must never empty the digest ==")
item = {"kid": "dhruv", "title": "Badminton regional"}
keep = {"kid": "dhruv", "title": "Robotics open house"}
for label, raw in [("empty-string term", [{"kid": "dhruv", "match": [""]}]),
                   ("scalar instead of list", [{"kid": "dhruv", "match": "badminton"}]),
                   ("match missing", [{"kid": "dhruv"}]),
                   ("not a list", {"kid": "dhruv", "match": ["x"]}),
                   ("kid missing", [{"match": ["badminton"]}])]:
    secs = {s: [] for s in sd.SKIPPABLE}
    secs["new_discoveries"] = [dict(item), dict(keep)]
    hidden = sd.apply_skips(secs, {"digest": {"skip": raw}})
    check(f"{label} drops nothing", hidden == 0 and len(secs["new_discoveries"]) == 2,
          f"hidden={hidden}")

print("== 2. a valid rule hides only the right kid ==")
rule = {"digest": {"skip": [{"kid": "dhruv", "match": ["badminton", "speech", "debate"],
                             "fields": ["title", "name", "org"]}]}}
secs = {s: [] for s in sd.SKIPPABLE}
secs["new_discoveries"] = [
    {"kid": "dhruv", "title": "Badminton regional"},
    {"kid": "both", "title": "Student Senate (speech and debate skills)"},
    {"kid": "ridhi", "title": "Voice of Democracy speech contest"},
    {"kid": "dhruv", "title": "Robotics open house"},
]
hidden = sd.apply_skips(secs, rule)
titles = [i["title"] for i in secs["new_discoveries"]]
check("dhruv badminton hidden", "Badminton regional" not in titles)
check("kid 'both' survives", any("Student Senate" in t for t in titles))
check("kid 'ridhi' survives", any("Voice of Democracy" in t for t in titles))
check("unrelated dhruv item survives", "Robotics open house" in titles)
check("hidden count reported", hidden == 1, f"hidden={hidden}")

print("== 3. free-text fields are not matched ==")
secs = {s: [] for s in sd.SKIPPABLE}
secs["new_discoveries"] = [{"kid": "dhruv", "title": "Essay contest",
                            "notes": "topic is freedom of speech"}]
sd.apply_skips(secs, rule)
check("a term inside notes does not hide the item", len(secs["new_discoveries"]) == 1)

print("== 4. a broken data file degrades to an empty grid, never an exception ==")
for label, blob in [("invalid json", "{not json"),
                    ("top-level list", "[]"),
                    ("applications not a list", {"applications": {}}),
                    ("entry missing title", {"applications": [{"id": "x", "deadline": "2027-01-01"}]}),
                    ("malformed date", {"applications": [{"title": "T", "deadline": "2026-12"}]}),
                    ("entry not a dict", {"applications": ["nope"]})]:
    path = write_tmp(blob)
    try:
        rows, more, _ = summerapps.load_upcoming(TODAY, path)
        ok = isinstance(rows, list)
    except Exception as e:                                    # noqa: BLE001
        ok, rows = False, f"raised {e!r}"
    finally:
        os.unlink(path)
    check(f"{label} handled", ok, str(rows))

print("== 5. an estimated date never drives a countdown or an expiry ==")
path = write_tmp({"source": {"synced": TODAY.isoformat()}, "applications": [
    {"id": "a", "title": "Fuzzy Dec thing", "deadline": "2026-12-15", "approx": True,
     "until": "2027-01-15", "window": "Registration ~Dec", "action": "Register"},
    {"id": "b", "title": "Real deadline", "deadline": "2026-11-20", "approx": False,
     "until": "2026-11-20", "window": "Nov 20", "action": "Apply"}]})
rows, _, _ = summerapps.load_upcoming(TODAY, path)
by = {r["id"]: r for r in rows}
check("approx row carries no day count", by["a"]["days"] is None)
check("exact row carries a day count", by["b"]["days"] == 5, str(by["b"]["days"]))
when_a, tone_a = sd._when_parts(by["a"])
when_b, tone_b = sd._when_parts(by["b"])
check("approx renders the sheet's words", when_a == "Registration ~Dec", when_a)
check("approx is never coloured urgent", tone_a == "soft", tone_a)
check("exact renders a countdown", "5 days" in when_b, when_b)
check("exact within 7 days is coral", tone_b == "coral", tone_b)
# past its guessed midpoint, still inside the stated window -> still shown
rows2, _, _ = summerapps.load_upcoming(datetime.date(2026, 12, 20), path)
check("a guessed midpoint does not expire a live row", "a" in {r["id"] for r in rows2})
rows3, _, _ = summerapps.load_upcoming(datetime.date(2027, 1, 16), path)
check("the stated window end does expire it", "a" not in {r["id"] for r in rows3})
os.unlink(path)

print("== 6. today == deadline is still shown ==")
path = write_tmp({"source": {"synced": TODAY.isoformat()}, "applications": [
    {"id": "t", "title": "Due today", "deadline": TODAY.isoformat(), "approx": False,
     "until": TODAY.isoformat(), "window": "today", "action": "Send it"}]})
rows, _, _ = summerapps.load_upcoming(TODAY, path)
check("kept on the deadline day", len(rows) == 1 and rows[0]["days"] == 0)
check("renders as today", sd._when_parts(rows[0])[0].endswith("today"))
rows, _, _ = summerapps.load_upcoming(TODAY + datetime.timedelta(days=1), path)
check("gone the day after", rows == [])
os.unlink(path)

print("== 7. HTML and text renderers stay in sync ==")
sections = {s: [] for s in sd.SKIPPABLE}
sections.update({"digest_notes": [], "kid_status": {}, "quarantined": 0,
                 "summer_apps_more": 3, "summer_apps_stale": None})
path = write_tmp({"source": {"synced": TODAY.isoformat()}, "applications": [
    {"id": "a", "title": "Alpha Programme", "org": "Org A", "deadline": "2026-11-20",
     "approx": False, "until": "2026-11-20", "window": "Nov 20", "action": "Apply now",
     "verify": True, "note": "a note"},
    {"id": "b", "title": "Beta Rolling", "org": "Org B", "deadline": None, "approx": False,
     "until": None, "window": "Rolling", "action": "Any time"}]})
sections["summer_apps"], sections["summer_apps_more"], _ = summerapps.load_upcoming(TODAY, path)
os.unlink(path)
html_out = sd.render_html(TODAY, sections, sd.derive_health("full"), [])
text_out = sd.render_text(TODAY, sections, sd.derive_health("full"), [])
for r in sections["summer_apps"]:
    check(f"{r['title']} in HTML", r["title"] in html_out)
    check(f"{r['title']} in text", r["title"] in text_out)
check("grid is a real table", "<table" in html_out)
check("rolling row labelled in both", "Rolling" in html_out and "Rolling" in text_out)

print("== 8. the grid does not mask a quiet day ==")
check("quiet-day line still present", "Quiet day" in html_out, "grid suppressed it")

print("== 9. no-grid case renders nothing extra ==")
sections["summer_apps"], sections["summer_apps_more"] = [], 0
html_empty = sd.render_html(TODAY, sections, sd.derive_health("full"), [])
check("no grid heading when empty", "Summer 2027 applications" not in html_empty)
check("text has no grid heading when empty",
      "SUMMER 2027 APPLICATIONS" not in sd.render_text(TODAY, sections, sd.derive_health("full"), []))

print("== 10. regressions found in the pre-commit diff review ==")
# (a) a non-string field must not reach html.escape and kill the whole digest
path = write_tmp({"source": {"synced": TODAY.isoformat()}, "applications": [
    {"id": "x", "title": "Typed wrong", "org": 5, "note": ["a"], "action": None,
     "deadline": "2027-01-01", "approx": False, "until": "2027-01-01"}]})
rows, _, _ = summerapps.load_upcoming(TODAY, path)
os.unlink(path)
check("non-string fields coerced to str",
      all(isinstance(rows[0][k], str) for k in ("org", "note", "action")))
secs = {s: [] for s in sd.SKIPPABLE}
secs.update({"digest_notes": [], "kid_status": {}, "quarantined": 0,
             "summer_apps": rows, "summer_apps_more": 0, "summer_apps_stale": None})
try:
    sd.render_html(TODAY, secs, sd.derive_health("full"), [])
    sd.render_text(TODAY, secs, sd.derive_health("full"), [])
    ok = True
except Exception as e:                                        # noqa: BLE001
    ok = False
    print(f"      raised {e!r}")
check("a mistyped field cannot take the whole digest down", ok)

# (b) an exact deadline that has passed must disappear, not render as "today"
path = write_tmp({"source": {"synced": TODAY.isoformat()}, "applications": [
    {"id": "past", "title": "Already closed", "deadline": "2026-10-01", "approx": False,
     "until": "2026-12-31", "window": "Oct 1", "action": "too late"}]})
rows, _, _ = summerapps.load_upcoming(TODAY, path)
os.unlink(path)
check("a passed exact deadline is dropped even with a later 'until'", rows == [],
      str([sd._when_parts(r) for r in rows]))

# (c) rolling rows must not be squeezed out by the dated cap
apps = [{"id": f"d{i}", "title": f"Dated {i:02d}", "deadline": f"2027-01-{i:02d}",
         "approx": False, "until": f"2027-01-{i:02d}", "window": "x", "action": "go"}
        for i in range(1, 20)]
apps.append({"id": "roll", "title": "Rolling one", "deadline": None, "until": None,
             "approx": False, "window": "Rolling", "action": "any time", "verify": True})
path = write_tmp({"source": {"synced": TODAY.isoformat()}, "applications": apps})
rows, more, _ = summerapps.load_upcoming(TODAY, path)
os.unlink(path)
ids = [r["id"] for r in rows]
check("rolling row survives the dated cap", "roll" in ids, str(ids))
check("'more' counts only dated rows", more == 19 - summerapps.GRID_MAX, str(more))
check("rolling row drops the meaningless 'confirm the date' hint",
      next(r for r in rows if r["id"] == "roll")["verify"] is False)

# (d) Highlights: only unambiguous terms, and never the other child's
rule_notes = {"digest": {"skip": [{"kid": "dhruv", "match": ["badminton"],
                                   "notes_match": ["badminton", "forensics"]}]}}
secs = {s: [] for s in sd.SKIPPABLE}
secs["digest_notes"] = ["Dhruv's badminton tournament is Saturday.",
                        "Ridhi's speech contest entry is due.",
                        "Band fee due Thursday."]
hidden = sd.apply_skips(secs, rule_notes)
check("a badminton highlight is hidden", not any("badminton" in n for n in secs["digest_notes"]))
check("a speech highlight is NOT hidden (could be either child)",
      any("speech" in n for n in secs["digest_notes"]))
check("unrelated highlight kept", any("Band fee" in n for n in secs["digest_notes"]))
check("highlight count reported", hidden == 1, str(hidden))

print()
if fails:
    print(f"FAIL — {len(fails)} test(s): " + ", ".join(fails))
    sys.exit(1)
print("All digest tests passed.")
