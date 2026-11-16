#!/usr/bin/env python3
"""Scan one category page of RIT's "Co-op/Internships and Summer Research Opportunities
in the Life Sciences" list (people.rit.edu/~gtfsbi/Symp/) and publish a digest of it.

What it does, in order:
  1. downloads the category page (kept in roadmap/local/rit/, gitignored);
  2. parses every entry: organisation, city/state, the year the list last touched the
     entry, its description and its "co-op" link;
  3. opens each entry's link once and records whether it still works and which words the
     page uses (high school, undergraduate, citizen / permanent resident, international
     student, the current or next year);
  4. writes dashboard/public/lists/rit-<slug>.json and updates lists/index.json.

The word checks are plain text matches made by this script. Nobody read the pages. They
say "the page mentions X", never "the programme requires X".

The output holds only public information about public programmes. It is deliberately a
standalone file: nothing else in the roadmap reads it and it reads nothing else.

  /usr/bin/python3 scan_rit.py bme            # full scan
  /usr/bin/python3 scan_rit.py bme --no-check # parse only, no link visits

Web pages are untrusted input: they are parsed as text, never executed or obeyed.
Stdlib only.
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request
from html.parser import HTMLParser

ROADMAP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROADMAP)
LOCAL = os.path.join(ROADMAP, "local", "rit")
OUT_DIR = os.path.join(REPO, "dashboard", "public", "lists")
BASE = "https://people.rit.edu/~gtfsbi/Symp/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) list-reader/1.0"
SLUG = re.compile(r"^[A-Za-z0-9]{2,30}$")
STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
             "OH OK OR PA PR RI SC SD TN TX UT VT VA WA WV WI WY".split())
MAX_BYTES = 200_000
WORKERS = 8
TIMEOUT = 14          # per socket operation
DEADLINE = 30         # whole request, so a trickling server cannot hold a worker


class _Chunker(HTMLParser):
    """Turns the page into entry-sized chunks. The list has no real structure: entries
    are runs of inline markup separated by <br> or paragraph breaks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []
        self.cur = {"text": [], "links": []}
        self.href = None
        self.buf = []
        self.skip = 0

    def _cut(self):
        if self.cur["text"] or self.cur["links"]:
            self.chunks.append(self.cur)
        self.cur = {"text": [], "links": []}

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("br", "p", "hr", "tr", "li", "div", "table"):
            self._cut()
        elif tag == "a":
            self.href = dict(attrs).get("href") or ""
            self.buf = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("p", "tr", "li", "div", "table"):
            self._cut()
        elif tag == "a" and self.href is not None:
            label = " ".join("".join(self.buf).split())
            self.cur["links"].append((label, self.href))
            self.cur["text"].append(f" ⟦{len(self.cur['links']) - 1}⟧ ")
            self.href = None

    def handle_data(self, data):
        if self.skip:
            return
        if self.href is not None:
            self.buf.append(data)
        else:
            self.cur["text"].append(data)

    def close(self):
        super().close()
        self._cut()


def _http(u):
    return isinstance(u, str) and re.match(r"^https?://", u.strip(), re.I) is not None


SECTION = re.compile(r"^[A-Za-z]{2,12}$")


def extract_section(page_html, name):
    """The part of a page between <a name="NAME"> and the next named anchor, or None.
    The by-state page marks each state (and a few countries) with such an anchor."""
    start = re.search(rf'<a\s+name\s*=\s*"{re.escape(name)}"', page_html, re.I)
    if not start:
        return None
    nxt = re.search(r'<a\s+name\s*=\s*"', page_html[start.end():], re.I)
    return page_html[start.start(): start.end() + nxt.start()] if nxt else page_html[start.start():]


# Rough travel regions from the San Ramon area, by the city the list gives.
_REGIONS = [
    ("Bay Area", "san-francisco south-san-francisco oakland berkeley emeryville alameda richmond albany el-cerrito "
                 "stanford palo-alto menlo-park redwood-city redwood-shores san-carlos burlingame san-mateo foster-city "
                 "brisbane mountain-view sunnyvale santa-clara san-jose milpitas fremont newark hayward pleasanton "
                 "livermore dublin san-ramon danville walnut-creek concord martinez moffett-field novato san-rafael "
                 "sausalito tiburon mill-valley"),
    ("Sacramento and Davis", "davis sacramento"),
    ("Santa Cruz and Monterey", "santa-cruz moss-landing monterey pacific-grove salinas"),
    ("Southern California", "los-angeles la-jolla san-diego pasadena irvine thousand-oaks duarte riverside santa-barbara "
                            "torrance carlsbad long-beach malibu claremont san-marcos encinitas westwood avalon catalina-island fullerton loma-linda"),
]
_REGION_OF = {city: region for region, cities in _REGIONS for city in cities.split()}


def region_of(city, state):
    if state != "CA":
        return ""
    if not city:
        return "California, place not stated"
    return _REGION_OF.get("-".join(city.lower().split()), "Other California")


def parse_entries(page_html, default_state=""):
    """-> list of entries. An entry is a chunk that has a link labelled "co-op".
    `default_state` is used when an entry inside a state's section gives no state of its own."""
    p = _Chunker()
    p.feed(page_html)
    p.close()
    entries = []
    for ch in p.chunks:
        links = ch["links"]
        coop = [i for i, (label, href) in enumerate(links) if label.lower() in ("co-op", "coop", "co-ops") and _http(href)]
        if not coop:
            continue
        first = coop[0]
        named = [(label, href) for label, href in links[:first] if label]
        if not named:
            continue
        text = " ".join("".join(ch["text"]).split())
        before, _, after = text.partition(f"⟦{first}⟧")
        before_plain = re.sub(r"⟦\d+⟧", "", before)
        loc = None
        if default_state:   # an organisation with several sites: prefer its site in this state
            loc = re.search(rf",\s*([A-Za-z .'\-]{{2,40}}),\s*({re.escape(default_state)})\b", before_plain)
        loc = loc or re.search(r",\s*([A-Za-z .'\-]{2,40}),\s*([A-Z]{2})\b[^,]*$", before_plain.strip(" -–"))
        city, state = (loc.group(1).strip(), loc.group(2)) if loc and loc.group(2) in STATES else ("", "")
        if not state and default_state:
            state = default_state
        after_plain = " ".join(re.sub(r"⟦\d+⟧", lambda m: links[int(m.group(0)[1:-1])][0], after).split())
        year = re.search(r"\((20\d\d|19\d\d)\)", after_plain)
        desc = after_plain[year.end():] if year else after_plain
        desc = re.sub(r"^[\s,\-–]*(more details|application|details)?[\s,\-–]*", "", desc, flags=re.I).strip(" -–,")
        entries.append({
            "org": named[0][0][:160],
            "unit": "; ".join(label for label, _ in named[1:])[:200],
            "city": city, "state": state,
            "listed_year": int(year.group(1)) if year else None,
            "desc": desc[:420],
            "url": links[first][1].strip(),
            "region": region_of(city, state),
        })
    # the same programme can be listed twice on one page; keep the first
    seen, out = set(), []
    for e in entries:
        key = (e["org"].lower(), e["url"].lower())
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


WORDS = {
    "high_school": re.compile(r"high[- ]school", re.I),
    "undergraduate": re.compile(r"undergraduate", re.I),
    "citizenship": re.compile(r"u\.?\s?s\.?\s+citizen|permanent resident|citizenship", re.I),
    "international": re.compile(r"international (student|applicant|undergraduate)s?|regardless of (citizenship|nationality)"
                               r"|\bf-?1 (visa|student)|non-u\.?\s?s\.? citizens?", re.I),
    # An age needs an age word after the number ("16 years", "17 or older"), so page
    # numbers, minutes, months and credits do not count.
    "age_rule": re.compile(r"\b(at least|minimum age( of)?|must be|ages?|aged)\s+1[3-9]\s*(years|yrs|or older|of age)"
                           r"|\b1[3-9]\s*(-|to|–)\s*1[4-9]\s*(years|yrs)"
                           r"|\b1[3-9]\s*(years|yrs)\.?\s*(of age|old|or older)", re.I),
}


def visible_text(page_html):
    """Text a reader would see: comments, scripts and styles removed, tags stripped."""
    no_hidden = re.sub(r"(?is)<!--.*?-->|<(script|style)\b.*?</\1>", " ", page_html)
    return html.unescape(re.sub(r"<[^>]+>", " ", no_hidden))


def page_words(text, year):
    flags = {k: bool(rx.search(text)) for k, rx in WORDS.items()}
    flags["current_year"] = bool(re.search(rf"\b({year}|{year + 1})\b", text))
    return flags


SNIPPET_KEYS = ("high_school", "age_rule", "citizenship", "international")


def page_snippets(text):
    """The words around the first 'high school' and the first age statement on a page,
    so a reader can see what the match refers to (students? teachers? another program?).
    Copied text, cut to at most about 190 characters."""
    flat = " ".join(text.split())
    out = {}
    for key in SNIPPET_KEYS:
        m = WORDS[key].search(flat)
        if not m:
            continue
        a, b = max(0, m.start() - 90), min(len(flat), m.end() + 90)
        a = flat.rfind(" ", 0, a) + 1 if a else 0
        b = flat.find(" ", b) if flat.find(" ", b) != -1 else len(flat)
        out[key] = ("…" if a else "") + flat[a:b].strip() + ("…" if b < len(flat) else "")
    return out


def is_public_url(url):
    """True only for http(s) addresses on the public internet. The list is third-party
    content: an entry (or a redirect) pointing at this Mac or the home network must never
    be opened, so loopback, private, link-local and reserved addresses are refused."""
    try:
        parts = urllib.parse.urlsplit(url or "")
    except (ValueError, AttributeError, TypeError):
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    host = parts.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True   # does not resolve: opening it will simply fail, there is nothing to protect
    try:
        return all(ipaddress.ip_address(info[4][0].split("%")[0]).is_global for info in infos)
    except ValueError:
        return False


class _PublicOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_public_url(newurl):
            raise urllib.error.HTTPError(newurl, code, "redirect to a non-public address refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_PublicOnlyRedirects, urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def check_link(url, year):
    """-> {'status': ok|gone|blocked|error|skipped, 'code': int|None, 'words': {...}|None}. Never raises."""
    if not is_public_url(url):
        return {"status": "skipped", "code": None, "words": None}
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.5"})
    try:
        started = time.monotonic()
        with _OPENER.open(req, timeout=TIMEOUT) as resp:
            chunks, size = [], 0
            while size < MAX_BYTES:
                if time.monotonic() - started > DEADLINE:
                    return {"status": "error", "code": None, "words": None}
                chunk = resp.read(min(16_384, MAX_BYTES - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            raw = b"".join(chunks)
            ctype = resp.headers.get("Content-Type", "")
            code = resp.status
        if "html" not in ctype.lower() and "text" not in ctype.lower():
            return {"status": "ok", "code": code, "words": None}
        text = visible_text(raw.decode("utf-8", "replace"))
        result = {"status": "ok", "code": code, "words": page_words(text, year)}
        snippets = page_snippets(text)
        if snippets:
            result["snippets"] = snippets
        return result
    except urllib.error.HTTPError as e:
        kind = "gone" if e.code in (404, 410) else "blocked" if e.code in (401, 403, 429) else "error"
        return {"status": kind, "code": e.code, "words": None}
    except Exception:
        return {"status": "error", "code": None, "words": None}


def fetch_page(slug):
    url = BASE + slug + ".htm"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as resp:
        raw = resp.read()
        modified = resp.headers.get("Last-Modified")
    os.makedirs(LOCAL, exist_ok=True)
    with open(os.path.join(LOCAL, slug + ".htm"), "wb") as f:
        f.write(raw)
    stamp = None
    if modified:
        try:
            stamp = datetime.datetime.strptime(modified, "%a, %d %b %Y %H:%M:%S %Z").date().isoformat()
        except ValueError:
            stamp = None
    title = re.search(r"(?is)<title>(.*?)</title>", raw.decode("utf-8", "replace"))
    return raw.decode("utf-8", "replace"), url, stamp, " ".join(html.unescape(title.group(1)).split()) if title else slug


def add_ids(doc):
    """Give every entry an id the dashboard API accepts (`lst:<id>`), built from the list
    and the programme's name and link, so a saved choice survives a rescan."""
    prefix = re.sub(r"[^a-z0-9-]+", "-", str(doc.get("slug", "list")).lower()).strip("-")[:30] or "list"
    for e in doc.get("entries", []):
        key = (e.get("org", "").strip().lower() + "|" + e.get("url", "").strip().lower()).encode()
        e["id"] = f"{prefix}-{hashlib.sha1(key).hexdigest()[:10]}"
    return doc


def carry_over(old_doc, new_entries):
    """Keep checked tags (`audience`) from the previous scan: by id first, else by the same
    name in the same section when the name is unique. Nothing is ever removed."""
    def host(u):
        h = urllib.parse.urlsplit(u or "").hostname or ""
        return h[4:] if h.startswith("www.") else h

    def key(e):
        return (e.get("org", "").lower(), e.get("section") or "", host(e.get("url")))

    old = [e for e in (old_doc or {}).get("entries", []) if isinstance(e, dict) and e.get("audience")]
    by_id = {e.get("id"): e for e in old}
    old_by_key, new_by_key = {}, {}
    for e in old:
        old_by_key.setdefault(key(e), []).append(e)
    for e in new_entries:
        new_by_key.setdefault(key(e), []).append(e)
    for e in new_entries:
        prev = by_id.get(e.get("id"))
        if prev is None:
            # Fallback by name only when it is unambiguous on both sides and on the same site.
            olds, news = old_by_key.get(key(e), []), new_by_key.get(key(e), [])
            prev = olds[0] if len(olds) == 1 and len(news) == 1 else None
        if prev is not None and "audience" not in e:
            e["audience"] = prev["audience"]
    return new_entries


def summarise(entries):
    def count(fn):
        out = {}
        for e in entries:
            k = fn(e)
            if k is not None:
                out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], str(kv[0]))))
    checked = [e for e in entries if e.get("link")]
    words = {k: sum(1 for e in checked if (e["link"].get("words") or {}).get(k)) for k in list(WORDS) + ["current_year"]}
    return {
        "entries": len(entries),
        "by_state": count(lambda e: e["state"] or "not stated"),
        "by_region": count(lambda e: e.get("region") or None),
        "by_section": count(lambda e: e.get("section") or None),
        **({"by_audience": count(lambda e: (e.get("audience") or {}).get("tag", "not checked"))}
           if any(e.get("audience") for e in entries) else {}),
        "by_listed_year": count(lambda e: e["listed_year"] if e["listed_year"] else "no year"),
        "links": count(lambda e: e["link"]["status"] if e.get("link") else None),
        "pages_read": sum(1 for e in checked if e["link"].get("words") is not None),
        "pages_mentioning": words,
    }


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Serialise first: if the document cannot be written, nothing is created in the public folder.
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--section", help="only the part of the page under this anchor, e.g. CA")
    ap.add_argument("--label", help="short name shown on the Lists tab")
    ap.add_argument("--no-check", action="store_true")
    args = ap.parse_args(argv)
    if not SLUG.match(args.slug) or (args.section and not SECTION.match(args.section)):
        print("scan: bad page or section name")
        return 2
    today = datetime.date.today()
    page, url, modified, title = fetch_page(args.slug)
    out_slug = args.slug
    if args.section:
        part = extract_section(page, args.section)
        if part is None:
            print(f"scan: no section named {args.section} on the page")
            return 1
        page, url, out_slug = part, url + "#" + args.section, f"{args.slug}-{args.section.lower()}"
    state = args.section.upper() if args.section and args.section.upper() in STATES else ""
    entries = parse_entries(page, default_state=state)
    if not entries:
        print("scan: no entries found — the page layout may have changed")
        return 1
    if not args.no_check:
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for e, result in zip(entries, pool.map(lambda e: check_link(e["url"], today.year), entries)):
                e["link"] = result
    label = (args.label or "").strip()[:40] or out_slug
    if args.section:
        title = f"{title} — section {args.section}"
    doc = {
        "version": 1, "slug": out_slug, "label": label, "title": title, "source_url": url,
        "source_last_modified": modified, "scanned_on": today.isoformat(),
        "links_checked": not args.no_check,
        "summary": summarise(entries), "entries": entries,
    }
    add_ids(doc)
    try:
        with open(os.path.join(OUT_DIR, f"rit-{out_slug}.json")) as f:
            carry_over(json.load(f), doc["entries"])
    except (OSError, ValueError):
        pass
    doc["summary"] = summarise(doc["entries"])
    _write_json(os.path.join(OUT_DIR, f"rit-{out_slug}.json"), doc)
    index_path = os.path.join(OUT_DIR, "index.json")
    try:
        with open(index_path) as f:
            index = json.load(f)
    except (OSError, ValueError):
        index = {"version": 1, "lists": []}
    index["lists"] = [x for x in index.get("lists", []) if x.get("slug") != out_slug] + [{
        "slug": out_slug, "label": label, "title": title, "file": f"rit-{out_slug}.json", "entries": len(entries),
        "scanned_on": today.isoformat(), "source_last_modified": modified, "links_checked": not args.no_check}]
    _write_json(index_path, index)
    s = doc["summary"]
    print(f"scan: {out_slug} — {s['entries']} entries, regions {s['by_region']}, links {s['links']}, pages read {s['pages_read']}, "
          f"mentioning {s['pages_mentioning']}, page last modified {modified}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
