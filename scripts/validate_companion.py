#!/usr/bin/env python3
"""Validate the Class Companion curriculum: manifest + every course file.

Exit 0 = clean, 1 = failure. Stdlib only; run with /usr/bin/python3.
"""
import json
import re
import sys
from pathlib import Path

CUR = Path("/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school/companion/public/curriculum")
ACCENTS = {"coral", "teal", "sage", "sky", "amber"}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
errors = []


def err(m):
    errors.append(m)


def main():
    manifest = json.loads((CUR / "manifest.json").read_text())
    courses = manifest.get("courses", [])
    if len(courses) != 6:
        err(f"manifest: expected 6 courses, found {len(courses)}")

    ids = [c["id"] for c in courses]
    if len(ids) != len(set(ids)):
        err("manifest: duplicate course id")

    for kd in manifest.get("key_dates", []):
        if not ISO.match(kd.get("date", "")):
            err(f"manifest key_date bad date: {kd}")

    for c in courses:
        for f in ("id", "title", "short", "accent", "file"):
            if f not in c:
                err(f"manifest course {c.get('id')}: missing {f}")
        if c.get("accent") not in ACCENTS:
            err(f"manifest course {c.get('id')}: bad accent {c.get('accent')}")
        path = CUR / c["file"]
        if not path.exists():
            err(f"course file missing: {c['file']}")
            continue
        doc = json.loads(path.read_text())
        if doc.get("id") != c["id"]:
            err(f"{c['file']}: id mismatch ({doc.get('id')} vs {c['id']})")
        for f in ("title", "overview", "how_to_study_course", "resources", "units"):
            if f not in doc:
                err(f"{c['file']}: missing {f}")
        if not doc.get("units"):
            err(f"{c['file']}: no units")
        for u in doc.get("units", []):
            for f in ("id", "title", "topics", "how_to_study"):
                if f not in u:
                    err(f"{c['file']} unit {u.get('id')}: missing {f}")
        for r in doc.get("resources", []):
            if not str(r.get("url", "")).startswith("http"):
                err(f"{c['file']}: resource url not http: {r.get('label')}")

    print(f"  courses: {len(courses)}")
    for c in courses:
        p = CUR / c["file"]
        if p.exists():
            n = len(json.loads(p.read_text()).get("units", []))
            print(f"    {c['id']}: {n} units")
    if errors:
        print(f"\nFAIL — {len(errors)} error(s):")
        for e in errors:
            print("  -", e)
        return 1
    print("OK — companion curriculum valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
