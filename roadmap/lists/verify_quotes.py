#!/usr/bin/env python3
"""Check each checker's quote word for word against the page it came from.

The checkers read pages through a tool that sometimes summarises, so a "quote" can be a
paraphrase. This script opens each tag's evidence page itself (public addresses only, via
scan_rit) and records `quote_verified`: true (the words are on the page), false (not found
word for word), or null (the page could not be loaded). It changes nothing else.

  /usr/bin/python3 verify_quotes.py            # every list in dashboard/public/lists
"""
import concurrent.futures
import html
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_rit  # noqa: E402

_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                        " ": " ", "…": " ... "})


def _norm(text):
    return " ".join(text.translate(_TRANS).lower().split())


def quote_on_page(quote, page_html):
    """True when every part of the quote (split at ellipses) appears on the visible page as
    whole words, in the same order."""
    text = _norm(scan_rit.visible_text(page_html))
    parts = [p.strip(" .,;:") for p in re.split(r"\.{3}|…", _norm(quote))]
    parts = [p for p in parts if p]
    if not parts:
        return False
    pos = 0
    for part in parts:
        # whole words: no letter, digit, dot or hyphen glued to either end ("non-u.s." is not "u.s.")
        m = re.compile(r"(?<![\w.\-])" + re.escape(part) + r"(?![\w\-])").search(text, pos)
        if not m:
            return False
        pos = m.end()
    return True


def _fetch(url):
    if not scan_rit.is_public_url(url):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": scan_rit.UA, "Accept": "text/html,*/*;q=0.5"})
        with scan_rit._OPENER.open(req, timeout=scan_rit.TIMEOUT) as resp:
            return resp.read(scan_rit.MAX_BYTES * 3).decode("utf-8", "replace")
    except Exception:
        return None


def verify(doc, fetch=_fetch):
    todo = [e["audience"] for e in doc.get("entries", [])
            if isinstance(e.get("audience"), dict) and e["audience"].get("quote") and e["audience"].get("evidence_url")]
    pages = {}
    urls = sorted({a["evidence_url"] for a in todo})
    with concurrent.futures.ThreadPoolExecutor(max_workers=scan_rit.WORKERS) as pool:
        for url, page in zip(urls, pool.map(fetch, urls)):
            pages[url] = page
    counts = {"verified": 0, "not_found": 0, "page_not_loaded": 0}
    for a in todo:
        page = pages.get(a["evidence_url"])
        if page is None:
            a["quote_verified"] = None
            a.pop("citizenship_verified", None)   # an old result must not outlive a failed re-read
            counts["page_not_loaded"] += 1
        elif quote_on_page(a["quote"], page):
            a["quote_verified"] = True
            counts["verified"] += 1
        else:
            a["quote_verified"] = False
            counts["not_found"] += 1
        # The status rule decides whether she can apply, so it is checked the same way.
        if page is not None and isinstance(a.get("citizenship"), str) and a["citizenship"].strip():
            a["citizenship_verified"] = quote_on_page(a["citizenship"], page)
    return counts


FIT_QUOTES = {"noncitizen": "noncitizen_quote", "who": "who_quote", "pay": "pay_quote", "work_auth": "work_auth_quote"}


def verify_fit(doc, fetch=_fetch):
    """Check the quotes behind each `fit` record. Sets fit["verified"] = {field: true/false}
    for every quote given; removes it when the page cannot be loaded."""
    todo = [e["fit"] for e in doc.get("entries", [])
            if isinstance(e.get("fit"), dict) and e["fit"].get("evidence_url")
            and any(e["fit"].get(q) for q in FIT_QUOTES.values())]
    urls = sorted({f["evidence_url"] for f in todo})
    with concurrent.futures.ThreadPoolExecutor(max_workers=scan_rit.WORKERS) as pool:
        pages = dict(zip(urls, pool.map(fetch, urls)))
    counts = {"verified": 0, "not_found": 0, "page_not_loaded": 0}
    for f in todo:
        page = pages.get(f["evidence_url"])
        if page is None:
            f.pop("verified", None)   # an old result must not outlive a failed re-read
            counts["page_not_loaded"] += 1
            continue
        marks = {}
        for field, qkey in FIT_QUOTES.items():
            if f.get(qkey):
                marks[field] = quote_on_page(f[qkey], page)
                counts["verified" if marks[field] else "not_found"] += 1
        f["verified"] = marks
    return counts


def main():
    for name in sorted(os.listdir(scan_rit.OUT_DIR)):
        if not name.endswith(".json") or name in ("index.json", "notes.json"):
            continue
        path = os.path.join(scan_rit.OUT_DIR, name)
        with open(path) as f:
            doc = json.load(f)
        entries = doc.get("entries", [])
        if not any(e.get("audience") or e.get("fit") for e in entries):
            continue
        counts = verify(doc) if any(e.get("audience") for e in entries) else {}
        fit_counts = verify_fit(doc) if any(e.get("fit") for e in entries) else {}
        scan_rit._write_json(path, doc)
        print(f"{name}: tags {counts} fit {fit_counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
