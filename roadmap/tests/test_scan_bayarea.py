#!/usr/bin/env python3
"""Run: /usr/bin/python3 /Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school/roadmap/tests/test_scan_bayarea.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lists"))
import scan_bayarea  # noqa: E402

PAGE = """<html><body><header><a href="https://x.example/nav">Nav</a></header><main>
<h1>Program listings</h1><p>Intro text with <a href="https://intro.example/">a link</a>.</p>
<h2>Use the links below to jump to a section:</h2><ul><li><a href="#Museums">Museums</a></li></ul>
<h3 id="Museums">Museums and Science Centers</h3>
<ul><li><strong><a href="https://ex.example/hs">High School Explainers</a></strong>&nbsp;at the&nbsp;<a href="http://ex.example/">Exploratorium</a></li></ul>
<h3 id="Colleges">Colleges and Universities</h3><h4>University of California, Berkeley</h4>
<ul><li><a href="https://cep.berkeley.edu/pre-college-trio">Pre-College TRIO Programs</a></li></ul>
<h4>&nbsp;Stanford University</h4>
<ul><li><a href="https://med.stanford.edu/cssec.html">Surgical Skills Summer Internship</a></li><li><a href="javascript:void(0)">Bad</a></li></ul>
<h3 id="Labs">Laboratories and Other Research Facilities</h3>
<ul><li><a href="https://www.jbei.org/iclem">iCLEM</a> at the <a href="https://www.jbei.org/">Joint BioEnergy Institute</a> \u2013 Note: open only to students in Alameda, Contra Costa and San Francisco counties.</li></ul>
<h3 id="jobs">Resources for Exploring and Finding Jobs</h3><ul><li><a href="https://www.careeronestop.org/">CareerOneStop</a></li></ul>
<h3 id="out_of_state">Out-of-state Programs</h3><ul><li><a href="https://mites.mit.edu/">MITES</a></li></ul>
</main><footer><a href="https://x.example/foot">Footer</a></footer></body></html>"""


class BatsTests(unittest.TestCase):
    def setUp(self):
        self.entries = scan_bayarea.parse_bats(PAGE)

    def test_takes_program_lines_under_their_section_and_group(self):
        self.assertEqual([e["org"] for e in self.entries],
                         ["High School Explainers at the Exploratorium", "Pre-College TRIO Programs",
                          "Surgical Skills Summer Internship", "iCLEM at the Joint BioEnergy Institute"])
        self.assertEqual([e["section"] for e in self.entries],
                         ["Museums and Science Centers", "Colleges and Universities", "Colleges and Universities",
                          "Laboratories and Other Research Facilities"])
        self.assertEqual(self.entries[1]["unit"], "University of California, Berkeley")
        self.assertEqual(self.entries[2]["unit"], "Stanford University")

    def test_uses_the_first_program_link_and_keeps_the_note(self):
        iclem = self.entries[3]
        self.assertEqual(iclem["url"], "https://www.jbei.org/iclem")
        self.assertIn("Alameda, Contra Costa and San Francisco counties", iclem["desc"])

    def test_skips_intro_jump_list_job_resources_out_of_state_and_bad_links(self):
        urls = [e["url"] for e in self.entries]
        for skipped in ("https://intro.example/", "https://www.careeronestop.org/", "https://mites.mit.edu/", "javascript:void(0)",
                        "https://x.example/nav", "https://x.example/foot"):
            self.assertNotIn(skipped, urls)

    def test_every_entry_is_bay_area_and_says_where_it_came_from(self):
        for e in self.entries:
            self.assertEqual((e["state"], e["region"]), ("CA", "Bay Area"))
            self.assertEqual(e["source"], scan_bayarea.BATS_SOURCE)


NESTED = """<main><h3>Colleges and Universities</h3><h4>UCSF</h4><ul>
<li>UCSF's <a href="https://sep.ucsf.edu/hs/">Science and Health Education Partnership (SEP)</a> offers three programs:
  <ul><li><a href="https://sep.ucsf.edu/hip/">High School Intern Program (HIP)</a></li>
      <li><a href="https://sep.ucsf.edu/twc/">Teen Wellness Connection (TWC)</a></li></ul></li>
<li>Teen Programs at the <a href="http://www.oaklandzoo.org/">Oakland Zoo</a>: <a href="https://www.oaklandzoo.org/teen-summer-internships">Teen Summer Internships</a></li>
</ul></main>"""


class NestingAndLinkTests(unittest.TestCase):
    def setUp(self):
        self.rows = scan_bayarea.parse_bats(NESTED)

    def test_a_parent_line_with_nested_items_is_kept_as_well_as_its_children(self):
        urls = [e["url"] for e in self.rows]
        self.assertIn("https://sep.ucsf.edu/hs/", urls)
        self.assertIn("https://sep.ucsf.edu/hip/", urls)
        self.assertIn("https://sep.ucsf.edu/twc/", urls)
        parent = next(e for e in self.rows if e["url"] == "https://sep.ucsf.edu/hs/")
        self.assertNotIn("High School Intern Program", parent["org"])   # children are not glued onto the parent

    def test_a_program_page_is_preferred_over_a_site_home_page(self):
        zoo = next(e for e in self.rows if "Oakland Zoo" in e["org"])
        self.assertEqual(zoo["url"], "https://www.oaklandzoo.org/teen-summer-internships")


class CarryOverTests(unittest.TestCase):
    def test_tags_from_the_previous_scan_are_kept_by_id_or_by_name(self):
        old = {"entries": [{"id": "x-1", "org": "Lab A", "section": "Labs", "audience": {"tag": "high_school"}},
                           {"id": "x-2", "org": "Zoo B", "section": "Zoos", "audience": {"tag": "college"}}]}
        new = [{"id": "x-1", "org": "Lab A", "section": "Labs"},
               {"id": "x-9", "org": "Zoo B", "section": "Zoos"},       # its link changed, so its id changed
               {"id": "x-3", "org": "New C", "section": "Labs"}]
        scan_bayarea.scan_rit.carry_over(old, new)
        self.assertEqual([e.get("audience", {}).get("tag") for e in new], ["high_school", "college", None])

    def test_a_name_match_on_a_different_site_or_shared_by_two_new_rows_does_not_inherit(self):
        old = {"entries": [{"id": "x-1", "org": "UC Berkeley", "section": None, "url": "https://reu.berkeley.edu/a",
                            "audience": {"tag": "college"}}]}
        other_site = [{"id": "x-7", "org": "UC Berkeley", "section": None, "url": "https://camp.example.org/"}]
        scan_bayarea.scan_rit.carry_over(old, other_site)
        self.assertNotIn("audience", other_site[0])
        two_new = [{"id": "x-8", "org": "UC Berkeley", "section": None, "url": "https://reu.berkeley.edu/b"},
                   {"id": "x-9", "org": "UC Berkeley", "section": None, "url": "https://reu.berkeley.edu/c"}]
        scan_bayarea.scan_rit.carry_over(old, two_new)
        self.assertEqual([("audience" in e) for e in two_new], [False, False])


class SeedTests(unittest.TestCase):
    def test_seed_rows_are_complete_and_http(self):
        rows = scan_bayarea.seed_entries()
        self.assertGreaterEqual(len(rows), 10)
        for e in rows:
            for f in ("org", "url", "section", "source", "desc", "region", "state"):
                self.assertTrue(isinstance(e.get(f), str) and e[f], (e.get("org"), f))
            self.assertRegex(e["url"], r"^https?://")

    def test_merge_drops_a_program_already_listed(self):
        a = [{"org": "Science Internship Program (SIP)", "url": "https://sip.ucsc.edu/"}]
        b = [{"org": "UCSC SIP", "url": "https://SIP.ucsc.edu"}]
        self.assertEqual(len(scan_bayarea.merge(a, b)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
