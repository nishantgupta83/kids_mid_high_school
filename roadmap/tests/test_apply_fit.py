#!/usr/bin/env python3
"""Run: /usr/bin/python3 /Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school/roadmap/tests/test_apply_fit.py"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lists"))
import apply_fit  # noqa: E402

DOC = {"slug": "x", "summary": {"entries": 3}, "entries": [
    {"id": "x-1", "org": "A", "url": "https://a.example/", "audience": {"tag": "college"}},
    {"id": "x-2", "org": "B", "url": "https://b.example/"},
    {"id": "x-3", "org": "C", "url": "https://c.example/"}]}

GOOD = {"id": "x-1", "noncitizen": "open", "noncitizen_quote": "Open to domestic and international students.",
        "who": "any_college", "who_quote": "Students from any accredited college may apply.",
        "pay": "stipend", "pay_quote": "$5,000 stipend", "work_auth": False, "work_auth_quote": None,
        "evidence_url": "https://a.example/elig", "pages_read": 2, "notes": "Housing provided."}


class FitTests(unittest.TestCase):
    def test_attaches_fit_beside_the_audience_tag_and_never_removes_entries(self):
        doc = copy.deepcopy(DOC)
        n, problems = apply_fit.apply(doc, [GOOD, dict(GOOD, id="x-2", noncitizen="closed", who="own_students")], "2026-11-12")
        self.assertEqual((n, problems), (2, []))
        self.assertEqual([e["id"] for e in doc["entries"]], ["x-1", "x-2", "x-3"])
        fit = doc["entries"][0]["fit"]
        self.assertEqual((fit["noncitizen"], fit["who"], fit["pay"], fit["work_auth"]), ("open", "any_college", "stipend", False))
        self.assertEqual(fit["checked_on"], "2026-11-12")
        self.assertEqual(doc["entries"][0]["audience"], {"tag": "college"})   # the earlier tag is untouched
        self.assertNotIn("fit", doc["entries"][2])
        self.assertEqual(doc["summary"]["by_noncitizen"], {"closed": 1, "open": 1, "not checked": 1})

    def test_bad_rows_are_reported_not_applied(self):
        doc = copy.deepcopy(DOC)
        rows = [dict(GOOD, noncitizen="maybe"), dict(GOOD, who="anyone"), dict(GOOD, pay="lots"),
                dict(GOOD, id="nope"), dict(GOOD, evidence_url="javascript:alert(1)"), dict(GOOD, work_auth="yes"),
                dict(GOOD, noncitizen_quote=5), "not an object"]
        n, problems = apply_fit.apply(doc, rows, "2026-11-12")
        self.assertEqual(n, 0)
        self.assertEqual(len(problems), 8)
        self.assertTrue(all("fit" not in e for e in doc["entries"]))

    def test_nothing_about_her_reaches_the_public_file(self):
        doc = copy.deepcopy(DOC)
        row = dict(GOOD, noncitizen_quote="She is on visa type X so she cannot apply.",
                   notes="Stipend is paid weekly. Her visa type X status would block this. Housing is provided.")
        apply_fit.apply(doc, [row], "2026-11-12")
        fit = doc["entries"][0]["fit"]
        self.assertNotIn("noncitizen_quote", fit)
        self.assertEqual(fit["notes"], "Stipend is paid weekly. Housing is provided.")

    def test_long_text_is_cut_and_spaces_collapsed(self):
        doc = copy.deepcopy(DOC)
        apply_fit.apply(doc, [dict(GOOD, pay_quote="paid   " * 100)], "2026-11-12")
        self.assertLessEqual(len(doc["entries"][0]["fit"]["pay_quote"]), 300)
        self.assertNotIn("  ", doc["entries"][0]["fit"]["pay_quote"])

    def test_a_result_file_that_is_not_a_list_is_an_error(self):
        import json, tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"rows": [GOOD]}, f)
        self.assertEqual(apply_fit.main([f.name]), 2)


class PublicFilesTests(unittest.TestCase):
    def test_no_published_list_mentions_the_family(self):
        import json, re
        out = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "dashboard", "public", "lists")
        import private_terms
        # Generic words here; the family's own come from the gitignored private terms file.
        bad = re.compile("|".join([r"\bridhi\b|\bpari\b|gupta|birthday|priority date|turns? 16|\bshe\b|\bher\b"]
                                  + private_terms.load()["never_public"]), re.I)
        for name in os.listdir(out):
            if name.endswith(".json"):
                text = open(os.path.join(out, name)).read()
                m = bad.search(text)
                self.assertIsNone(m, f"{name}: {text[max(0, m.start() - 60):m.end() + 60] if m else ''}")


if __name__ == "__main__":
    unittest.main()
