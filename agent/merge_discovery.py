#!/usr/bin/env python3
"""Merge weekly-discovery LLM output. Discovery NEVER auto-adds to sources.json.

- relocated_urls + proposed_sources → data/sources_proposed.json (state "pending"),
  awaiting the parent's approve/dismiss on the dashboard. Relocations carry
  replaces_source_id so approval swaps the dead source's URL.
- one_off_events → events.json as source.kind="discovery" (rendered "unverified —
  check link"); deterministic dedupe; past dates skipped.

Bad items are quarantined (gitignored). Non-dict envelope → exit 1, nothing written.
Usage: merge_discovery.py --llm-output <path> [--dry-run]
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomicio import read_json, write_json
from lib.runlog import log
from merge_results import event_key, slug, KID

REPO = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"
DATA = os.path.join(REPO, "data")
LOCAL = os.path.join(DATA, "local")

PROP_ID = re.compile(r"^prop-[a-z0-9-]{2,76}$")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SRC_CATEGORY = {"volunteer", "club", "event", "program", "athletics", "library", "school-page"}
SCAN_METHOD = {"http_diff", "json_api", "manual"}
OPP_KID = {"ridhi", "dhruv", "both"}


def valid_proposal(p, existing_ids, existing_urls):
    if not isinstance(p, dict):
        return False
    if not PROP_ID.match(str(p.get("id", ""))):
        return False
    if p.get("kid") not in OPP_KID or p.get("category") not in SRC_CATEGORY:
        return False
    if p.get("scan_method") not in SCAN_METHOD:
        return False
    if not str(p.get("url", "")).startswith("http"):
        return False
    if p["id"] in existing_ids or p["url"] in existing_urls:
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm-output", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    today = datetime.date.today()

    try:
        with open(args.llm_output) as f:
            out = json.load(f)
        if not isinstance(out, dict):
            raise ValueError("not an object")
    except Exception as e:
        log(f"merge_discovery: REJECT envelope ({e}) — nothing written")
        return 1

    sources = read_json(os.path.join(DATA, "sources.json"))["sources"]
    src_by_id = {s["id"]: s for s in sources}
    proposed_doc = read_json(os.path.join(DATA, "sources_proposed.json"), {"proposals": []})
    proposed = proposed_doc["proposals"]
    prop_ids = {p["id"] for p in proposed}
    prop_urls = {p["url"] for p in proposed}
    covered_urls = {s["url"] for s in sources}

    events_doc = read_json(os.path.join(DATA, "events.json"))
    events = events_doc["events"]
    event_keys = {e["dedupe_key"] for e in events}
    event_ids = {e["id"] for e in events}

    added_prop, added_evt, quarantined = 0, 0, []

    # Relocations → proposed sources with replaces_source_id
    for rel in (out.get("relocated_urls") or []):
        sid = rel.get("source_id") if isinstance(rel, dict) else None
        url = rel.get("new_url", "") if isinstance(rel, dict) else ""
        if sid not in src_by_id or not str(url).startswith("http"):
            quarantined.append({"kind": "relocation", "item": rel})
            continue
        pid = f"prop-relocate-{sid}"
        if pid in prop_ids:
            continue
        s = src_by_id[sid]
        proposed.append({
            "id": pid, "name": f"[relocate] {s['name']}", "kid": s["kid"], "category": s["category"],
            "url": url, "scan_method": s["scan"]["method"], "why": f"Found a live URL for the dead source '{s['name']}'",
            "eligibility_note": "", "replaces_source_id": sid, "found": today.isoformat(),
            "confidence": "estimated", "state": "pending", "evidence": str(rel.get("evidence", ""))[:400],
        })
        prop_ids.add(pid); added_prop += 1

    # New proposed sources
    for p in (out.get("proposed_sources") or []):
        if not valid_proposal(p, prop_ids, prop_urls | covered_urls):
            quarantined.append({"kind": "proposed_source", "item": p})
            continue
        proposed.append({
            "id": p["id"], "name": p["name"][:120], "kid": p["kid"], "category": p["category"],
            "url": p["url"], "scan_method": p["scan_method"], "why": str(p.get("why", ""))[:300],
            "eligibility_note": str(p.get("eligibility_note", ""))[:300], "replaces_source_id": None,
            "found": today.isoformat(), "confidence": p.get("confidence", "estimated"), "state": "pending",
        })
        prop_ids.add(p["id"]); prop_urls.add(p["url"]); added_prop += 1

    # One-off events → events.json (discovery kind, unverified)
    for e in (out.get("one_off_events") or []):
        if not isinstance(e, dict) or e.get("kid") not in KID or not ISO.match(str(e.get("date", ""))):
            quarantined.append({"kind": "one_off_event", "item": e})
            continue
        if e["date"] < today.isoformat():
            continue
        key = event_key(e["kid"], e["date"], e["title"])
        if key in event_keys:
            continue
        stamp = today.strftime("%Y%m%d")
        n = 1
        while f"evt-disc-{stamp}-{n:03d}" in event_ids:
            n += 1
        eid = f"evt-disc-{stamp}-{n:03d}"
        event_ids.add(eid); event_keys.add(key)
        url = e.get("url") if str(e.get("url", "")).startswith("http") else None
        events.append({
            "id": eid, "dedupe_key": key, "kid": e["kid"],
            "title": f"{e['title']} ({e.get('org','')})".strip().rstrip("()").strip(),
            "date": e["date"], "end_date": None, "time": None, "type": "community",
            "action": None,
            "source": {"kind": "discovery", "ref": url or "web", "first_seen": today.isoformat(),
                       "unverified": True, "why": str(e.get("why", ""))[:300]},
            "status": "active",
        })
        added_evt += 1

    summary_notes = [str(n)[:300] for n in (out.get("digest_notes") or [])[:5] if isinstance(n, str)]

    if args.dry_run:
        print(json.dumps({"proposed_added": added_prop, "events_added": added_evt,
                          "quarantined": len(quarantined), "notes": summary_notes}, indent=2))
        return 0

    proposed_doc["proposals"] = proposed
    write_json(os.path.join(DATA, "sources_proposed.json"), proposed_doc)
    write_json(os.path.join(DATA, "events.json"), events_doc)
    if quarantined:
        q = read_json(os.path.join(LOCAL, "quarantine.json"), {"items": []})
        now = datetime.datetime.now().isoformat(timespec="seconds")
        q["items"].extend({"at": now, **item} for item in quarantined)
        write_json(os.path.join(LOCAL, "quarantine.json"), q)
    # Merge discovery notes into the digest summary (so they show Sunday).
    ms = read_json(os.path.join(LOCAL, "merge_summary.json"), {"date": today.isoformat(), "digest_notes": []})
    if ms.get("date") != today.isoformat():
        ms = {"date": today.isoformat(), "digest_notes": [], "new_events": [], "new_opportunities": [],
              "updated_events": [], "watchlist_updates": [], "other_items": [], "reseen": 0, "quarantined": 0}
    ms["digest_notes"] = (ms.get("digest_notes", []) + summary_notes)[:8]
    write_json(os.path.join(LOCAL, "merge_summary.json"), ms)

    log(f"merge_discovery: +{added_prop} proposed, +{added_evt} one-off events, {len(quarantined)} quarantined")
    return 0


if __name__ == "__main__":
    sys.exit(main())
