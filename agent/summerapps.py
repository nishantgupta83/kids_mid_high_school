#!/usr/bin/env python3
"""Upcoming summer-programme applications for the digest grid.

Source of truth is data/summer_apps.json, a HAND-maintained snapshot of the parent's
Drive sheets. Nothing in the scan writes it.

Two rules earn their keep here:

1. Never raise. A hand-editing slip in this optional section must not take the whole
   digest down — send_digest wraps rendering in one try/except that degrades to a bare
   "digest error" email, so an exception here would cost the family its action items.
   load_upcoming() therefore returns an empty grid on any malformed input.

2. An ESTIMATED date never expires a row and never colours one. Entries whose date was
   inferred from words like "~Dec" or "Spring" carry approx=true; their visibility is
   governed by `until` (the generous end of the stated window) and they are shown with
   the sheet's own wording instead of a countdown. A guessed midpoint used as a deadline
   would quietly delete opportunities that are still open.
"""
import datetime
import json
import os

REPO = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school"
APPS_FILE = os.path.join(REPO, "data", "summer_apps.json")

GRID_MAX = 10          # DATED rows shown; the rest collapse into one tail line
ROLLING_MAX = 3        # rolling rows always get their own slots (they sort last,
                       # so a shared cap would hide them permanently)
STALE_DAYS = 120       # snapshot older than this gets a re-sync nudge


def _text(value):
    """Text fields must be strings: html.escape() on an int raises, and that exception
    would surface inside send_digest's single try/except and replace the ENTIRE digest
    with a bare error email. A hand-edited file must not be able to do that."""
    return value if isinstance(value, str) else ""


def _as_date(value):
    """ISO date or None. Anything malformed reads as None rather than raising."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def load_upcoming(today, path=APPS_FILE):
    """-> (rows, more_count, stale_note). Never raises, never partially fails."""
    try:
        with open(path) as f:
            doc = json.load(f)
        apps = doc.get("applications")
        if not isinstance(apps, list):
            return [], 0, None
    except (OSError, ValueError, AttributeError):
        return [], 0, None

    rows = []
    for a in apps:
        if not isinstance(a, dict):
            continue
        title = a.get("title")
        if not isinstance(title, str) or not title:
            continue  # title is a sort tiebreak; a missing one must not blow up sorted()
        deadline = _as_date(a.get("deadline"))
        until = _as_date(a.get("until"))
        # Rolling (no until) never expires. Otherwise hide the day after `until`.
        if until is not None and until < today:
            continue
        approx = bool(a.get("approx"))
        # A STATED deadline that has passed is gone, whatever `until` says. Without this a
        # row with a generous `until` renders as "today" in coral after its real deadline.
        if deadline is not None and not approx and deadline < today:
            continue
        # Countdown/urgency only from a date the sheet actually stated.
        days = (deadline - today).days if (deadline is not None and not approx) else None
        rolling = deadline is None and until is None
        rows.append({
            "id": _text(a.get("id")) or title,
            "title": title,
            "org": _text(a.get("org")),
            "window": _text(a.get("window")),
            "action": _text(a.get("action")),
            "note": _text(a.get("note")),
            "track": _text(a.get("track")),
            # A rolling row has no date to confirm, so the "confirm the date" hint is noise.
            "verify": bool(a.get("verify")) and not rolling,
            "approx": approx,
            "deadline": deadline,
            "days": days,
            "rolling": rolling,
        })

    # Dated first (ordered by date), rolling last; title breaks ties deterministically.
    rows.sort(key=lambda r: (r["deadline"] is None, r["deadline"] or datetime.date.max, r["title"]))

    stale_note = None
    synced = _as_date((doc.get("source") or {}).get("synced")) if isinstance(doc.get("source"), dict) else None
    if synced is not None and (today - synced).days > STALE_DAYS:
        stale_note = f"list last synced from the sheets {synced.isoformat()}"
    elif synced is None:
        stale_note = "list has no sync date"

    # Rolling rows get reserved slots: they sort last, so a single shared cap would hide
    # them every single day. `more` counts only the dated rows that did not fit.
    dated = [r for r in rows if not r["rolling"]]
    rolling = [r for r in rows if r["rolling"]]
    shown = dated[:GRID_MAX] + rolling[:ROLLING_MAX]
    return shown, max(0, len(dated) - GRID_MAX), stale_note
