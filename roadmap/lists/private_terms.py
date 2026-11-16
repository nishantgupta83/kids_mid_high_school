"""Family-specific words the public-list scrubbers look for, kept OUT of git.

The real terms (her birthday, visa type, the priority-date year...) live in the
gitignored roadmap/local/private_terms.json:

  {
    "scrub_notes":  ["regex", ...],   extra: drop a notes sentence that matches
    "scrub_fields": ["regex", ...],   extra: drop a page-derived field that matches
    "never_public": ["regex", ...],   must never appear in files the site serves
    "never_in_data": ["regex", ...]   must never appear in roadmap/data (e.g. the priority date)
  }

Code that WRITES public files calls require(): with the file missing it stops, so a
checkout without the file (a fresh clone, a cloud session) can't publish a weaker scrub.
"""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "local", "private_terms.json")
KEYS = ("scrub_notes", "scrub_fields", "never_public", "never_in_data")


def load(path=PATH):
    """-> dict of the three lists (empty lists when the file is missing)."""
    if not os.path.exists(path):
        return {k: [] for k in KEYS}
    with open(path) as f:
        data = json.load(f)
    return {k: [str(t) for t in data.get(k, [])] for k in KEYS}


def present(path=PATH):
    return os.path.exists(path)


def require(path=PATH):
    """Stop unless the file exists, has only known keys, and every scrub list is filled."""
    if not present(path):
        raise SystemExit(f"private terms file missing: {path} (local-only; refusing to write public lists without it)")
    with open(path) as f:
        raw = json.load(f)
    unknown = sorted(set(raw) - set(KEYS)) if isinstance(raw, dict) else ["<not an object>"]
    empty = [k for k in ("scrub_notes", "scrub_fields", "never_public") if not load(path)[k]]
    if unknown or empty:
        raise SystemExit(f"private terms file {path} is incomplete (unknown keys {unknown}, empty {empty}); "
                         "refusing to write public lists")
