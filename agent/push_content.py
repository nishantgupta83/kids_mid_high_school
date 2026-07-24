#!/usr/bin/env python3
"""Bridge between local state and the dashboard's KV (via the authed Pages API).

--pull: fetch dashboard status changes (opp:<id> keys) and fold them into
        opportunities.json. Runs as scan step 3, BEFORE merge — the only other
        writer (merge_results) runs after, so single-writer-at-a-time holds.
        Ownership rule: dashboard owns pipeline.status; a KV record newer than
        the local updated_at wins.
--push: PUT health ALWAYS + the content doc only when it changed since the last
        push (hash tracked in data/local/last_push_hash).

Auth: x-sync-key from Keychain item school-intel-family-code.
Exit codes: 0 ok, 1 network/auth failure (scan.sh treats as WARN, never fatal).
"""
import datetime
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomicio import read_json, write_json, write_text
from lib.keychain import get_secret
from lib.runlog import log

REPO = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"
DATA = os.path.join(REPO, "data")
LOCAL = os.path.join(DATA, "local")


def call(cfg, path, method="GET", body=None):
    base = cfg["kv_api"]["base_url"].rstrip("/")
    code = get_secret(cfg["keychain"]["family_code"])
    # Cloudflare's bot filter 403s the default Python-urllib UA — send a real one.
    req = urllib.request.Request(base + path, method=method,
                                 headers={"x-sync-key": code, "Content-Type": "application/json",
                                          "User-Agent": "SchoolCompassAgent/1.0"})
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=30) as resp:
        return json.loads(resp.read())


def promote_proposal(p, sources, today):
    """Approve a proposed source: swap a dead source's URL, or add a new source."""
    if p.get("replaces_source_id"):
        for s in sources:
            if s["id"] == p["replaces_source_id"]:
                s["url"] = p["url"]
                s["scan"].update({"last_hash": None, "etag": None, "last_modified": None,
                                  "consecutive_failures": 0, "next_check_date": today.isoformat()})
                s["status"] = "active"
                s.setdefault("provenance", {})["relocated"] = today.isoformat()
                return True
        return False
    if any(s["id"] == p["id"] or s["url"] == p["url"] for s in sources):
        return False
    sources.append({
        "id": p["id"], "name": p["name"], "kid": p["kid"], "category": p["category"], "url": p["url"],
        "scan": {"method": p["scan_method"], "params": {}, "region_hint": "", "frequency": "weekly",
                 "next_check_date": today.isoformat(), "last_checked": None, "last_hash": None,
                 "etag": None, "last_modified": None, "consecutive_failures": 0},
        "eligibility": {"age_min": None, "age_max": None, "grade_min": None, "grade_max": None,
                        "gpa_min": None, "notes": p.get("eligibility_note", "")},
        "application_window": {"opens": None, "closes": None, "recurrence": "rolling", "confidence": "estimated"},
        "priority": 2, "status": "active",
        "provenance": {"added": today.isoformat(), "verified": None, "note": "approved from weekly discovery proposal"},
        "notes": p.get("why", ""),
    })
    return True


def apply_proposal_decisions(cfg):
    """Read approve/dismiss decisions from KV and act on pending proposals."""
    remote = call(cfg, "/api/pipeline")
    decisions = remote.get("proposals", {})  # {propId: {decision}}
    if not decisions:
        return 0
    today = datetime.date.today()
    prop_doc = read_json(os.path.join(DATA, "sources_proposed.json"), {"proposals": []})
    sources_doc = read_json(os.path.join(DATA, "sources.json"))
    remaining, handled = [], 0
    for p in prop_doc["proposals"]:
        dec = decisions.get(p["id"], {})
        d = dec.get("decision")
        # Instance-scope: a decision only applies to the exact proposal it was made on.
        # A stale KV key from an earlier same-id proposal (different found date) is ignored,
        # so a regenerated proposal always needs fresh approval — closes the auto-promote gap.
        # Require a truthy found on BOTH sides so an empty/missing value can never match.
        if (p.get("state", "pending") != "pending" or not d
                or not p.get("found") or not dec.get("found") or dec.get("found") != p.get("found")):
            remaining.append(p)
            continue
        if d == "approve" and promote_proposal(p, sources_doc["sources"], today):
            handled += 1
            log(f"push_content: promoted proposal {p['id']}")
        elif d == "dismiss":
            handled += 1
            log(f"push_content: dismissed proposal {p['id']}")
        else:
            remaining.append(p)  # approve that couldn't resolve → keep for next time
    if handled:
        prop_doc["proposals"] = remaining
        write_json(os.path.join(DATA, "sources.json"), sources_doc)
        write_json(os.path.join(DATA, "sources_proposed.json"), prop_doc)
    return handled


def pull(cfg):
    remote = call(cfg, "/api/pipeline")
    statuses = remote.get("statuses", {})
    doc = read_json(os.path.join(DATA, "opportunities.json"))
    changed = 0
    for o in doc["opportunities"]:
        kv = statuses.get(o["id"])
        if not kv:
            continue
        local = o["pipeline"]
        if kv["status"] != local["status"] and kv.get("updated_at", "") > local.get("updated_at", ""):
            local["status"] = kv["status"]
            local["updated_at"] = kv["updated_at"]
            local["updated_by"] = "dashboard"
            local.setdefault("history", []).append({"status": kv["status"], "at": kv["updated_at"]})
            changed += 1
    if changed:
        write_json(os.path.join(DATA, "opportunities.json"), doc)
    promoted = apply_proposal_decisions(cfg)
    log(f"push_content: pull — {changed} status change(s), {promoted} proposal decision(s) applied")
    return 0


def push(cfg):
    events = read_json(os.path.join(DATA, "events.json"), {"events": []})["events"]
    opps = read_json(os.path.join(DATA, "opportunities.json"), {"opportunities": []})["opportunities"]
    watch = read_json(os.path.join(DATA, "watchlist.json"), {"watchlist": []})["watchlist"]
    proposed = [p for p in read_json(os.path.join(DATA, "sources_proposed.json"), {"proposals": []})["proposals"]
                if p.get("state", "pending") == "pending"]
    last_run = read_json(os.path.join(DATA, "state", "last_run.json"), {})
    today = datetime.date.today().isoformat()
    ms = read_json(os.path.join(LOCAL, "merge_summary.json"), {})
    other = ms.get("other_items", []) if ms.get("date") == today else []

    content = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "run_id": last_run.get("run_id"),
        "events": [e for e in events if e["status"] != "expired"],
        "opportunities": opps,
        "watchlist": watch,
        "proposed_sources": [{"id": p["id"], "name": p["name"], "kid": p["kid"], "why": p.get("why", ""),
                              "url": p["url"], "category": p["category"], "found": p.get("found", "")} for p in proposed],
        "other_items": other,
    }
    # Hash excludes generated_at so quiet days don't push identical content.
    hashable = json.dumps({k: v for k, v in content.items() if k != "generated_at"}, sort_keys=True)
    digest = hashlib.sha256(hashable.encode()).hexdigest()
    hash_path = os.path.join(LOCAL, "last_push_hash")
    prev = open(hash_path).read().strip() if os.path.exists(hash_path) else ""

    new_email = read_json(os.path.join(LOCAL, "new_email.json"), {"messages": []})
    changed_doc = read_json(os.path.join(LOCAL, "changed_sources.json"), {"changed": []})
    cand = read_json(os.path.join(LOCAL, "sources_updates.candidate.json"), {"updates": {}})
    # Preserve the previous success timestamp across failed runs so staleness is
    # measured from the last real success, never masked by a fresh failed attempt.
    success_path = os.path.join(LOCAL, "last_success_at")
    if last_run.get("ok") and last_run.get("at"):
        write_text(success_path, last_run["at"])
    last_success = open(success_path).read().strip() if os.path.exists(success_path) else None
    health = {
        "last_attempt_at": last_run.get("at"),
        "last_success_at": last_success,
        "run_id": last_run.get("run_id"),
        "mode": last_run.get("mode"),
        "emails_scanned": len(new_email.get("messages", [])),
        "sources_changed": len(changed_doc.get("changed", [])),
        "sources_failing": [sid for sid, u in cand.get("updates", {}).items()
                            if u.get("consecutive_failures", 0) > 0],
    }

    body = {"health": health}
    if digest != prev:
        body["content"] = content
    result = call(cfg, "/api/data", method="PUT", body=body)
    if "content" in body:
        write_text(hash_path, digest)
    log(f"push_content: push — wrote {result.get('wrote')} key(s)"
        + (" (content updated)" if "content" in body else " (health only)"))
    return 0


def kidstatus(cfg):
    """Fetch Dhruv's homework done-count + streak for today, for the digest."""
    today = datetime.date.today().isoformat()
    events = read_json(os.path.join(DATA, "events.json"), {"events": []})["events"]
    hw = [e for e in events if e.get("type") == "homework" and e.get("kid") in ("dhruv", "both")
          and e.get("date") == today and e.get("status") == "active"]
    if not hw:
        return 0
    try:
        k = call(cfg, f"/api/kid?date={today}")
    except Exception as e:
        log(f"push_content: kidstatus fetch failed {e}")
        return 0
    done = sum(1 for e in hw if (k.get("homework", {}).get(e["id"], {}) or {}).get("status") == "done")
    write_json(os.path.join(LOCAL, "kid_status.json"),
               {"date": today, "done": done, "total": len(hw), "streak": (k.get("streak") or {}).get("count", 0)})
    log(f"push_content: kidstatus — Dhruv {done}/{len(hw)} done")
    return 0


def main():
    with open(os.path.join(REPO, "agent", "config.json")) as f:
        cfg = json.load(f)
    if not cfg["kv_api"]["base_url"]:
        log("push_content: no base_url configured — skipping")
        return 0
    try:
        if "--pull" in sys.argv:
            return pull(cfg)
        if "--push" in sys.argv:
            return push(cfg)
        if "--kidstatus" in sys.argv:
            return kidstatus(cfg)
        print("usage: push_content.py --pull | --push | --kidstatus")
        return 2
    except (urllib.error.URLError, OSError, KeyError) as e:
        log(f"push_content: FAIL {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
