#!/usr/bin/env python3
"""Add "who is this for" tags to published lists, from the checkers' result files.

Each result row says, for one entry id, whether the program is for high school students,
college, graduate, etc., with a quote and the page it was read on. This script only ADDS
an `audience` object to matching entries; it never removes or reorders entries. Rows that
fail validation are reported and skipped. The checkers read the web; their text is data.

  /usr/bin/python3 apply_audience.py RESULT.json [RESULT.json ...]

Writes dashboard/public/lists/<list>.json for every list that had a matching id.
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_rit  # noqa: E402
import private_terms  # noqa: E402

# Sentences in the checkers' notes that reason about this particular student (age on a
# date, her visa) are dropped: the lists are public files. The family-specific words
# (her birthday, visa type) come from the gitignored private terms file.
_ABOUT_HER_GENERIC = (r"turns? 16|turned 16|turning 16|\bshe\b|\bher\b|"
                      r"the student|this student|a student (on|who|turning)|would (miss|be met|qualify|not qualify|be ineligible)|"
                      r"\b1[3-7]-year-old\b|\bis 1[3-7]\b|too young|birthday|\bborn\b|daughter|\bridhi\b|\bpari\b")

# Narrower check for the page-derived fields (quote, dates, grades...): a program's own
# start date is fine there even if it matches her birthday; names and her visa are not.
_PERSONAL_GENERIC = (r"\bshe\b|\bher\b|turns? 16|turned 16|turning 16|\b1[3-7]-year-old\b|"
                     r"birthday|\bborn\b|daughter|\bridhi\b|\bpari\b")


def configure(terms):
    """(Re)build both checks from a private-terms dict (tests pass fake terms)."""
    global _ABOUT_HER, _PERSONAL
    _ABOUT_HER = re.compile("|".join([_ABOUT_HER_GENERIC] + terms.get("scrub_notes", [])), re.I)
    _PERSONAL = re.compile("|".join([_PERSONAL_GENERIC] + terms.get("scrub_fields", [])), re.I)


configure(private_terms.load())


def is_personal(text):
    return bool(_PERSONAL.search(text))


def _scrub(text):
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [s for s in sentences if s and not _ABOUT_HER.search(s)]
    return " ".join(kept).strip()


def scrub_doc(doc):
    for e in doc.get("entries", []):
        a = e.get("audience")
        if isinstance(a, dict) and isinstance(a.get("notes"), str):
            cleaned = _scrub(a["notes"])
            if cleaned:
                a["notes"] = cleaned
            else:
                a.pop("notes")
    return doc


TAGS = {"high_school", "college", "graduate", "general", "teachers", "unclear", "gone"}
TEXT_FIELDS = ("quote", "min_age", "citizenship", "grades", "cost_or_pay", "dates", "notes")
MAX = 300


def _clean(row):
    """-> (audience dict, None) or (None, reason)."""
    if not isinstance(row, dict):
        return None, "row is not an object"
    if row.get("tag") not in TAGS:
        return None, f"{row.get('id')}: unknown tag {row.get('tag')!r}"
    out = {"tag": row["tag"]}
    for key in TEXT_FIELDS:
        v = row.get(key)
        if v is None or v == "":
            continue
        if not isinstance(v, str):
            return None, f"{row.get('id')}: {key} is not text"
        text = " ".join(v.split())
        if key == "notes":
            text = _scrub(text)
            if not text:
                continue
        elif is_personal(text):
            continue   # a page-derived field should never talk about her; if it does, leave it out
        out[key] = text[:MAX]
    url = row.get("evidence_url")
    if url not in (None, ""):
        if not (isinstance(url, str) and re.match(r"^https?://", url.strip(), re.I)):
            return None, f"{row.get('id')}: evidence_url is not http(s)"
        out["evidence_url"] = url.strip()[:500]
    pages = row.get("pages_read")
    if isinstance(pages, int) and not isinstance(pages, bool) and 0 <= pages <= 50:
        out["pages_read"] = pages
    return out, None


def apply(doc, rows, checked_on):
    """Attach tags to `doc` in place. -> (number applied, list of problems)."""
    by_id = {e.get("id"): e for e in doc.get("entries", []) if e.get("id")}
    applied, problems = 0, []
    for row in rows:
        audience, why = _clean(row)
        if why:
            problems.append(why)
            continue
        entry = by_id.get(row.get("id"))
        if entry is None:
            problems.append(f"{row.get('id')}: no such entry in {doc.get('slug')}")
            continue
        audience["checked_on"] = checked_on
        entry["audience"] = audience
        applied += 1
    counts = {}
    for e in doc.get("entries", []):
        k = (e.get("audience") or {}).get("tag", "not checked")
        counts[k] = counts.get(k, 0) + 1
    doc.setdefault("summary", {})["by_audience"] = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return applied, problems


def main(argv):
    private_terms.require()
    if argv == ["--scrub"]:
        for name in sorted(os.listdir(scan_rit.OUT_DIR)):
            if name.endswith(".json") and name not in ("index.json", "notes.json"):
                path = os.path.join(scan_rit.OUT_DIR, name)
                with open(path) as f:
                    doc = json.load(f)
                scan_rit._write_json(path, scrub_doc(doc))
                print("scrubbed", name)
        return 0
    if not argv:
        print("usage: apply_audience.py RESULT.json [...]")
        return 2
    rows = []
    for path in argv:
        with open(path) as f:
            data = json.load(f)
        rows.extend(data if isinstance(data, list) else [])
    today = datetime.date.today().isoformat()
    total, all_problems = 0, []
    for name in sorted(os.listdir(scan_rit.OUT_DIR)):
        if not name.endswith(".json") or name in ("index.json", "notes.json"):
            continue
        path = os.path.join(scan_rit.OUT_DIR, name)
        with open(path) as f:
            doc = json.load(f)
        ids = {e.get("id") for e in doc.get("entries", [])}
        mine = [r for r in rows if isinstance(r, dict) and r.get("id") in ids]
        if not mine:
            continue
        n, problems = apply(doc, mine, today)
        all_problems += problems
        total += n
        scan_rit._write_json(path, doc)
        print(f"{name}: {n} tagged; {doc['summary']['by_audience']}")
    known = {e_id for name in os.listdir(scan_rit.OUT_DIR) if name.endswith(".json") and name not in ("index.json", "notes.json")
             for e_id in (e.get("id") for e in json.load(open(os.path.join(scan_rit.OUT_DIR, name))).get("entries", []))}
    for r in rows:
        if not isinstance(r, dict) or r.get("id") not in known:
            all_problems.append(f"{r.get('id') if isinstance(r, dict) else r!r}: not found in any list")
    for p in all_problems:
        print("skipped:", p)
    print(f"applied {total} of {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
