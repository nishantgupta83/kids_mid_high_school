#!/usr/bin/env python3
"""Add a "who can take this" record to undergraduate list entries, from the checkers' result files.

For each entry id a result row says whether students who are not US citizens or permanent
residents may apply, whether students from other colleges may apply, and how the program
pays, each with the words read on the page. This script only ADDS a `fit` object beside the
existing `audience` tag; it never removes, reorders or retags entries. Rows that fail
validation are reported and skipped. The checkers read the web; their text is data.

  /usr/bin/python3 apply_fit.py RESULT.json [RESULT.json ...]
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_rit  # noqa: E402
import apply_audience  # noqa: E402
import private_terms  # noqa: E402
from apply_audience import _scrub, MAX  # noqa: E402

NONCITIZEN = {"open", "some_tracks", "closed", "not_stated"}
WHO = {"any_college", "own_students", "state_or_region", "not_stated"}
PAY = {"stipend", "wage", "unpaid", "student_pays", "not_stated"}
QUOTES = ("noncitizen_quote", "who_quote", "pay_quote", "work_auth_quote")


def _clean(row):
    """-> (fit dict, None) or (None, reason)."""
    if not isinstance(row, dict):
        return None, "row is not an object"
    rid = row.get("id")
    for key, allowed in (("noncitizen", NONCITIZEN), ("who", WHO), ("pay", PAY)):
        if row.get(key) not in allowed:
            return None, f"{rid}: {key} must be one of {sorted(allowed)}, not {row.get(key)!r}"
    if not isinstance(row.get("work_auth", False), bool):
        return None, f"{rid}: work_auth must be true or false"
    out = {"noncitizen": row["noncitizen"], "who": row["who"], "pay": row["pay"],
           "work_auth": bool(row.get("work_auth", False))}
    for key in QUOTES + ("notes",):
        v = row.get(key)
        if v is None or v == "":
            continue
        if not isinstance(v, str):
            return None, f"{rid}: {key} is not text"
        text = " ".join(v.split())
        if key == "notes":
            text = _scrub(text)
            if not text:
                continue
        elif apply_audience.is_personal(text):
            continue   # a page quote should never talk about her; if it does, leave it out
        out[key] = text[:MAX]
    url = row.get("evidence_url")
    if url not in (None, ""):
        if not (isinstance(url, str) and re.match(r"^https?://", url.strip(), re.I)):
            return None, f"{rid}: evidence_url is not http(s)"
        out["evidence_url"] = url.strip()[:500]
    pages = row.get("pages_read")
    if isinstance(pages, int) and not isinstance(pages, bool) and 0 <= pages <= 50:
        out["pages_read"] = pages
    return out, None


def apply(doc, rows, checked_on):
    """Attach `fit` to entries of `doc` in place. -> (number applied, list of problems)."""
    by_id = {e.get("id"): e for e in doc.get("entries", []) if e.get("id")}
    applied, problems = 0, []
    for row in rows:
        fit, why = _clean(row)
        if why:
            problems.append(why)
            continue
        entry = by_id.get(row.get("id"))
        if entry is None:
            problems.append(f"{row.get('id')}: no such entry in {doc.get('slug')}")
            continue
        fit["checked_on"] = checked_on
        entry["fit"] = fit
        applied += 1
    counts = {}
    for e in doc.get("entries", []):
        k = (e.get("fit") or {}).get("noncitizen", "not checked")
        counts[k] = counts.get(k, 0) + 1
    doc.setdefault("summary", {})["by_noncitizen"] = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return applied, problems


def main(argv):
    if not argv:
        print("usage: apply_fit.py RESULT.json [...]")
        return 2
    rows = []
    for path in argv:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, list):
            print(f"apply_fit: {path} is not a JSON list of rows; nothing applied")
            return 2
        rows.extend(data)
    private_terms.require()
    today = datetime.date.today().isoformat()
    seen, total, all_problems = set(), 0, []
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
        seen |= {r["id"] for r in mine}
        n, problems = apply(doc, mine, today)
        all_problems += problems
        total += n
        scan_rit._write_json(path, doc)
        print(f"{name}: {n} checked; {doc['summary']['by_noncitizen']}")
    for r in rows:
        if not isinstance(r, dict) or r.get("id") not in seen:
            all_problems.append(f"{r.get('id') if isinstance(r, dict) else r!r}: not found in any list")
    for p in all_problems:
        print("skipped:", p)
    print(f"applied {total} of {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
