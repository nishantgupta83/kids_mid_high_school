#!/usr/bin/env python3
"""Merge LLM proposals into state. THE single writer of data/*.json.

Guarantees:
- LLM output is proposals only; dedupe keys are recomputed here, never trusted.
- Per-item validation: bad items → data/local/quarantine.json (gitignored); good items merge.
- Non-dict / unparseable envelope → exit 1, NOTHING written, cursors untouched.
- Transactional checkpoints: email cursor + per-source scan-state candidates are
  promoted ONLY here — full success promotes all; --finalize-only (quiet/degraded)
  promotes only sources whose changes were NOT awaiting classification, and the
  email cursor only when there were no unprocessed messages.

Usage:
  merge_results.py --llm-output <path> [--dry-run]
  merge_results.py --finalize-only
"""
import argparse
import datetime
import difflib
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomicio import read_json, write_json
from lib.runlog import log

REPO = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"
DATA = os.path.join(REPO, "data")
LOCAL = os.path.join(DATA, "local")

KID = {"ridhi", "dhruv", "both", "family"}
OPP_KID = {"ridhi", "dhruv", "both"}
EVENT_TYPE = {"school", "deadline", "break", "test", "athletics", "community", "homework"}
OPP_CATEGORY = {"volunteer-bio", "volunteer-general", "program", "club", "event"}
OPP_REGION = {"tri-valley", "bay-area", "virtual"}
WATCH_STATE = {"waiting", "window_open", "converted", "missed"}
EVENT_UPDATE_FIELDS = {"date", "end_date", "time", "title", "status"}
EVENT_STATUS = {"active", "done", "expired"}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ELIGIBLE = re.compile(r"^(yes|no|check|from:\d{4}-\d{2}-\d{2})$")
FUZZY_THRESHOLD = 0.8


def slug(s: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:max_len].rstrip("-")


def cycle_year(today: datetime.date) -> int:
    """Academic-year anchor: Jul-Dec → this year; Jan-Jun → previous year."""
    return today.year if today.month >= 7 else today.year - 1


def opp_key(org: str, title: str, today: datetime.date) -> str:
    return f"{slug(org)}|{slug(title)}|{cycle_year(today)}"


def event_key(kid: str, date: str, title: str) -> str:
    return f"{kid}|{date}|{slug(title, 60)}"


def is_date(v, allow_null=True):
    if v is None:
        return allow_null
    return isinstance(v, str) and bool(ISO.match(v))


def validate_event(e) -> list:
    errs = []
    if not isinstance(e, dict):
        return ["not an object"]
    if e.get("kid") not in KID:
        errs.append(f"bad kid {e.get('kid')!r}")
    if not isinstance(e.get("title"), str) or not (3 <= len(e["title"]) <= 200):
        errs.append("bad title")
    if not is_date(e.get("date"), allow_null=False):
        errs.append("bad date")
    if not is_date(e.get("end_date")):
        errs.append("bad end_date")
    if e.get("type") not in EVENT_TYPE:
        errs.append(f"bad type {e.get('type')!r}")
    action = e.get("action")
    if action is not None:
        if not isinstance(action, dict) or not action.get("what"):
            errs.append("bad action")
        elif not is_date(action.get("due")):
            errs.append("bad action.due")
    return errs


def validate_opp(o, source_ids) -> list:
    errs = []
    if not isinstance(o, dict):
        return ["not an object"]
    if o.get("kid") not in OPP_KID:
        errs.append(f"bad kid {o.get('kid')!r}")
    for field in ("title", "org", "evidence"):
        if not isinstance(o.get(field), str) or len(o.get(field) or "") < 2:
            errs.append(f"missing/bad {field}")
    # Email-discovered opportunities often have no link — null is allowed.
    if o.get("url") is not None and not str(o.get("url", "")).startswith("http"):
        errs.append("bad url")
    if o.get("category") not in OPP_CATEGORY:
        errs.append(f"bad category {o.get('category')!r}")
    if o.get("region") not in OPP_REGION:
        errs.append(f"bad region {o.get('region')!r}")
    elig = o.get("eligibility")
    if not isinstance(elig, dict) or not ELIGIBLE.match(str(elig.get("eligible_now", ""))):
        errs.append("bad eligibility")
    win = o.get("window")
    if not isinstance(win, dict) or not all(is_date(win.get(k)) for k in ("opens", "closes", "deadline")):
        errs.append("bad window")
    if o.get("source_id") not in source_ids:
        errs.append(f"unknown source_id {o.get('source_id')!r}")
    return errs


def fuzzy_match(key: str, existing_keys: list):
    base = key.rsplit("|", 1)[0]  # compare org|title, ignore cycle year
    for ek in existing_keys:
        if difflib.SequenceMatcher(None, base, ek.rsplit("|", 1)[0]).ratio() >= FUZZY_THRESHOLD:
            return ek
    return None


def next_id(prefix: str, existing_ids: set, today: datetime.date) -> str:
    stamp = today.strftime("%Y%m%d")
    n = 1
    while f"{prefix}-{stamp}-{n:03d}" in existing_ids:
        n += 1
    return f"{prefix}-{stamp}-{n:03d}"


def promote_snapshot(sid: str):
    """latest.candidate.txt → latest.txt (old latest → previous.txt)."""
    snap = os.path.join(DATA, "snapshots", "sources", sid)
    candidate = os.path.join(snap, "latest.candidate.txt")
    latest = os.path.join(snap, "latest.txt")
    if not os.path.exists(candidate):
        return
    if os.path.exists(latest):
        os.replace(latest, os.path.join(snap, "previous.txt"))
    os.replace(candidate, latest)


def promote_checkpoints(full_success: bool):
    """Advance email cursor + source scan-state. See module docstring for the rules."""
    promoted, withheld = [], []
    today = datetime.date.today().isoformat()

    cand_cursor = read_json(os.path.join(LOCAL, "email_cursor.candidate.json"))
    if cand_cursor:
        new_email = read_json(os.path.join(LOCAL, "new_email.json"), {"messages": []})
        if full_success or not new_email.get("messages"):
            write_json(os.path.join(DATA, "state", "email_cursor.json"), cand_cursor)
            promoted.append("email_cursor")
        else:
            withheld.append("email_cursor (unprocessed messages)")

    cand_sources = read_json(os.path.join(LOCAL, "sources_updates.candidate.json"))
    changed_doc = read_json(os.path.join(LOCAL, "changed_sources.json"), {"changed": []})
    if cand_sources and cand_sources.get("date") != today:
        withheld.append(f"all sources (stale candidate from {cand_sources.get('date')})")
        cand_sources = None
    if cand_sources and changed_doc.get("changed") and changed_doc.get("date") != cand_sources.get("date"):
        withheld.append("all sources (changed-list/candidate date mismatch)")
        cand_sources = None
    if cand_sources:
        changed_ids = {c["source_id"] for c in changed_doc.get("changed", [])}
        sources_doc = read_json(os.path.join(DATA, "sources.json"))
        by_id = {s["id"]: s for s in sources_doc["sources"]}
        for sid, upd in cand_sources.get("updates", {}).items():
            if sid not in by_id:
                continue
            if not full_success and sid in changed_ids:
                withheld.append(f"source:{sid} (change awaits classification)")
                continue
            by_id[sid]["scan"].update({
                "last_checked": upd["last_checked"],
                "last_hash": upd["last_hash"],
                "etag": upd["etag"],
                "last_modified": upd["last_modified"],
                "consecutive_failures": upd["consecutive_failures"],
                "next_check_date": upd["next_check_date"],
            })
            promote_snapshot(sid)
            promoted.append(f"source:{sid}")
        write_json(os.path.join(DATA, "sources.json"), sources_doc)

    log(f"merge: checkpoints promoted={len(promoted)} withheld={len(withheld)}"
        + (f" [{'; '.join(withheld)}]" if withheld else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm-output")
    ap.add_argument("--finalize-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    today = datetime.date.today()

    if args.finalize_only:
        if not args.dry_run:
            promote_checkpoints(full_success=False)
        log("merge: finalize-only complete")
        return 0

    # ---- Full merge ----
    try:
        with open(args.llm_output) as f:
            out = json.load(f)
        if not isinstance(out, dict):
            raise ValueError("envelope is not an object")
    except Exception as e:
        log(f"merge: REJECT envelope ({e}) — nothing written, cursors untouched")
        return 1

    events_doc = read_json(os.path.join(DATA, "events.json"))
    opps_doc = read_json(os.path.join(DATA, "opportunities.json"))
    watch_doc = read_json(os.path.join(DATA, "watchlist.json"))
    sources_doc = read_json(os.path.join(DATA, "sources.json"))
    source_ids = {s["id"] for s in sources_doc["sources"]}

    events = events_doc["events"]
    opps = opps_doc["opportunities"]
    event_keys = {e["dedupe_key"]: e for e in events}
    opp_keys = {o["dedupe_key"]: o for o in opps}
    event_ids = {e["id"] for e in events}
    opp_ids = {o["id"] for o in opps}
    watch_by_id = {w["id"]: w for w in watch_doc["watchlist"]}

    quarantined, summary = [], {
        "date": today.isoformat(), "new_events": [], "new_opportunities": [],
        "updated_events": [], "watchlist_updates": [], "reseen": 0,
        "skipped_past": 0, "digest_notes": [],
    }
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")

    for e in out.get("new_events") or []:
        errs = validate_event(e)
        if errs:
            quarantined.append({"kind": "event", "errors": errs, "item": e})
            continue
        if e["date"] < today.isoformat():
            summary["skipped_past"] += 1
            continue
        key = event_key(e["kid"], e["date"], e["title"])
        if key in event_keys:
            summary["reseen"] += 1
            continue
        eid = next_id("evt", event_ids, today)
        event_ids.add(eid)
        ref = str(e.get("source_ref", ""))
        if ref.startswith("email:"):
            # Never commit raw Message-IDs (they look like addresses and trip the
            # PII lint); a short hash still lets us find the snapshot if needed.
            ref = "email:" + hashlib.sha256(ref.encode()).hexdigest()[:12]
        new_event = {
            "id": eid, "dedupe_key": key, "kid": e["kid"], "title": e["title"],
            "date": e["date"], "end_date": e.get("end_date"), "time": e.get("time"),
            "type": e["type"], "action": e.get("action"),
            "source": {"kind": "email" if ref.startswith("email:") else "registry",
                       "ref": ref[:200], "first_seen": today.isoformat()},
            "status": "active",
        }
        events.append(new_event)
        event_keys[key] = new_event
        summary["new_events"].append(eid)

    for o in out.get("new_opportunities") or []:
        errs = validate_opp(o, source_ids)
        if errs:
            quarantined.append({"kind": "opportunity", "errors": errs, "item": o})
            continue
        key = opp_key(o["org"], o["title"], today)
        hit = opp_keys.get(key)
        if hit is None:
            fk = fuzzy_match(key, list(opp_keys))
            if fk:
                hit = opp_keys[fk]
                log(f"merge: fuzzy-matched {key!r} -> {fk!r}")
        if hit:
            hit["provenance"]["last_seen"] = today.isoformat()
            summary["reseen"] += 1
            continue
        oid = next_id("opp", opp_ids, today)
        opp_ids.add(oid)
        new_opp = {
            "id": oid, "dedupe_key": key, "kid": o["kid"], "title": o["title"],
            "org": o["org"], "url": o["url"], "category": o["category"],
            "region": o["region"], "location": o.get("location", ""),
            "eligibility": {"eligible_now": o["eligibility"]["eligible_now"],
                            "reason": o["eligibility"].get("reason", "")[:300]},
            "window": {"opens": o["window"].get("opens"), "closes": o["window"].get("closes"),
                       "deadline": o["window"].get("deadline"),
                       "confidence": o["window"].get("confidence", "estimated")},
            "commitment": o.get("commitment", ""),
            "pipeline": {"status": "new", "updated_at": now_iso, "updated_by": "agent",
                         "history": [{"status": "new", "at": now_iso}]},
            "provenance": {"source_id": o["source_id"], "first_seen": today.isoformat(),
                           "last_seen": today.isoformat(), "evidence": o.get("evidence", "")[:400]},
            "notes": o.get("notes", "")[:400],
        }
        opps.append(new_opp)
        opp_keys[key] = new_opp
        summary["new_opportunities"].append(oid)

    for u in out.get("updated_events") or []:
        if not isinstance(u, dict) or not isinstance(u.get("changes"), dict):
            quarantined.append({"kind": "event_update", "errors": ["malformed"], "item": u})
            continue
        target = next((e for e in events if e["id"] == u.get("id")), None)
        if target is None:
            quarantined.append({"kind": "event_update", "errors": ["unknown id"], "item": u})
            continue
        changes = {k: v for k, v in u["changes"].items() if k in EVENT_UPDATE_FIELDS}
        if "status" in changes and changes["status"] not in EVENT_STATUS:
            del changes["status"]
        for k in ("date", "end_date"):
            if k in changes and not is_date(changes[k]):
                del changes[k]
        if changes:
            old_key = target["dedupe_key"]
            target.update(changes)
            # Keep the dedupe key true to the (kid, date, title) identity so future
            # re-announcements dedupe against the updated event, not a ghost.
            new_key = event_key(target["kid"], target["date"], target["title"])
            if new_key != old_key and new_key not in event_keys:
                target["dedupe_key"] = new_key
                event_keys.pop(old_key, None)
                event_keys[new_key] = target
            summary["updated_events"].append({"id": target["id"], "changes": changes, "reason": str(u.get("reason", ""))[:200]})

    for w in out.get("watchlist_updates") or []:
        item = watch_by_id.get(w.get("id")) if isinstance(w, dict) else None
        if item is None:
            quarantined.append({"kind": "watchlist_update", "errors": ["unknown id"], "item": w})
            continue
        if w.get("state") in WATCH_STATE:
            item["state"] = w["state"]
        if is_date(w.get("expected_open")) and w.get("expected_open"):
            item["expected_open"] = w["expected_open"]
        item["last_note"] = str(w.get("note", ""))[:300]
        summary["watchlist_updates"].append(w.get("id"))

    # Expire past events (breaks expire after their end date).
    for e in events:
        effective_end = e.get("end_date") or e["date"]
        if e["status"] == "active" and effective_end < today.isoformat():
            e["status"] = "expired"

    summary["digest_notes"] = [str(n)[:300] for n in (out.get("digest_notes") or [])[:5] if isinstance(n, str)]
    summary["quarantined"] = len(quarantined)

    if args.dry_run:
        print(json.dumps({"would_merge": {
            "new_events": len(summary["new_events"]),
            "new_opportunities": len(summary["new_opportunities"]),
            "updated_events": len(summary["updated_events"]),
            "watchlist_updates": len(summary["watchlist_updates"]),
            "quarantined": len(quarantined),
            "reseen": summary["reseen"],
        }}, indent=2))
        return 0

    write_json(os.path.join(DATA, "events.json"), events_doc)
    write_json(os.path.join(DATA, "opportunities.json"), opps_doc)
    write_json(os.path.join(DATA, "watchlist.json"), watch_doc)

    if quarantined:
        qpath = os.path.join(LOCAL, "quarantine.json")
        q = read_json(qpath, {"items": []})
        q["items"].extend({"at": now_iso, **item} for item in quarantined)
        write_json(qpath, q)

    write_json(os.path.join(LOCAL, "merge_summary.json"), summary)
    promote_checkpoints(full_success=True)
    log(f"merge: OK +{len(summary['new_events'])} events, +{len(summary['new_opportunities'])} opps, "
        f"{len(summary['updated_events'])} updates, {len(quarantined)} quarantined, {summary['reseen']} re-seen")
    return 0


if __name__ == "__main__":
    sys.exit(main())
