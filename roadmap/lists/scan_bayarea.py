#!/usr/bin/env python3
"""Build the "Bay Area, local" list for the Lists tab of Ridhi's Roadmap.

Sources, each recorded on every entry:
  1. Bay Area Teen Science "Program listings" page, run at UC Berkeley
     (https://bayareateenscience.org/for-teens-overview/program-listings/), linked from the
     Cal High College and Career Center summer page. Parsed automatically: every program
     line under its section (h3) and group (h4, e.g. a university).
  2. Programs named on the Cal High summer page itself.
  3. Contra Costa and Alameda county programs found by web search on 2026-11-11.
Sources 2 and 3 are written out below with the source's own wording; nothing about
eligibility is asserted here. Each link is then opened once by scan_rit.check_link, which
records whether it works and quotes the page's own words around "high school" and any age.

Output: dashboard/public/lists/bayarea-local.json and an entry in lists/index.json.
Stand-alone: nothing else in the roadmap reads this file.

  /usr/bin/python3 scan_bayarea.py             # full build
  /usr/bin/python3 scan_bayarea.py --no-check  # no link visits
"""
import argparse
import concurrent.futures
import datetime
import html
import json
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_rit  # noqa: E402

BATS_URL = "https://bayareateenscience.org/for-teens-overview/program-listings/"
BATS_SOURCE = "Bay Area Teen Science program listings (UC Berkeley)"
CALHIGH_URL = "https://chs.srvusd.net/School-Info/Departments/College-and-Career-Center/Summer-Opportunities/index.html"
CALHIGH_SOURCE = "Cal High College and Career Center summer page"
SEARCH_SOURCE = "Web search, Nov 11, 2026"
SKIP_SECTIONS = {"resources for exploring and finding jobs", "classroom visits", "out-of-state programs"}
SLUG = "bayarea-local"


class _Bats(HTMLParser):
    """Collects each <li> (or <p>) inside <main> after the first section heading."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_main = 0
        self.heading = None
        self.buf = []
        self.section = ""
        self.group = ""
        self.stack = []      # open <li>/<p> items, innermost last; nested lists each get their own row
        self.href = None
        self.label = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.in_main += 1
        if not self.in_main:
            return
        if tag in ("h3", "h4"):
            self.heading, self.buf = tag, []
        elif tag in ("li", "p") and self.section:
            self.stack.append({"text": [], "links": []})
        elif tag == "a" and self.stack:
            self.href, self.label = dict(attrs).get("href") or "", []

    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main = max(0, self.in_main - 1)
        if not self.in_main:
            return
        if tag == self.heading:
            text = " ".join("".join(self.buf).split())
            if tag == "h3":
                self.section, self.group = text, ""
            else:
                self.group = text
            self.heading = None
        elif tag == "a" and self.stack and self.href is not None:
            self.stack[-1]["links"].append((" ".join("".join(self.label).split()), self.href.strip()))
            self.href = None
        elif tag in ("li", "p") and self.stack:
            item = self.stack.pop()
            self.rows.append((self.section, self.group, " ".join("".join(item["text"]).split()), item["links"]))

    def handle_data(self, data):
        if self.heading:
            self.buf.append(data)
        if self.stack:
            self.stack[-1]["text"].append(data)
            if self.href is not None:
                self.label.append(data)


def parse_bats(page_html):
    p = _Bats()
    p.feed(page_html)
    p.close()
    out = []
    for section, group, text, links in p.rows:
        if not section or section.lower() in SKIP_SECTIONS:
            continue
        good = [(label, href) for label, href in links if label and re.match(r"^https?://", href, re.I)]
        if not good or not text:
            continue
        # Prefer a link to a page over a link to a site's home page ("Teen Programs at the Oakland Zoo: Teen Summer Internships").
        deep = [g for g in good if re.sub(r"^https?://[^/]+", "", g[1]).strip("/")]
        chosen = (deep or good)[0][1]
        name, _, note = text.partition(" \u2013 Note:")
        out.append({
            "org": name.strip()[:200], "unit": group[:120], "city": "", "state": "CA", "region": "Bay Area",
            "section": section, "source": BATS_SOURCE, "listed_year": None,
            "desc": ("Note on the listing: " + note.strip())[:420] if note else "",
            "url": chosen,
        })
    return out


def _row(section, source, org, url, desc, unit=""):
    return {"org": org, "unit": unit, "city": "", "state": "CA", "region": "Bay Area", "section": section,
            "source": source, "listed_year": None, "desc": desc, "url": url}


def seed_entries():
    cal = "On the Cal High summer page"
    county = "County and hospital programs (Contra Costa, Alameda)"
    return [
        _row(cal, CALHIGH_SOURCE, "Summer SAGE (Science Accelerating Girls Engagement) in STEM",
             "https://apply.mykaleidoscope.com/scholarships/SAGE-LLNL-2026",
             "The Cal High page says: for young women 14 to 17; a week of job shadowing and hands-on projects at Lawrence Livermore National Lab and SLAC; deadlines in February or March.",
             "Lawrence Livermore National Laboratory and SLAC"),
        _row(cal, CALHIGH_SOURCE, "LLNL Biotechnology Summer Experience",
             "https://st.llnl.gov/sci-ed/summer-workshops/biotech-summer-experience",
             "The Cal High page says: a two-week program for high school students in molecular biology and bioinformatics, DNA research in a lab; applications open March 1; must be 16.",
             "Lawrence Livermore National Laboratory"),
        _row(cal, CALHIGH_SOURCE, "SPARK (Summer Program to Accelerate Regenerative Medicine Knowledge)",
             "https://www.cirm.ca.gov/our-impact/internship-programs/",
             "The Cal High page says: a six-week paid research internship in a stem cell lab, aimed at students who might not otherwise have research opportunities because of socioeconomic constraints.",
             "California Institute for Regenerative Medicine"),
        _row(cal, CALHIGH_SOURCE, "USDA AgDiscovery",
             "https://www.aphis.usda.gov/aphis/ourfocus/civilrights/agdiscovery/agdiscovery-program",
             "The Cal High page says: live on a college campus for 2 to 4 weeks with university and USDA scientists, including biotechnologists and veterinarians. Not Bay Area based.",
             "US Department of Agriculture"),
        _row(county, SEARCH_SOURCE, "Health Career Pathways, Contra Costa Health",
             "https://cchealth.org/about-contra-costa-health/work-with-cch/health-career-pathways",
             "The county health department's program working with high schools, colleges and community partners. Details are on the page.",
             "Contra Costa County"),
        _row(county, SEARCH_SOURCE, "Internship opportunities, Contra Costa Health",
             "https://www.cchealth.org/about-contra-costa-health/work-with-cch/internship-opportunities",
             "The county health department's list of internships by program area.", "Contra Costa County"),
        _row(county, SEARCH_SOURCE, "Student programs (including Young Healers), John Muir Health",
             "https://www.johnmuirhealth.com/about-john-muir-health/community-commitment/our-programs/student-programs",
             "Search results describe spring and summer internships for juniors and seniors run with Junior Achievement.",
             "John Muir Health, Walnut Creek and Concord"),
        _row(county, SEARCH_SOURCE, "High school student volunteering, John Muir Concord",
             "https://www.johnmuirhealth.com/get-involved/volunteer-services/concord-medical-center-high-school-student-volunteering",
             "The hospital's page for high school volunteers at the Concord campus.", "John Muir Health, Concord"),
        _row(county, SEARCH_SOURCE, "HealthX Fellowship, Making Waves",
             "https://making-waves.org/health-x-paid-career-pathway/",
             "Search results describe a paid healthcare career program for Bay Area teens from low-income backgrounds.",
             "Making Waves Foundation, Richmond"),
        _row(county, SEARCH_SOURCE, "Watershed Interns, Math Science Nucleus",
             "https://msnucleus.org/watersheds/explorer.html",
             "Search results describe a week-long environmental science internship with the Alameda County Flood Control District, for students with a year of high school science.",
             "Alameda County"),
        _row(county, SEARCH_SOURCE, "Internships and other placements, Alameda County Public Health",
             "https://health.alamedacountyca.gov/work-with-us-ph/internshipsandotherplacements/",
             "The county public health department's page on short placements, which search results say include high school students.",
             "Alameda County"),
        _row(county, SEARCH_SOURCE, "Internship and volunteer program, Alameda County District 1",
             "https://district1.alamedacountyca.gov/intern-program/",
             "A county supervisor's office program; search results say summer applications open between April and May.",
             "Alameda County"),
        _row(county, SEARCH_SOURCE, "High School and College Summer Healthcare Program, Touro University",
             "https://tu.edu/programs/pathway-programs/summer/",
             "A summer healthcare pathway program at Touro University California in Vallejo.", "Touro University California, Vallejo"),
        _row(county, SEARCH_SOURCE, "Summer programs list, San Ramon Valley High School",
             "https://srvhs.srvusd.net/School-Info/Departments/College--Career-Center/Extracurriculars/Summer-Programs/index.html",
             "Another SRVUSD high school's list of summer programs; it may name programs not listed here.", "San Ramon Valley High School"),
    ]


def merge(*groups):
    seen, out = set(), []
    for group in groups:
        for e in group:
            key = re.sub(r"^https?://(www\.)?", "", e["url"].strip().lower()).rstrip("/")
            if key not in seen:
                seen.add(key)
                out.append(e)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-check", action="store_true")
    args = ap.parse_args(argv)
    today = datetime.date.today()
    req = urllib.request.Request(BATS_URL, headers={"User-Agent": scan_rit.UA})
    with urllib.request.urlopen(req, timeout=40) as resp:
        page = resp.read().decode("utf-8", "replace")
    os.makedirs(scan_rit.LOCAL, exist_ok=True)
    with open(os.path.join(scan_rit.LOCAL, "bats-listings.html"), "w", encoding="utf-8") as f:
        f.write(page)
    bats = parse_bats(page)
    if len(bats) < 10:
        print(f"scan: only {len(bats)} programs found on the listing page; its layout may have changed")
        return 1
    entries = merge(seed_entries(), bats)
    out_path = os.path.join(scan_rit.OUT_DIR, f"{SLUG}.json")
    if not args.no_check:
        with concurrent.futures.ThreadPoolExecutor(max_workers=scan_rit.WORKERS) as pool:
            for e, result in zip(entries, pool.map(lambda e: scan_rit.check_link(e["url"], today.year), entries)):
                e["link"] = result
    doc = {
        "version": 1, "slug": SLUG, "label": "Bay Area, local",
        "title": "Bay Area programs: Cal High page, UC Berkeley's teen science listing, county programs",
        "source_url": BATS_URL, "sources": [BATS_URL, CALHIGH_URL], "source_last_modified": None,
        "scanned_on": today.isoformat(), "links_checked": not args.no_check,
        "summary": scan_rit.summarise(entries), "entries": entries,
    }
    scan_rit.add_ids(doc)
    try:
        with open(out_path) as f:
            scan_rit.carry_over(json.load(f), doc["entries"])
    except (OSError, ValueError):
        pass
    doc["summary"] = scan_rit.summarise(doc["entries"])
    scan_rit._write_json(out_path, doc)
    index_path = os.path.join(scan_rit.OUT_DIR, "index.json")
    try:
        with open(index_path) as f:
            index = json.load(f)
    except (OSError, ValueError):
        index = {"version": 1, "lists": []}
    index["lists"] = [x for x in index.get("lists", []) if x.get("slug") != SLUG] + [{
        "slug": SLUG, "label": "Bay Area, local", "title": doc["title"], "file": f"{SLUG}.json", "entries": len(entries),
        "scanned_on": today.isoformat(), "source_last_modified": None, "links_checked": not args.no_check}]
    scan_rit._write_json(index_path, index)
    s = doc["summary"]
    print(f"scan: {SLUG} — {s['entries']} entries, sections {s['by_section']}, links {s['links']}, "
          f"pages read {s['pages_read']}, mentioning {s['pages_mentioning']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
