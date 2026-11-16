#!/usr/bin/env python3
"""Run: /usr/bin/python3 /Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school/roadmap/tests/test_apply_audience.py"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lists"))
import apply_audience  # noqa: E402
import private_terms  # noqa: E402

DOC = {"slug": "x", "summary": {"entries": 3}, "entries": [
    {"id": "x-1", "org": "A", "url": "https://a.example/"},
    {"id": "x-2", "org": "B", "url": "https://b.example/"},
    {"id": "x-3", "org": "C", "url": "https://c.example/"}]}

GOOD = {"id": "x-1", "tag": "high_school", "quote": "Open to high school students.", "evidence_url": "https://a.example/elig",
        "min_age": "16", "citizenship": None, "grades": "10-12", "cost_or_pay": None, "dates": "Applications due Feb 1, 2027",
        "pages_read": 2, "notes": None}


class ApplyTests(unittest.TestCase):
    def test_attaches_tags_and_never_removes_entries(self):
        doc = copy.deepcopy(DOC)
        n, problems = apply_audience.apply(doc, [GOOD, dict(GOOD, id="x-2", tag="graduate", quote="PhD students only")], "2026-11-11")
        self.assertEqual(n, 2)
        self.assertEqual(problems, [])
        self.assertEqual([e["id"] for e in doc["entries"]], ["x-1", "x-2", "x-3"])
        self.assertEqual(doc["entries"][0]["audience"]["tag"], "high_school")
        self.assertEqual(doc["entries"][0]["audience"]["checked_on"], "2026-11-11")
        self.assertNotIn("audience", doc["entries"][2])
        self.assertEqual(doc["summary"]["by_audience"], {"high_school": 1, "graduate": 1, "not checked": 1})

    def test_bad_rows_are_reported_not_applied(self):
        doc = copy.deepcopy(DOC)
        rows = [dict(GOOD, tag="maybe"), dict(GOOD, id="nope"), dict(GOOD, id="x-2", evidence_url="javascript:alert(1)"),
                dict(GOOD, id="x-3", quote=123), "not an object"]
        n, problems = apply_audience.apply(doc, rows, "2026-11-11")
        self.assertEqual(n, 0)
        self.assertEqual(len(problems), 5)
        self.assertTrue(all("audience" not in e for e in doc["entries"]))

    def test_long_text_is_cut_and_unknown_keys_dropped(self):
        doc = copy.deepcopy(DOC)
        apply_audience.apply(doc, [dict(GOOD, quote="q" * 900, notes="n" * 900, secret="x")], "2026-11-11")
        a = doc["entries"][0]["audience"]
        self.assertLessEqual(len(a["quote"]), 300)
        self.assertLessEqual(len(a["notes"]), 300)
        self.assertNotIn("secret", a)

    def test_a_later_run_replaces_an_earlier_tag(self):
        doc = copy.deepcopy(DOC)
        apply_audience.apply(doc, [GOOD], "2026-11-11")
        apply_audience.apply(doc, [dict(GOOD, tag="unclear", quote="")], "2026-11-12")
        self.assertEqual(doc["entries"][0]["audience"]["tag"], "unclear")
        self.assertEqual(doc["entries"][0]["audience"]["checked_on"], "2026-11-12")


class PrivacyTests(unittest.TestCase):
    """The lists are public files. The checkers were told her birthday and visa so they could
    judge fit; that reasoning must not be copied into a public file. The real family terms
    live in the gitignored private terms file, so these tests use made-up ones."""

    FAKE = {"scrub_notes": ["march 3", "visa type x"], "scrub_fields": ["visa type x"]}

    def setUp(self):
        apply_audience.configure(self.FAKE)

    def tearDown(self):
        apply_audience.configure(private_terms.load())

    def test_sentences_about_the_student_are_removed_from_notes(self):
        doc = copy.deepcopy(DOC)
        apply_audience.apply(doc, [dict(GOOD, notes="Requires full-time enrollment. Min age 16 would be met after March 3, 2027. "
                                                     "A student on visa type X may not qualify. Dates are from 2026.")], "2026-11-11")
        notes = doc["entries"][0]["audience"]["notes"]
        self.assertEqual(notes, "Requires full-time enrollment. Dates are from 2026.")

    def test_private_terms_alone_drop_a_sentence_or_field(self):
        doc = copy.deepcopy(DOC)
        apply_audience.apply(doc, [dict(GOOD, notes="Opens after March 3. Runs in July.",
                                        citizenship="Visa type X holders are excluded")], "2026-11-11")
        a = doc["entries"][0]["audience"]
        self.assertEqual(a.get("notes"), "Runs in July.")
        self.assertNotIn("citizenship", a)

    def test_program_dates_in_other_fields_are_kept(self):
        doc = copy.deepcopy(DOC)
        apply_audience.apply(doc, [dict(GOOD, dates="program March 3 - August 14, 2027")], "2026-11-11")
        self.assertEqual(doc["entries"][0]["audience"]["dates"], "program March 3 - August 14, 2027")

    def test_wider_personal_wording_is_dropped_from_every_text_field(self):
        doc = copy.deepcopy(DOC)
        apply_audience.apply(doc, [dict(GOOD, notes="A 15-year-old would be ineligible. Runs in July.",
                                        grades="Ridhi is in grade 10", dates="Her birthday is in June")], "2026-11-11")
        a = doc["entries"][0]["audience"]
        self.assertEqual(a.get("notes"), "Runs in July.")
        self.assertNotIn("grades", a)
        self.assertNotIn("dates", a)

    def test_scrub_cleans_an_already_published_list(self):
        doc = {"entries": [{"id": "a", "audience": {"tag": "unclear", "notes": "Opens to applicants after March 3 only."}}]}
        apply_audience.scrub_doc(doc)
        self.assertNotIn("notes", doc["entries"][0]["audience"])


class PublicFilesTests(unittest.TestCase):
    def test_no_family_details_in_anything_the_site_serves_without_the_code(self):
        import re
        public = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "dashboard", "public")
        # Generic words here; the family's own (birthday, visa, priority date) come from the
        # gitignored private terms file and are checked only where that file exists.
        bad = re.compile("|".join([r"turns? 16|turning 16|her birthday|gupta"] + private_terms.load()["never_public"]), re.I)
        for root, _, files in os.walk(public):
            for name in files:
                if name.endswith((".json", ".html", ".js")):
                    text = open(os.path.join(root, name), encoding="utf-8").read()
                    m = bad.search(text)
                    self.assertIsNone(m, f"{name}: {m.group(0) if m else ''}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
