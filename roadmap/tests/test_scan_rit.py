#!/usr/bin/env python3
"""Run: /usr/bin/python3 /Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school/roadmap/tests/test_scan_rit.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lists"))
import scan_rit  # noqa: E402

PAGE = """<html><head><title>Test list</title><script>var a = '<a href="http://evil/">co-op</a>';</script></head><body>
<p>To view information: click <font><u>co-op</u></font> to go to postings</p>
<p align="left"><b><a href="http://www.alasu.edu/index.aspx">Alabama State University</a></b>, Montgomery, AL -
 <a href="http://www.alasu.edu/reu">co-op</a>, <a href="http://bioreu-alasu.org/">more details</a>,
 <a href="http://bioreu-alasu.org/apply/">application</a> <b>(2020)</b> Research Experiences for Undergraduates in
 NanoBioengineering - &quot;Tissue regeneration&quot;<br>
<a href="https://www.binghamton.edu/"><b>Binghamton University</b></a>, <a href="https://www.binghamton.edu/bme/">Department
 of Biomedical Engineering</a>, Binghamton, NY - <a href="https://www.binghamton.edu/bme/reu/index.html">co-op</a>
 <b>(2019)</b> Biomedical Translational Science &amp; Technology<br>
<b><a href="https://www.epfl.ch/">Ecole Polytechnique</a></b>, Lausanne, Switzerland - <a href="https://www.epfl.ch/summer">co-op</a> (2018) Summer research<br>
<b><a href="http://x.example/">Bad Link Org</a></b>, Nowhere, ZZ - <a href="javascript:alert(1)">co-op</a> (2020) nope<br>
<b><a href="http://www.alasu.edu/index.aspx">Alabama State University</a></b>, Montgomery, AL - <a href="http://www.alasu.edu/reu">co-op</a> (2020) duplicate
</p></body></html>"""


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.entries = scan_rit.parse_entries(PAGE)

    def test_finds_each_real_entry_once(self):
        self.assertEqual([e["org"] for e in self.entries],
                         ["Alabama State University", "Binghamton University", "Ecole Polytechnique"])

    def test_reads_place_year_and_link(self):
        a = self.entries[0]
        self.assertEqual((a["city"], a["state"], a["listed_year"]), ("Montgomery", "AL", 2020))
        self.assertEqual(a["url"], "http://www.alasu.edu/reu")
        self.assertIn("NanoBioengineering", a["desc"])
        self.assertNotIn("more details", a["desc"])

    def test_keeps_the_department_as_the_unit(self):
        b = self.entries[1]
        self.assertEqual(b["unit"], "Department of Biomedical Engineering")
        self.assertEqual((b["city"], b["state"], b["listed_year"]), ("Binghamton", "NY", 2019))
        self.assertEqual(b["desc"], "Biomedical Translational Science & Technology")

    def test_a_place_outside_the_us_has_no_state(self):
        self.assertEqual(self.entries[2]["state"], "")

    def test_script_text_and_non_http_links_are_ignored(self):
        self.assertFalse(any("evil" in e["url"] or e["url"].startswith("javascript") for e in self.entries))

    def test_word_checks_are_plain_matches(self):
        w = scan_rit.page_words("Open to high-school students. U.S. citizens or permanent residents only. Apply by 2027.", 2026)
        self.assertEqual(w, {"high_school": True, "undergraduate": False, "citizenship": True, "international": False,
                             "age_rule": False, "current_year": True})
        self.assertTrue(scan_rit.page_words("Applicants must be at least 16 years old.", 2026)["age_rule"])
        self.assertTrue(scan_rit.page_words("Open to students 15-18 years of age", 2026)["age_rule"])
        self.assertFalse(scan_rit.page_words("We have 16 labs and 18 projects.", 2026)["age_rule"])
        for not_an_age in ("Page 14 of 20", "messages 13 new", "aged 18 months", "at least 15 minutes", "must be 18 credits"):
            self.assertFalse(scan_rit.page_words(not_an_age, 2026)["age_rule"], not_an_age)
        for an_age in ("must be 16 years old", "aged 17 or older", "ages 15 to 18 years", "Minimum age of 16 years"):
            self.assertTrue(scan_rit.page_words(an_age, 2026)["age_rule"], an_age)
        self.assertFalse(scan_rit.page_words("Program from 2019.", 2026)["current_year"])

    def test_the_sentence_around_a_match_is_kept(self):
        text = ("Lots of menu text here. " * 10) + "The program is open to high school students who will be at least 16 years old by June 1. " + ("Footer. " * 20)
        snips = scan_rit.page_snippets(text)
        self.assertIn("high school students", snips["high_school"])
        self.assertIn("16 years old", snips["age_rule"])
        self.assertLessEqual(len(snips["high_school"]), 200)
        self.assertEqual(scan_rit.page_snippets("Nothing relevant on this page."), {})

    def test_status_wording_is_found_and_quoted(self):
        for open_text in ("International students are welcome to apply.", "Open regardless of citizenship.",
                          "Students on an F-1 visa may apply.", "Non-U.S. citizens are eligible."):
            self.assertTrue(scan_rit.page_words(open_text, 2026)["international"], open_text)
        self.assertFalse(scan_rit.page_words("International travel is not covered.", 2026)["international"])
        text = ("Menu. " * 30) + "Applicants must be U.S. citizens or permanent residents. International students may apply to the other track. " + ("Footer. " * 30)
        snips = scan_rit.page_snippets(text)
        self.assertIn("permanent residents", snips["citizenship"])
        self.assertIn("International students may apply", snips["international"])

    def test_hidden_comment_text_is_not_quoted(self):
        page = "<p>Open to college students.</p><!-- The program runs June 23 (high school) --><p>Apply now.</p>"
        self.assertEqual(scan_rit.page_snippets(scan_rit.visible_text(page)), {})
        self.assertNotIn("June 23", scan_rit.visible_text(page))

    def test_summary_counts(self):
        for e, status in zip(self.entries, ("ok", "gone", "ok")):
            e["link"] = {"status": status, "code": 200, "words": {"high_school": status == "ok"} if status == "ok" else None}
        s = scan_rit.summarise(self.entries)
        self.assertEqual(s["entries"], 3)
        self.assertEqual(s["links"], {"ok": 2, "gone": 1})
        self.assertEqual(s["pages_read"], 2)
        self.assertEqual(s["pages_mentioning"]["high_school"], 2)
        self.assertEqual(s["by_state"]["not stated"], 1)

    def test_only_public_web_addresses_are_visited(self):
        ok = scan_rit.is_public_url
        self.assertTrue(ok("http://93.184.216.34/page"))
        self.assertTrue(ok("https://8.8.8.8/"))
        for bad in ("http://127.0.0.1:8090/", "http://localhost/", "http://192.168.1.10/admin", "http://10.0.0.5/",
                    "http://169.254.169.254/latest/meta-data", "http://[::1]/", "ftp://93.184.216.34/x",
                    "file:///etc/passwd", "javascript:alert(1)", "http:///nohost", "", None):
            self.assertFalse(ok(bad), bad)

    def test_a_link_to_a_private_address_is_never_opened(self):
        r = scan_rit.check_link("http://127.0.0.1:9/never", 2026)
        self.assertEqual(r, {"status": "skipped", "code": None, "words": None})

    def test_a_failed_write_leaves_no_stray_file(self):
        import tempfile
        d = tempfile.mkdtemp(prefix="scan-test-")
        with self.assertRaises(TypeError):
            scan_rit._write_json(os.path.join(d, "out.json"), {"bad": object()})
        self.assertEqual(os.listdir(d), [])

    def test_section_is_cut_between_its_anchor_and_the_next(self):
        page = ('<a name="AZ"></a>Arizona <p><b><a href="http://az.example/">AZ Org</a></b>, Tucson, AZ - <a href="http://az.example/c">co-op</a> (2020) x<br>'
                '<a name="CA"></a>California <p><b><a href="http://ca.example/">Arthritis Foundation (California)</a></b> - <a href="http://ca.example/c">co-op</a> (2020) Summer Science Internship<br>'
                '<b><a href="http://s.example/">Stanford University</a></b>, Stanford, CA - <a href="http://s.example/c">co-op</a> (2019) y<br>'
                '<A NAME="carribean"></a>Caribbean <p><b><a href="http://c.example/">C Org</a></b>, Nassau - <a href="http://c.example/c">co-op</a> (2020) z<br>')
        part = scan_rit.extract_section(page, "CA")
        entries = scan_rit.parse_entries(part, default_state="CA")
        self.assertEqual([e["org"] for e in entries], ["Arthritis Foundation (California)", "Stanford University"])
        self.assertEqual([e["state"] for e in entries], ["CA", "CA"])
        self.assertIsNone(scan_rit.extract_section(page, "TX"))

    def test_region_comes_from_the_city(self):
        r = scan_rit.region_of
        self.assertEqual(r("Stanford", "CA"), "Bay Area")
        self.assertEqual(r("South San Francisco", "CA"), "Bay Area")
        self.assertEqual(r("Davis", "CA"), "Sacramento and Davis")
        self.assertEqual(r("Santa Cruz", "CA"), "Santa Cruz and Monterey")
        self.assertEqual(r("La Jolla", "CA"), "Southern California")
        self.assertEqual(r("", "CA"), "California, place not stated")
        self.assertEqual(r("Fresno", "CA"), "Other California")
        self.assertEqual(r("Boston", "MA"), "")

    def test_bad_section_name_is_refused(self):
        self.assertEqual(scan_rit.main(["cstate1", "--section", "C A;", "--no-check"]), 2)

    def test_every_entry_gets_a_stable_id_the_api_accepts(self):
        import re
        doc = {"slug": "cstate1-ca", "entries": [{"org": "Stanford University", "url": "http://s.example/c"}, {"org": "UCSF", "url": "http://u.example/"}]}
        scan_rit.add_ids(doc)
        ids = [e["id"] for e in doc["entries"]]
        self.assertEqual(len(set(ids)), 2)
        for i in ids:
            self.assertRegex("lst:" + i, r"^(lst):[a-z0-9][a-z0-9-]{1,60}$")
        again = {"slug": "cstate1-ca", "entries": [{"org": "stanford university", "url": "HTTP://S.EXAMPLE/c"}]}
        scan_rit.add_ids(again)
        self.assertEqual(again["entries"][0]["id"], ids[0])   # same programme, same id, so a saved choice survives a rescan

    def test_summary_counts_sections_when_present(self):
        es = [{"org": "A", "state": "CA", "section": "Labs", "listed_year": None, "link": {"status": "ok", "words": {}}},
              {"org": "B", "state": "CA", "section": "Labs", "listed_year": None, "link": {"status": "gone", "words": None}},
              {"org": "C", "state": "CA", "section": "Zoos", "listed_year": None, "link": {"status": "ok", "words": {}}}]
        s = scan_rit.summarise(es)
        self.assertEqual(s["by_section"], {"Labs": 2, "Zoos": 1})

    def test_bad_page_name_is_refused(self):
        self.assertEqual(scan_rit.main(["../etc/passwd", "--no-check"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
