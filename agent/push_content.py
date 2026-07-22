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


def pull(cfg):
    remote = call(cfg, "/api/pipeline")
    statuses = remote.get("statuses", {})
    if not statuses:
        log("push_content: pull — no dashboard statuses")
        return 0
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
    log(f"push_content: pull — {changed} status change(s) folded in")
    return 0


def push(cfg):
    events = read_json(os.path.join(DATA, "events.json"), {"events": []})["events"]
    opps = read_json(os.path.join(DATA, "opportunities.json"), {"opportunities": []})["opportunities"]
    watch = read_json(os.path.join(DATA, "watchlist.json"), {"watchlist": []})["watchlist"]
    last_run = read_json(os.path.join(DATA, "state", "last_run.json"), {})

    content = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "run_id": last_run.get("run_id"),
        "events": [e for e in events if e["status"] != "expired"],
        "opportunities": opps,
        "watchlist": watch,
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
        print("usage: push_content.py --pull | --push")
        return 2
    except (urllib.error.URLError, OSError, KeyError) as e:
        log(f"push_content: FAIL {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
