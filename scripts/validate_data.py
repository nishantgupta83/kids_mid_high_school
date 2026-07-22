#!/usr/bin/env python3
"""Validate all committed data/*.json files: structure, enums, cross-refs, PII lint.

Exit 0 = clean. Exit 1 = any failure (scan.sh must refuse to commit).
Stdlib only; run with /usr/bin/python3.
"""
import json
import re
import sys
from pathlib import Path

REPO = Path("/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school")
DATA = REPO / "data"

KID = {"ridhi", "dhruv", "both", "family"}
SOURCE_CATEGORY = {"volunteer", "club", "event", "athletics", "library", "school-page", "program"}
SCAN_METHOD = {"http_diff", "json_api", "ical", "manual"}
SCAN_FREQ = {"daily", "weekly", "window_only"}
SOURCE_STATUS = {"active", "watch", "dormant", "retired"}
RECURRENCE = {"rolling", "annual", "one_time"}
CONFIDENCE = {"verified", "estimated"}
OPP_CATEGORY = {"volunteer-bio", "volunteer-general", "program", "club", "event"}
OPP_REGION = {"tri-valley", "bay-area", "virtual"}
PIPELINE_STATUS = {"new", "discuss", "applied", "enrolled", "passed"}
EVENT_TYPE = {"school", "deadline", "break", "test", "athletics", "community", "homework"}
EVENT_SOURCE_KIND = {"email", "registry", "static", "discovery"}
EVENT_STATUS = {"active", "done", "expired"}
WATCH_STATE = {"waiting", "window_open", "converted", "missed"}

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# PII lint: committed state must never carry addresses/emails/phones/last names.
PII_PATTERNS = [
    ("email address", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("phone number", re.compile(r"(\+1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b")),
    ("family last name", re.compile(r"\bGupta\b")),
]

errors = []


def err(msg):
    errors.append(msg)


def load(name):
    path = DATA / name
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:  # parse or IO failure is fatal for that file
        err(f"{name}: cannot load ({e})")
        return None


def check_date(name, where, value, allow_null=True):
    if value is None:
        if not allow_null:
            err(f"{name}: {where} date is null but required")
        return
    if not isinstance(value, str) or not ISO_DATE.match(value):
        err(f"{name}: {where} bad date {value!r}")


def check_enum(name, where, value, allowed, allow_null=False):
    if value is None and allow_null:
        return
    if value not in allowed:
        err(f"{name}: {where} value {value!r} not in {sorted(allowed)}")


def check_unique(name, what, values):
    seen = set()
    for v in values:
        if v in seen:
            err(f"{name}: duplicate {what}: {v!r}")
        seen.add(v)


def validate_sources(doc):
    sources = doc.get("sources", [])
    check_unique("sources.json", "id", [s.get("id") for s in sources])
    for s in sources:
        sid = s.get("id", "<missing-id>")
        for field in ("id", "name", "kid", "category", "url", "scan", "eligibility", "application_window", "priority", "status", "provenance"):
            if field not in s:
                err(f"sources.json[{sid}]: missing field {field}")
        check_enum(f"sources.json[{sid}]", "kid", s.get("kid"), KID)
        check_enum(f"sources.json[{sid}]", "category", s.get("category"), SOURCE_CATEGORY)
        check_enum(f"sources.json[{sid}]", "status", s.get("status"), SOURCE_STATUS)
        if not str(s.get("url", "")).startswith("http"):
            err(f"sources.json[{sid}]: url must be http(s)")
        if s.get("priority") not in (1, 2, 3):
            err(f"sources.json[{sid}]: priority must be 1..3")
        scan = s.get("scan", {})
        check_enum(f"sources.json[{sid}]", "scan.method", scan.get("method"), SCAN_METHOD)
        check_enum(f"sources.json[{sid}]", "scan.frequency", scan.get("frequency"), SCAN_FREQ)
        check_date(f"sources.json[{sid}]", "scan.next_check_date", scan.get("next_check_date"))
        win = s.get("application_window", {})
        check_enum(f"sources.json[{sid}]", "window.recurrence", win.get("recurrence"), RECURRENCE)
        check_enum(f"sources.json[{sid}]", "window.confidence", win.get("confidence"), CONFIDENCE)
        check_date(f"sources.json[{sid}]", "window.opens", win.get("opens"))
        check_date(f"sources.json[{sid}]", "window.closes", win.get("closes"))
    return {s.get("id") for s in sources}


def validate_opportunities(doc, source_ids):
    opps = doc.get("opportunities", [])
    check_unique("opportunities.json", "id", [o.get("id") for o in opps])
    check_unique("opportunities.json", "dedupe_key", [o.get("dedupe_key") for o in opps])
    for o in opps:
        oid = o.get("id", "<missing-id>")
        for field in ("id", "dedupe_key", "kid", "title", "org", "url", "category", "region", "eligibility", "window", "pipeline", "provenance"):
            if field not in o:
                err(f"opportunities.json[{oid}]: missing field {field}")
        check_enum(f"opportunities.json[{oid}]", "kid", o.get("kid"), KID)
        check_enum(f"opportunities.json[{oid}]", "category", o.get("category"), OPP_CATEGORY)
        check_enum(f"opportunities.json[{oid}]", "region", o.get("region"), OPP_REGION)
        elig = (o.get("eligibility") or {}).get("eligible_now")
        if not (elig in ("yes", "no", "check") or (isinstance(elig, str) and elig.startswith("from:"))):
            err(f"opportunities.json[{oid}]: eligibility.eligible_now {elig!r} invalid")
        pipe = o.get("pipeline", {})
        check_enum(f"opportunities.json[{oid}]", "pipeline.status", pipe.get("status"), PIPELINE_STATUS)
        if not pipe.get("history"):
            err(f"opportunities.json[{oid}]: pipeline.history empty")
        src = (o.get("provenance") or {}).get("source_id")
        if src not in source_ids:
            err(f"opportunities.json[{oid}]: provenance.source_id {src!r} not in sources.json")


def validate_events(doc):
    events = doc.get("events", [])
    check_unique("events.json", "id", [e.get("id") for e in events])
    check_unique("events.json", "dedupe_key", [e.get("dedupe_key") for e in events])
    for e in events:
        eid = e.get("id", "<missing-id>")
        for field in ("id", "dedupe_key", "kid", "title", "date", "type", "source", "status"):
            if field not in e:
                err(f"events.json[{eid}]: missing field {field}")
        check_enum(f"events.json[{eid}]", "kid", e.get("kid"), KID)
        check_enum(f"events.json[{eid}]", "type", e.get("type"), EVENT_TYPE)
        check_enum(f"events.json[{eid}]", "status", e.get("status"), EVENT_STATUS)
        check_date(f"events.json[{eid}]", "date", e.get("date"), allow_null=False)
        check_date(f"events.json[{eid}]", "end_date", e.get("end_date"))
        check_enum(f"events.json[{eid}]", "source.kind", (e.get("source") or {}).get("kind"), EVENT_SOURCE_KIND)
        action = e.get("action")
        if action is not None:
            if not isinstance(action, dict) or "what" not in action:
                err(f"events.json[{eid}]: action must be null or have 'what'")
            else:
                check_date(f"events.json[{eid}]", "action.due", action.get("due"))


def validate_watchlist(doc, source_ids):
    watches = doc.get("watchlist", [])
    check_unique("watchlist.json", "id", [w.get("id") for w in watches])
    for w in watches:
        wid = w.get("id", "<missing-id>")
        for field in ("id", "source_id", "kid", "title", "check_from", "why", "alert_days_before", "state"):
            if field not in w:
                err(f"watchlist.json[{wid}]: missing field {field}")
        check_enum(f"watchlist.json[{wid}]", "kid", w.get("kid"), KID)
        check_enum(f"watchlist.json[{wid}]", "state", w.get("state"), WATCH_STATE)
        check_date(f"watchlist.json[{wid}]", "check_from", w.get("check_from"), allow_null=False)
        check_date(f"watchlist.json[{wid}]", "expected_open", w.get("expected_open"))
        check_date(f"watchlist.json[{wid}]", "hard_deadline", w.get("hard_deadline"))
        if w.get("source_id") not in source_ids:
            err(f"watchlist.json[{wid}]: source_id {w.get('source_id')!r} not in sources.json")


def pii_lint():
    """Scan every COMMITTED data file for PII patterns. Gitignored dirs are exempt."""
    skip_dirs = {"local", "snapshots", "digests"}
    hits = 0
    for path in sorted(DATA.rglob("*.json")):
        rel = path.relative_to(DATA)
        if rel.parts[0] in skip_dirs:
            continue
        text = path.read_text()
        for label, pattern in PII_PATTERNS:
            for m in pattern.finditer(text):
                line = text[: m.start()].count("\n") + 1
                err(f"PII LINT {rel}:{line}: {label} {m.group(0)!r}")
                hits += 1
    return hits


def main():
    counts = {}
    sources_doc = load("sources.json")
    source_ids = validate_sources(sources_doc) if sources_doc else set()
    counts["sources"] = len(sources_doc.get("sources", [])) if sources_doc else 0

    opps_doc = load("opportunities.json")
    if opps_doc:
        validate_opportunities(opps_doc, source_ids)
        counts["opportunities"] = len(opps_doc.get("opportunities", []))

    events_doc = load("events.json")
    if events_doc:
        validate_events(events_doc)
        counts["events"] = len(events_doc.get("events", []))

    watch_doc = load("watchlist.json")
    if watch_doc:
        validate_watchlist(watch_doc, source_ids)
        counts["watchlist"] = len(watch_doc.get("watchlist", []))

    for name in ("school_year.json", "sources_proposed.json", "state/last_run.json", "state/email_cursor.json"):
        load(name)  # parse check only

    pii_lint()

    for k, v in counts.items():
        print(f"  {k}: {v}")
    if errors:
        print(f"\nFAIL — {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK — all data files valid, PII lint clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
