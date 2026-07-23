#!/usr/bin/env python3
"""Assemble data/local/discovery_input.json for the weekly discovery LLM call.

Deliberately isolated: NO email content, only kid profiles, a summary of the
current registry (so it doesn't re-propose what we already scan), the watchlist,
and the list of dead-URL sources to relocate.
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


def main():
    sources = read_json(os.path.join(DATA, "sources.json"))["sources"]
    watch = read_json(os.path.join(DATA, "watchlist.json"))["watchlist"]
    proposed = read_json(os.path.join(DATA, "sources_proposed.json"), {"proposals": []})["proposals"]

    dead = [{"source_id": s["id"], "name": s["name"], "old_url": s["url"]}
            for s in sources if s["scan"].get("consecutive_failures", 0) >= 1]

    bundle = {
        "today": datetime.date.today().isoformat(),
        "kids": {
            "ridhi": "10th grade, California High School, San Ramon 94582, age 15; bio/medicine/genetics volunteering + teen science programs",
            "dhruv": "6th grade, Pine Valley Middle School, San Ramon, age 11; badminton, speech & debate, finance/business clubs, STEM",
        },
        "already_covered": [{"name": s["name"], "url": s["url"], "category": s["category"], "kid": s["kid"]} for s in sources],
        "already_proposed": [{"id": p["id"], "name": p["name"]} for p in proposed],
        "dead_urls_to_relocate": dead,
        "watchlist": [{"title": w["title"], "expected_open": w.get("expected_open")} for w in watch],
    }
    write_json(os.path.join(LOCAL, "discovery_input.json"), bundle)
    log(f"build_discovery: {len(dead)} dead url(s), {len(sources)} covered, {len(proposed)} already proposed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
