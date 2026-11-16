#!/usr/bin/env python3
"""Build the roadmap content document and PUT it to the dashboard (/api/roadmap).

Reads roadmap/data/*.json plus data/summer_apps.json (READ ONLY: that file belongs to
the school digest and is hand-maintained). Writes no files at all. Every run publishes:
there is deliberately no "unchanged, skip" shortcut, because a local record of the last
push cannot know what the dashboard actually holds.

  --dry-run          validate + build, print a summary, no network
  --base-url URL     override the dashboard address (local dev: http://localhost:8799)
  --data-dir DIR     override roadmap/data (tests)

Auth: x-sync-key from Keychain item school-intel-family-code, or the ROADMAP_SYNC_KEY
environment variable when set (local dev only).
Exit codes: 0 ok · 1 network/auth failure · 2 data failed validation (nothing sent).
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

ROADMAP = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROADMAP)
sys.path.insert(0, ROADMAP)
sys.path.insert(0, os.path.join(REPO, "agent"))

import validate as roadmap_validate  # noqa: E402

DATA = os.path.join(ROADMAP, "data")
APPS_FILE = os.path.join(REPO, "data", "summer_apps.json")
CONFIG = os.path.join(REPO, "agent", "config.json")
MAX_CONTENT_BYTES = 400_000  # the API refuses anything larger; KV's own limit is far higher

# Only these fields of an application travel to the page. A hand-edited extra field
# (a contact address, say) stays on the Mac.
APP_FIELDS = ("id", "title", "org", "track", "deadline", "until", "approx", "verify", "window", "action", "note")


def _read(path):
    with open(path) as f:
        return json.load(f)


def load_applications(apps_file):
    """-> (rows, synced, note). Never raises: a slip in the hand-edited file must not
    stop the rest of the roadmap from publishing."""
    try:
        doc = _read(apps_file)
        apps = doc.get("applications")
        if not isinstance(apps, list):
            return [], None, "applications list could not be read"
    except (OSError, ValueError, AttributeError):
        return [], None, "applications list could not be read"
    rows = []
    for a in apps:
        if not isinstance(a, dict) or not isinstance(a.get("id"), str) or not isinstance(a.get("title"), str):
            continue
        rows.append({k: a[k] for k in APP_FIELDS if k in a})
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    synced = source.get("synced") if isinstance(source.get("synced"), str) else None
    return rows, synced, None


def build_content(data_dir=DATA, apps_file=APPS_FILE):
    start = _read(os.path.join(data_dir, "start.json"))
    apps, synced, note = load_applications(apps_file)
    content = {
        "version": 1,
        "generated": datetime.date.today().isoformat(),
        "start": {"decided_on": start.get("decided_on"),
                  **{k: start.get(k, []) for k in ("assumptions", "decisions", "flags")}},
        "applications": apps,
        "applications_synced": synced,
        "courses": _read(os.path.join(data_dir, "courses.json")),
        "summers": _read(os.path.join(data_dir, "summers.json")),
        "milestones": _read(os.path.join(data_dir, "milestones.json")).get("milestones", []),
        "sources": _read(os.path.join(data_dir, "source_docs.json")).get("sources", []),
        "money": _read(os.path.join(data_dir, "money.json")),
        "options": _read(os.path.join(data_dir, "options.json")),
        "status": _read(os.path.join(data_dir, "status.json")),
        "community": _read(os.path.join(data_dir, "community.json")),
    }
    if note:
        content["applications_note"] = note
    return content


def _sync_key():
    env = os.environ.get("ROADMAP_SYNC_KEY")
    if env:
        return env
    from lib.keychain import get_secret
    return get_secret(_read(CONFIG)["keychain"]["family_code"])


def _put(base_url, body):
    # Cloudflare's bot filter 403s the default Python-urllib UA — send a real one.
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/roadmap", method="PUT", data=json.dumps(body).encode(),
        headers={"x-sync-key": _sync_key(), "Content-Type": "application/json",
                 "User-Agent": "SchoolCompassAgent/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--base-url")
    ap.add_argument("--data-dir", default=DATA)
    args = ap.parse_args(argv)

    errors = roadmap_validate.validate(args.data_dir)
    if errors:
        for e in errors:
            print(e)
        print(f"push: REFUSED — {len(errors)} validation problem(s), nothing sent")
        return 2

    content = build_content(args.data_dir)
    size = len(json.dumps(content))
    if size > MAX_CONTENT_BYTES:
        print(f"push: REFUSED — content is {size} bytes (limit {MAX_CONTENT_BYTES})")
        return 2
    summary = (f"{len(content['applications'])} applications, {len(content['milestones'])} milestones, "
               f"{len(content['start']['decisions'])} decisions, {len(content['summers'].get('options', []))} "
               f"summer options, {len(content['money'].get('awards', []))} awards, {len(content['options'].get('routes', []))} routes, "
               f"{len(content['status'].get('questions', []))} questions, {len(content['community'].get('patterns', []))} family notes, "
               f"{len(content['sources'])} sources, {size} bytes")
    if args.dry_run:
        print("push: DRY RUN — " + summary)
        return 0

    base = args.base_url or _read(CONFIG)["kv_api"]["base_url"]
    try:
        result = _put(base, {"content": content})
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        print(f"push: FAILED — {type(e).__name__}: {e}")
        return 1
    if not (isinstance(result, dict) and result.get("ok")):
        print(f"push: FAILED — unexpected reply {result!r}")
        return 1
    print(f"push: OK → {base} — " + summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
