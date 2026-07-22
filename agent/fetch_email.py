#!/usr/bin/env python3
"""Pull new school emails from Gmail via IMAP (app password from Keychain).

Candidate-state discipline: this script NEVER advances data/state/email_cursor.json.
It writes data/local/email_cursor.candidate.json; merge_results.py promotes it only
after a successful merge, so a failed run retries the same inputs next time.

Outputs:
  data/local/new_email.json           — messages fetched THIS run (input to build_bundle)
  data/snapshots/email/<date>.json    — daily archive (gitignored, 30-day prune)
  data/local/email_cursor.candidate.json

Usage: fetch_email.py [--dry-run] [--since YYYY-MM-DD]
Exit codes: 0 ok, 1 fatal (auth/IMAP), 0 with empty output when nothing new.
"""
import argparse
import datetime
import email
import email.policy
import imaplib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomicio import read_json, write_json
from lib.keychain import get_secret
from lib.runlog import log

REPO = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"
CONFIG = os.path.join(REPO, "agent", "config.json")
CURSOR = os.path.join(REPO, "data", "state", "email_cursor.json")
CANDIDATE = os.path.join(REPO, "data", "local", "email_cursor.candidate.json")
NEW_EMAIL = os.path.join(REPO, "data", "local", "new_email.json")
SNAP_DIR = os.path.join(REPO, "data", "snapshots", "email")

# Prefilter: drop low-value/PII-heavy lines before anything downstream sees them.
DROP_LINE = re.compile(
    r"(lunch\s+balance|meal\s+balance|student\s+id\s*[:#]|unsubscribe|"
    r"view\s+this\s+email\s+in\s+your\s+browser)",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")
STYLE_SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)


def html_to_text(html: str) -> str:
    text = STYLE_SCRIPT_RE.sub(" ", html)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", text, flags=re.IGNORECASE)
    text = TAG_RE.sub(" ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return text


def clean_body(text: str, max_chars: int) -> str:
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or DROP_LINE.search(line):
            continue
        lines.append(line)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out[:max_chars]


def extract_body(msg, max_chars: int) -> str:
    plain, html = None, None
    for part in msg.walk():
        ctype = part.get_content_type()
        if part.get_content_disposition() == "attachment":
            continue
        try:
            payload = part.get_content()
        except Exception:
            continue
        if ctype == "text/plain" and plain is None:
            plain = payload
        elif ctype == "text/html" and html is None:
            html = payload
    if plain:
        return clean_body(plain, max_chars)
    if html:
        return clean_body(html_to_text(html), max_chars)
    return ""


def extract_ics_dates(msg) -> list:
    """Best-effort DTSTART/SUMMARY pairs from .ics attachments."""
    found = []
    for part in msg.walk():
        if part.get_content_type() in ("text/calendar", "application/ics"):
            try:
                ics = part.get_content()
                if isinstance(ics, bytes):
                    ics = ics.decode("utf-8", "replace")
            except Exception:
                continue
            starts = re.findall(r"DTSTART[^:]*:(\d{8}(?:T\d{6})?)", ics)
            summaries = re.findall(r"SUMMARY[^:]*:(.+)", ics)
            for i, s in enumerate(starts):
                found.append({
                    "dtstart": s,
                    "summary": (summaries[i].strip() if i < len(summaries) else ""),
                })
    return found


def imap_connect(cfg):
    password = get_secret(cfg["keychain"]["gmail"])
    conn = imaplib.IMAP4_SSL(cfg["imap"]["host"], timeout=60)
    conn.login(cfg["imap"]["user"], password)
    conn.select(cfg["imap"]["mailbox"], readonly=True)
    return conn


def search_uids(conn, sender_domains, since_date=None, min_uid=None):
    """Union of per-sender UID searches (IMAP OR nesting is brittle across 4+ terms).

    Returns (uids, search_failed). A failed domain search means unknown messages
    exist — the caller must NOT advance the cursor past them.
    """
    uids, search_failed = set(), False
    for domain in sender_domains:
        criteria = ["FROM", f'"{domain}"']
        if since_date:
            criteria += ["SINCE", since_date.strftime("%d-%b-%Y")]
        if min_uid:
            criteria = ["UID", f"{min_uid}:*"] + criteria
        try:
            typ, data = conn.uid("SEARCH", *criteria)
        except Exception as e:
            log(f"fetch_email: SEARCH exception for {domain}: {e}")
            search_failed = True
            continue
        if typ != "OK":
            log(f"fetch_email: SEARCH failed for {domain}: {typ}")
            search_failed = True
            continue
        if data and data[0]:
            uids.update(int(u) for u in data[0].split())
    return sorted(uids), search_failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    ap.add_argument("--since", help="override start date YYYY-MM-DD")
    args = ap.parse_args()

    with open(CONFIG) as f:
        cfg = json.load(f)
    cursor = read_json(CURSOR, {})
    today = datetime.date.today()

    conn = imap_connect(cfg)
    try:
        # UIDVALIDITY guards the cursor's meaning.
        uidvalidity = int(conn.untagged_responses.get("UIDVALIDITY", [b"0"])[0])
        stored_validity = cursor.get("uidvalidity")
        min_uid = None
        since_date = None

        if args.since:
            since_date = datetime.date.fromisoformat(args.since)
        elif stored_validity is None or not cursor.get("backfill_done"):
            since_date = today - datetime.timedelta(days=cursor.get("backfill_days", 180))
            log(f"fetch_email: initial backfill since {since_date}")
        elif stored_validity != uidvalidity:
            since_date = today - datetime.timedelta(days=7)
            log(f"fetch_email: UIDVALIDITY changed {stored_validity}->{uidvalidity}, re-baseline 7d")
        else:
            min_uid = int(cursor.get("last_uid", 0)) + 1

        uids, search_failed = search_uids(conn, cfg["imap"]["sender_domains"], since_date, min_uid)
        # min_uid searches can return the last already-seen UID again (IMAP quirk: n:* always
        # matches the highest UID) — filter strictly.
        if min_uid:
            uids = [u for u in uids if u >= min_uid]

        if args.dry_run:
            print(f"fetch_email dry-run: {len(uids)} message(s) would be fetched"
                  + (" (search failures present)" if search_failed else ""))
            return 0

        messages, seen_msgids, failed_uids = [], set(), []
        # Date-based searches (backfill / UIDVALIDITY re-baseline) start a FRESH cursor:
        # the old namespace's last_uid must never leak into the new one.
        max_uid = int(cursor.get("last_uid") or 0) if min_uid else 0
        for uid in uids:
            try:
                typ, data = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
            except Exception as e:
                log(f"fetch_email: FETCH exception uid {uid}: {e}")
                failed_uids.append(uid)
                continue
            if typ != "OK" or not data or data[0] is None:
                failed_uids.append(uid)
                continue
            raw = data[0][1]
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            msgid = (msg.get("Message-ID") or f"uid-{uidvalidity}-{uid}").strip()
            if msgid in seen_msgids:
                continue
            seen_msgids.add(msgid)
            max_uid = max(max_uid, uid)
            messages.append({
                "uid": uid,
                "message_id": msgid,
                "date": (msg.get("Date") or "")[:64],
                "from": (msg.get("From") or "")[:128],
                "subject": (msg.get("Subject") or "")[:256],
                "body": extract_body(msg, cfg["imap"]["max_body_chars"]),
                "ics": extract_ics_dates(msg),
            })
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    write_json(NEW_EMAIL, {"fetched_at": datetime.datetime.now().isoformat(), "messages": messages})

    # Daily archive (append to today's snapshot, dedupe by message_id).
    snap_path = os.path.join(SNAP_DIR, f"{today.isoformat()}.json")
    snap = read_json(snap_path, {"messages": []})
    known = {m["message_id"] for m in snap["messages"]}
    snap["messages"].extend(m for m in messages if m["message_id"] not in known)
    write_json(snap_path, snap)

    # Candidate cursor — promoted by merge_results.py only after a successful merge.
    # Never advance past a UID we failed to fetch, and don't write a candidate at all
    # when a domain search failed (unknown messages may exist below max_uid).
    if search_failed:
        if os.path.exists(CANDIDATE):
            os.unlink(CANDIDATE)
        log(f"fetch_email: {len(messages)} message(s) fetched but SEARCH failures present — cursor NOT advanced")
        return 0
    promote_uid = max_uid
    if failed_uids:
        promote_uid = min(min(failed_uids) - 1, max_uid)
        promote_uid = max(promote_uid, int(cursor.get("last_uid") or 0) if min_uid else 0)
        log(f"fetch_email: {len(failed_uids)} FETCH failure(s) — cursor capped at {promote_uid}")
    write_json(CANDIDATE, {
        "uidvalidity": uidvalidity,
        "last_uid": promote_uid,
        "backfill_done": True,
        "backfill_days": cursor.get("backfill_days", 180),
    })

    log(f"fetch_email: {len(messages)} new message(s), cursor candidate={promote_uid}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyError as e:
        log(f"fetch_email FATAL: {e}")
        sys.exit(1)
    except (imaplib.IMAP4.error, OSError) as e:
        log(f"fetch_email FATAL: IMAP failure: {e}")
        sys.exit(1)
