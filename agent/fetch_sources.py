#!/usr/bin/env python3
"""Fetch registry sources, extract text, sha256-diff against last seen content.

Candidate-state discipline: never touches data/sources.json. Per-source scan-state
updates (hash/etag/next_check/failures) go to data/local/sources_updates.candidate.json;
merge_results.py applies them only after a successful merge.

Outputs:
  data/local/changed_sources.json              — changed sources w/ new-lines excerpts (bundle input)
  data/local/sources_updates.candidate.json    — scan-state updates awaiting promotion
  data/snapshots/sources/<id>/{latest,previous}.txt

First fetch of a source = BASELINE (records hash, not reported as changed).
Anomaly guard: previously-rich page (>2000 chars) shrinking below 500 chars is a
fetch anomaly (JS shell / outage), never a "change".

Usage: fetch_sources.py [--selftest]
"""
import datetime
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomicio import read_json, write_json, write_text
from lib.runlog import log

REPO = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"
SOURCES = os.path.join(REPO, "data", "sources.json")
CHANGED = os.path.join(REPO, "data", "local", "changed_sources.json")
CANDIDATE = os.path.join(REPO, "data", "local", "sources_updates.candidate.json")
SNAP_DIR = os.path.join(REPO, "data", "snapshots", "sources")

USER_AGENT = "SanRamonFamilyDigest/1.0 (personal family tool)"
TIMEOUT = 20
POLITE_DELAY_S = 2
ANOMALY_PREV_MIN = 2000
ANOMALY_NEW_MAX = 500
EXCERPT_CAP = 8000
NEW_LINES_CAP = 60

TAG_RE = re.compile(r"<[^>]+>")
STYLE_SCRIPT_RE = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.IGNORECASE | re.DOTALL)


def extract_text(raw: bytes, content_type: str) -> str:
    if "pdf" in content_type:
        return ""  # PDFs are hashed on raw bytes; no text extract in v1
    try:
        html = raw.decode("utf-8", "replace")
    except Exception:
        return ""
    text = STYLE_SCRIPT_RE.sub(" ", html)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>|</h[1-6]>", "\n", text, flags=re.IGNORECASE)
    text = TAG_RE.sub(" ", text)
    for ent, ch in (("&nbsp;", " "), ("&amp;", "&"), ("&#39;", "'"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"')):
        text = text.replace(ent, ch)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def sha256(text_or_bytes) -> str:
    data = text_or_bytes if isinstance(text_or_bytes, bytes) else text_or_bytes.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def new_lines_excerpt(previous: str, latest: str) -> str:
    """Order-preserving lines present in latest but not previous — the change signal."""
    prev_set = set(previous.splitlines())
    fresh = [ln for ln in latest.splitlines() if ln not in prev_set]
    return "\n".join(fresh[:NEW_LINES_CAP])


def is_due(source, today: datetime.date) -> bool:
    scan = source["scan"]
    if source["status"] not in ("active", "watch"):
        return False
    if scan["method"] in ("manual", "ical"):
        return False  # manual = runbook; ical = activated later
    nxt = scan.get("next_check_date")
    return nxt is None or datetime.date.fromisoformat(nxt) <= today


def next_check(source, today: datetime.date) -> str:
    freq = source["scan"]["frequency"]
    failures = source["scan"].get("consecutive_failures", 0)
    if failures >= 5 or freq == "weekly":
        return (today + datetime.timedelta(days=7)).isoformat()
    return (today + datetime.timedelta(days=1)).isoformat()


def fetch(source):
    scan = source["scan"]
    req = urllib.request.Request(source["url"], headers={"User-Agent": USER_AGENT})
    if scan.get("etag"):
        req.add_header("If-None-Match", scan["etag"])
    if scan.get("last_modified"):
        req.add_header("If-Modified-Since", scan["last_modified"])
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return {
                "status": resp.status,
                "body": resp.read(2_000_000),
                "content_type": resp.headers.get("Content-Type", ""),
                "etag": resp.headers.get("ETag"),
                "last_modified": resp.headers.get("Last-Modified"),
            }
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return {"status": 304}
        raise


def process_source(source, today):
    """Returns (update_dict, changed_entry_or_None)."""
    sid = source["id"]
    scan = source["scan"]
    update = {
        "last_checked": today.isoformat(),
        "consecutive_failures": scan.get("consecutive_failures", 0),
        "next_check_date": None,  # filled at end
        "last_hash": scan.get("last_hash"),
        "etag": scan.get("etag"),
        "last_modified": scan.get("last_modified"),
    }
    changed_entry = None
    snap = os.path.join(SNAP_DIR, sid)
    latest_path = os.path.join(snap, "latest.txt")

    try:
        resp = fetch(source)
        if resp["status"] == 304:
            update["consecutive_failures"] = 0
            log(f"fetch_sources: {sid} 304 not-modified")
        else:
            is_pdf = "pdf" in (resp.get("content_type") or "") or scan.get("params", {}).get("content_type") == "pdf"
            text = extract_text(resp["body"], resp.get("content_type") or "")
            new_hash = sha256(resp["body"] if is_pdf else text)
            previous_text = ""
            if os.path.exists(latest_path):
                with open(latest_path) as f:
                    previous_text = f.read()

            if not is_pdf and len(previous_text) > ANOMALY_PREV_MIN and len(text) < ANOMALY_NEW_MAX:
                update["consecutive_failures"] += 1
                log(f"fetch_sources: {sid} ANOMALY (rich page shrank {len(previous_text)}->{len(text)} chars) — not a change")
            elif scan.get("last_hash") is None:
                # Snapshot is STAGED (latest.candidate.txt) — merge_results promotes it
                # together with the hash, so a failed merge re-detects the same content.
                update.update(last_hash=new_hash, etag=resp.get("etag"), last_modified=resp.get("last_modified"), consecutive_failures=0)
                if not is_pdf:
                    write_text(os.path.join(snap, "latest.candidate.txt"), text)
                log(f"fetch_sources: {sid} BASELINE recorded ({len(text)} chars)")
            elif new_hash != scan["last_hash"]:
                if is_pdf:
                    excerpt = "(PDF content changed — review at URL)"
                else:
                    excerpt = new_lines_excerpt(previous_text, text)[:EXCERPT_CAP]
                    if not excerpt:
                        excerpt = "(content changed but no new lines — likely removals or reordering; see context head)"
                changed_entry = {
                    "source_id": sid,
                    "name": source["name"],
                    "url": source["url"],
                    "kid": source["kid"],
                    "category": source["category"],
                    "region_hint": scan.get("region_hint", ""),
                    "new_lines": excerpt,
                    "context_head": ("" if is_pdf else text[:1000]),
                }
                if not is_pdf:
                    write_text(os.path.join(snap, "latest.candidate.txt"), text)
                update.update(last_hash=new_hash, etag=resp.get("etag"), last_modified=resp.get("last_modified"), consecutive_failures=0)
                log(f"fetch_sources: {sid} CHANGED")
            else:
                update.update(etag=resp.get("etag"), last_modified=resp.get("last_modified"), consecutive_failures=0)
                log(f"fetch_sources: {sid} unchanged")
    except Exception as e:
        update["consecutive_failures"] += 1
        log(f"fetch_sources: {sid} FAIL ({type(e).__name__}: {e}) failures={update['consecutive_failures']}")

    update["next_check_date"] = next_check({"scan": {**scan, "consecutive_failures": update["consecutive_failures"]}}, today)
    return update, changed_entry


def selftest() -> int:
    """Fixture-driven assertions for the diff detector. Known-BAD cases must behave."""
    fx = os.path.join(REPO, "agent", "tests", "fixtures")

    def load_extract(name):
        with open(os.path.join(fx, name), "rb") as f:
            return extract_text(f.read(), "text/html")

    a = load_extract("redcross_a.html")
    b = load_extract("redcross_b_new_listing.html")
    ws = load_extract("redcross_a_whitespace_only.html")
    shell = load_extract("redcross_shell_anomaly.html")

    failures = []
    if sha256(a) == sha256(b):
        failures.append("known-BAD: new listing NOT detected as change")
    if sha256(a) != sha256(ws):
        failures.append("known-BAD: whitespace-only reformat wrongly detected as change")
    if not (len(a) > ANOMALY_PREV_MIN and len(shell) < ANOMALY_NEW_MAX):
        failures.append(f"anomaly fixture out of bounds (prev={len(a)}, shell={len(shell)})")
    excerpt = new_lines_excerpt(a, b)
    if "Blood Drive Ambassador" not in excerpt:
        failures.append("new-lines excerpt missing the added listing")

    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}")
        return 1
    print("SELFTEST OK: change detected, whitespace ignored, anomaly bounds correct, excerpt has new listing")
    return 0


def main():
    if "--selftest" in sys.argv:
        return selftest()

    today = datetime.date.today()
    doc = read_json(SOURCES)
    updates, changed = {}, []
    due = [s for s in doc["sources"] if is_due(s, today)]
    log(f"fetch_sources: {len(due)}/{len(doc['sources'])} source(s) due")
    for i, source in enumerate(due):
        if i:
            time.sleep(POLITE_DELAY_S)
        update, entry = process_source(source, today)
        updates[source["id"]] = update
        if entry:
            changed.append(entry)

    # Order matters (crash-window safety): the changed-list must exist BEFORE the
    # candidate hashes, so a crash between the writes can never pair new hashes
    # with a stale change list. merge_results also cross-checks the dates.
    write_json(CHANGED, {"date": today.isoformat(), "changed": changed})
    write_json(CANDIDATE, {"date": today.isoformat(), "updates": updates})
    log(f"fetch_sources: done — {len(changed)} changed, {sum(1 for u in updates.values() if u['consecutive_failures'])} failing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
