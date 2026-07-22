#!/usr/bin/env python3
"""Assemble data/local/scan_input.json — the single data payload for the daily LLM call.

Adaptive budgets keep the bundle under caps even on the 180-day backfill run.
Exit codes: 0 = bundle written; 3 = QUIET (no new email, no changed sources) — scan.sh
skips the LLM+merge steps and sends a quiet digest.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomicio import read_json, write_json
from lib.runlog import log

REPO = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"
DATA = os.path.join(REPO, "data")
LOCAL = os.path.join(DATA, "local")


def summarize_state():
    events = read_json(os.path.join(DATA, "events.json"), {"events": []})["events"]
    opps = read_json(os.path.join(DATA, "opportunities.json"), {"opportunities": []})["opportunities"]
    watch = read_json(os.path.join(DATA, "watchlist.json"), {"watchlist": []})["watchlist"]
    return {
        "existing_events": [
            {"id": e["id"], "dedupe_key": e["dedupe_key"], "date": e["date"], "title": e["title"], "status": e["status"]}
            for e in events if e["status"] == "active"
        ],
        "existing_opportunities": [
            {"id": o["id"], "dedupe_key": o["dedupe_key"], "org": o["org"], "title": o["title"], "status": o["pipeline"]["status"]}
            for o in opps
        ],
        "watchlist": [
            {"id": w["id"], "title": w["title"], "expected_open": w.get("expected_open"), "state": w["state"]}
            for w in watch
        ],
    }


def budget_emails(messages, char_budget):
    """Trim message bodies to fit the shared budget; subjects/senders always survive."""
    if not messages:
        return []
    per_msg = max(600, min(8000, char_budget // len(messages)))
    out = []
    for m in messages:
        out.append({
            "message_id": m["message_id"],
            "date": m["date"],
            "from": m["from"],
            "subject": m["subject"],
            "body": m["body"][:per_msg],
            "ics": m.get("ics", []),
        })
    return out


def main():
    with open(os.path.join(REPO, "agent", "config.json")) as f:
        cfg = json.load(f)
    bundle_cap = cfg["caps"]["bundle_chars"]

    new_email = read_json(os.path.join(LOCAL, "new_email.json"), {"messages": []})
    changed = read_json(os.path.join(LOCAL, "changed_sources.json"), {"changed": []})
    messages = new_email.get("messages", [])
    changed_sources = changed.get("changed", [])

    if not messages and not changed_sources:
        log("build_bundle: QUIET — nothing new to classify")
        return 3

    # Budget split: emails get the lion's share when both streams are present.
    email_budget = int(bundle_cap * (0.7 if changed_sources else 0.95))
    source_budget = bundle_cap - email_budget if changed_sources else 0
    per_source = max(1500, source_budget // len(changed_sources)) if changed_sources else 0

    bundle = {
        "today": datetime.date.today().isoformat(),
        "emails": budget_emails(messages, email_budget),
        "changed_sources": [
            {
                "source_id": c["source_id"],
                "name": c["name"],
                "url": c["url"],
                "kid": c["kid"],
                "category": c["category"],
                "region_hint": c["region_hint"],
                "new_lines": c["new_lines"][:per_source],
                "context_head": c["context_head"][:1000],
            }
            for c in changed_sources
        ],
        "current_state": summarize_state(),
    }
    write_json(os.path.join(LOCAL, "scan_input.json"), bundle)
    log(f"build_bundle: {len(messages)} email(s), {len(changed_sources)} changed source(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
