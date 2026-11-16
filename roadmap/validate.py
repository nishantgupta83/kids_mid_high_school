#!/usr/bin/env python3
"""Validate roadmap/data/*.json: structure, ids, dates, links, and a PII lint.

The roadmap is self-contained on purpose. It has its own validator so that a bad
roadmap row can never fail scripts/validate_data.py and trigger the school scan's
`git checkout -- data/` rollback. Stdlib only; run with /usr/bin/python3.

Exit 0 = clean, 1 = errors (printed one per line).
"""
import json
import os
import re
import sys

ROADMAP = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school/roadmap"
DATA = os.path.join(ROADMAP, "data")

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ITEM_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
HHMM = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
LEVELS = {"ap", "honors", "regular", "activity"}
LANES = {"school", "tests", "summer", "projects", "music", "college", "canada", "status"}
ELIGIBILITY = {"open", "verify", "closed"}

# Same patterns as scripts/validate_data.py: committed files carry first names only.
PII_PATTERNS = [
    ("email address", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("phone number", re.compile(r"(\+1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b")),
    ("family last name", re.compile(r"\bGupta\b", re.IGNORECASE)),
]

FILES = ("start.json", "courses.json", "summers.json", "milestones.json", "source_docs.json", "money.json",
         "options.json", "status.json", "community.json")
CONFIDENCE = {"confirmed", "partly", "unconfirmed"}
AWARD_KINDS = {"resident-tuition", "automatic", "competitive", "need-based"}
ASK = {"attorney", "campus residence office", "school counsellor", "Canadian immigration consultant"}


def _load(data_dir, name, errors):
    path = os.path.join(data_dir, name)
    try:
        with open(path) as f:
            text = f.read()
        doc = json.loads(text)
    except OSError:
        errors.append(f"{name}: file missing or unreadable")
        return None
    except ValueError as e:
        errors.append(f"{name}: not valid JSON ({e})")
        return None
    for label, pattern in PII_PATTERNS:
        for m in pattern.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            errors.append(f"PII LINT {name}:{line}: {label}")
    if not isinstance(doc, dict):
        errors.append(f"{name}: top level must be an object")
        return None
    return doc


def _rows(doc, key, name, errors):
    rows = doc.get(key) if doc else None
    if not isinstance(rows, list):
        if doc is not None:
            errors.append(f"{name}: '{key}' must be a list")
        return []
    return [r for r in rows if isinstance(r, dict)] if all(isinstance(r, dict) for r in rows) else \
        (errors.append(f"{name}: every '{key}' row must be an object") or [])


def _ids(rows, where, errors, seen=None):
    seen = set() if seen is None else seen
    for r in rows:
        rid = r.get("id")
        if not isinstance(rid, str) or not ITEM_ID.match(rid):
            errors.append(f"{where}: bad id {rid!r}")
        elif rid in seen:
            errors.append(f"{where}: duplicate id {rid!r}")
        else:
            seen.add(rid)
    return seen


def _text(r, field, where, errors, required=True):
    v = r.get(field)
    if v is None and not required:
        return
    if not isinstance(v, str) or (required and not v.strip()):
        errors.append(f"{where} {r.get('id')}: '{field}' must be text")


def _date(r, field, where, errors, required=True):
    v = r.get(field)
    if v is None and not required:
        return
    if not isinstance(v, str) or not ISO_DATE.match(v):
        errors.append(f"{where} {r.get('id')}: '{field}' is not a YYYY-MM-DD date")


def _url(r, field, where, errors):
    v = r.get(field)
    if v is None:
        return
    if not isinstance(v, str) or not re.match(r"^https?://", v):
        errors.append(f"{where} {r.get('id')}: '{field}' url must be http(s)")


def validate(data_dir=DATA):
    """Return a list of error strings (empty = clean). Never raises."""
    errors = []
    docs = {name: _load(data_dir, name, errors) for name in FILES}

    start = docs["start.json"]
    for key in ("assumptions", "flags"):
        rows = _rows(start, key, "start.json", errors)
        _ids(rows, f"start.json {key}", errors)
        for r in rows:
            _text(r, "text", f"start.json {key}", errors)
    decisions = _rows(start, "decisions", "start.json", errors)
    _ids(decisions, "start.json decisions", errors)
    for r in decisions:
        _text(r, "title", "start.json decisions", errors)
        _date(r, "by", "start.json decisions", errors)
        if not isinstance(r.get("exact"), bool):
            errors.append(f"start.json decisions {r.get('id')}: 'exact' must be true or false")
        if not isinstance(r.get("options", []), list):
            errors.append(f"start.json decisions {r.get('id')}: 'options' must be a list")

    courses = docs["courses.json"]
    seen = set()
    for key in ("grade10", "grade11", "grade12", "candidates"):
        rows = _rows(courses, key, "courses.json", errors)
        _ids(rows, f"courses.json {key}", errors, seen)
        for r in rows:
            _text(r, "title", f"courses.json {key}", errors)
            if r.get("level") not in LEVELS:
                errors.append(f"courses.json {key} {r.get('id')}: level must be one of {sorted(LEVELS)}")
    commitments = _rows(courses, "commitments", "courses.json", errors)
    _ids(commitments, "courses.json commitments", errors)
    for c in commitments:
        _text(c, "title", "courses.json commitments", errors)
        if c.get("when") not in ("season", "year"):
            errors.append(f"courses.json commitments {c.get('id')}: 'when' must be 'season' or 'year'")
        blocks = c.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            errors.append(f"courses.json commitments {c.get('id')}: needs at least one block")
            continue
        for i, b in enumerate(blocks):
            timed = isinstance(b, dict) and all(isinstance(b.get(k), str) and HHMM.match(b[k]) for k in ("start", "end"))
            hours = isinstance(b, dict) and isinstance(b.get("hours"), (int, float)) and not isinstance(b.get("hours"), bool) and b["hours"] > 0
            if not (isinstance(b, dict) and b.get("day") in (1, 2, 3, 4, 5, 6, 7) and (timed or hours)):
                errors.append(f"courses.json commitments {c.get('id')} block {i}: needs day 1-7 and HH:MM start/end or positive hours")

    summers = docs["summers.json"]
    options = _rows(summers, "options", "summers.json", errors)
    _ids(options, "summers.json options", errors)
    for r in options:
        _text(r, "title", "summers.json options", errors)
        if r.get("year") not in (2027, 2028):
            errors.append(f"summers.json options {r.get('id')}: year must be 2027 or 2028")
        if r.get("eligibility") not in ELIGIBILITY:
            errors.append(f"summers.json options {r.get('id')}: eligibility must be one of {sorted(ELIGIBILITY)}")
        _date(r, "keep_open_by", "summers.json options", errors, required=False)
        if "keep_open_by" in r and not isinstance(r.get("exact"), bool):
            errors.append(f"summers.json options {r.get('id')}: 'exact' must be true or false")
        _url(r, "url", "summers.json options", errors)

    miles = _rows(docs["milestones.json"], "milestones", "milestones.json", errors)
    _ids(miles, "milestones.json", errors)
    for r in miles:
        _text(r, "title", "milestones.json", errors)
        _date(r, "date", "milestones.json", errors)
        if not isinstance(r.get("exact"), bool):
            errors.append(f"milestones.json {r.get('id')}: 'exact' must be true or false")
        if r.get("lane") not in LANES:
            errors.append(f"milestones.json {r.get('id')}: lane must be one of {sorted(LANES)}")

    sources = _rows(docs["source_docs.json"], "sources", "source_docs.json", errors)
    _ids(sources, "source_docs.json", errors)
    for r in sources:
        _text(r, "title", "source_docs.json", errors)
        _url(r, "url", "source_docs.json", errors)
        _date(r, "dated", "source_docs.json", errors, required=False)

    money = docs["money.json"]
    if money is not None and not (isinstance(money.get("checked_on"), str) and ISO_DATE.match(money["checked_on"])):
        errors.append("money.json: 'checked_on' is not a YYYY-MM-DD date")
    points = _rows(money, "points", "money.json", errors)
    awards = _rows(money, "awards", "money.json", errors)
    _ids(points, "money.json points", errors)
    _ids(awards, "money.json awards", errors)
    for where, rows in (("money.json points", points), ("money.json awards", awards)):
        for r in rows:
            if r.get("confidence") not in CONFIDENCE:
                errors.append(f"{where} {r.get('id')}: confidence must be one of {sorted(CONFIDENCE)}")
            _url(r, "url", where, errors)
            # "Confirmed" is a claim about a source the parent can open: no link, no claim.
            if r.get("confidence") == "confirmed" and not r.get("url"):
                errors.append(f"{where} {r.get('id')}: a confirmed row needs its source url")
    for r in points:
        _text(r, "text", "money.json points", errors)
    for r in awards:
        for field in ("school", "award", "amount", "needs", "group"):
            _text(r, field, "money.json awards", errors)
        if r.get("kind") not in AWARD_KINDS:
            errors.append(f"money.json awards {r.get('id')}: kind must be one of {sorted(AWARD_KINDS)}")
    for key in ("how_to_read", "ask_each_college", "not_yet_checked"):
        v = money.get(key) if money else None
        if money is not None and not (isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v)):
            errors.append(f"money.json: '{key}' must be a list of text lines")

    def researched(rows, where):
        """Every researched statement says how far it was confirmed; 'confirmed' needs a link."""
        for r in rows:
            label = r.get("id") or (r.get("text") or "")[:40]
            if r.get("confidence") not in CONFIDENCE:
                errors.append(f"{where} {label}: confidence must be one of {sorted(CONFIDENCE)}")
            _url(r, "url", where, errors)
            if r.get("confidence") == "confirmed" and not r.get("url") and not r.get("sources"):
                errors.append(f"{where} {label}: a confirmed row needs its source url")
            if not isinstance(r.get("text"), str) or not r["text"].strip():
                errors.append(f"{where} {label}: 'text' must be text")

    options = docs["options.json"]
    routes = _rows(options, "routes", "options.json", errors)
    _ids(routes, "options.json routes", errors)
    for r in routes:
        for field in ("title", "summary", "leads_to", "place"):
            _text(r, field, "options.json routes", errors)
        facts = r.get("facts")
        if not isinstance(facts, list) or not facts or not all(isinstance(f, dict) for f in facts):
            errors.append(f"options.json routes {r.get('id')}: needs a list of facts")
        else:
            researched(facts, f"options.json {r.get('id')} fact")
        if not (isinstance(r.get("watch", []), list) and all(isinstance(x, str) for x in r.get("watch", []))):
            errors.append(f"options.json routes {r.get('id')}: 'watch' must be a list of text lines")

    status = docs["status.json"]
    facts = _rows(status, "facts", "status.json", errors)
    _ids(facts, "status.json facts", errors)
    researched(facts, "status.json fact")
    ages = _rows(status, "ages", "status.json", errors)
    _ids(ages, "status.json ages", errors)
    for r in ages:
        _date(r, "date", "status.json ages", errors)
        _text(r, "title", "status.json ages", errors)
    questions = _rows(status, "questions", "status.json", errors)
    _ids(questions, "status.json questions", errors)
    for r in questions:
        _text(r, "text", "status.json questions", errors)
        if r.get("ask") not in ASK:
            errors.append(f"status.json questions {r.get('id')}: 'ask' must be one of {sorted(ASK)}")
    bulletin = status.get("bulletin") if status else None
    if status is not None:
        if not isinstance(bulletin, dict) or not re.match(r"^\d{4}-\d{2}$", str(bulletin.get("month", ""))):
            errors.append("status.json bulletin: needs a 'month' as YYYY-MM")
        else:
            if bulletin.get("confidence") not in CONFIDENCE:
                errors.append("status.json bulletin: confidence must be one of " + str(sorted(CONFIDENCE)))
            rows = bulletin.get("rows") if isinstance(bulletin.get("rows"), list) else []
            _ids([r for r in rows if isinstance(r, dict)], "status.json bulletin", errors)
            for r in rows:
                if not isinstance(r, dict):
                    continue
                _text(r, "label", "status.json bulletin", errors)
                for field in ("final_action", "filing"):
                    _date(r, field, "status.json bulletin", errors)

    community = docs["community.json"]
    patterns = _rows(community, "patterns", "community.json", errors)
    _ids(patterns, "community.json patterns", errors)
    for r in patterns:
        for field in ("title", "text", "kind"):
            _text(r, field, "community.json patterns", errors)
        if r.get("confidence") not in CONFIDENCE:
            errors.append(f"community.json patterns {r.get('id')}: confidence must be one of {sorted(CONFIDENCE)}")
        sources = r.get("sources")
        if not isinstance(sources, list) or not sources:
            errors.append(f"community.json patterns {r.get('id')}: needs at least one source")
            continue
        for s in sources:
            if not isinstance(s, dict) or not isinstance(s.get("title"), str) or not isinstance(s.get("url"), str) \
                    or not re.match(r"^https?://", s["url"]):
                errors.append(f"community.json patterns {r.get('id')}: every source needs a title and an http(s) url")

    return errors


def main():
    errors = validate()
    for e in errors:
        print(e)
    if errors:
        print(f"FAIL — {len(errors)} problem(s) in roadmap data")
        return 1
    print("OK — roadmap data valid, PII lint clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
