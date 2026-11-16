#!/usr/bin/env python3
"""Run: /usr/bin/python3 /Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school/roadmap/tests/test_verify_quotes.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lists"))
import verify_quotes  # noqa: E402


class MatchTests(unittest.TestCase):
    PAGE = "<html><body><h2>Eligibility</h2><p>The program is open to all high&nbsp;school students who are\n 16 years of age or older on June 1, 2026.</p><!-- hidden --></body></html>"

    def test_exact_words_match_despite_spacing_case_and_entities(self):
        self.assertTrue(verify_quotes.quote_on_page("open to all High School students who are 16 years of age", self.PAGE))

    def test_curly_quotes_dashes_and_ellipses_are_tolerated(self):
        page = "<p>Students must be “at least 16” – no exceptions. Apply by March 1.</p>"
        self.assertTrue(verify_quotes.quote_on_page('Students must be "at least 16" - no exceptions', page))
        self.assertTrue(verify_quotes.quote_on_page("Students must be ... no exceptions. Apply by March 1.", page))

    def test_a_paraphrase_does_not_match(self):
        self.assertFalse(verify_quotes.quote_on_page("High school students aged 16+ may apply", self.PAGE))

    def test_words_must_match_whole_words(self):
        page = "<p>Open to non-U.S. citizens. Programs for post high school students.</p>"
        self.assertFalse(verify_quotes.quote_on_page("U.S. citizens", page))
        self.assertFalse(verify_quotes.quote_on_page("for high school students", page))

    def test_short_parts_are_checked_and_order_matters(self):
        page = "<p>Applicants must be 16. US only. Apply by March 1.</p>"
        self.assertFalse(verify_quotes.quote_on_page("Applicants must be 16 ... no", page))
        self.assertTrue(verify_quotes.quote_on_page("Applicants must be 16 ... US only", page))
        self.assertFalse(verify_quotes.quote_on_page("Apply by March 1 ... Applicants must be 16", page))

    def test_hidden_comment_text_does_not_count(self):
        self.assertFalse(verify_quotes.quote_on_page("hidden", self.PAGE))


class RunTests(unittest.TestCase):
    def test_marks_each_tag_true_false_or_unknown(self):
        doc = {"entries": [
            {"id": "a", "audience": {"tag": "high_school", "quote": "open to all high school students", "evidence_url": "https://a.example/"}},
            {"id": "b", "audience": {"tag": "college", "quote": "undergraduates only", "evidence_url": "https://b.example/"}},
            {"id": "c", "audience": {"tag": "unclear", "quote": "anything", "evidence_url": "https://c.example/"}},
            {"id": "d", "audience": {"tag": "gone"}},
            {"id": "e"}]}
        pages = {"https://a.example/": MatchTests.PAGE, "https://b.example/": "<p>Open to graduate students.</p>"}
        counts = verify_quotes.verify(doc, fetch=lambda u: pages.get(u))
        marks = [e.get("audience", {}).get("quote_verified", "absent") for e in doc["entries"]]
        self.assertEqual(marks, [True, False, None, "absent", "absent"])
        self.assertEqual(counts, {"verified": 1, "not_found": 1, "page_not_loaded": 1})


class StatusRuleTests(unittest.TestCase):
    def test_the_status_rule_is_checked_word_for_word_too(self):
        page = "<p>Applicants must be U.S. citizens or lawful permanent residents (green card holders).</p><p>Only high school applicants will be accepted.</p>"
        doc = {"entries": [
            {"id": "a", "audience": {"tag": "high_school", "quote": "only high school applicants will be accepted",
                                     "citizenship": "U.S. citizens or lawful permanent residents", "evidence_url": "https://a.example/"}},
            {"id": "b", "audience": {"tag": "high_school", "quote": "only high school applicants will be accepted",
                                     "citizenship": "Not stated", "evidence_url": "https://a.example/"}}]}
        verify_quotes.verify(doc, fetch=lambda u: page)
        self.assertTrue(doc["entries"][0]["audience"]["citizenship_verified"])
        self.assertFalse(doc["entries"][1]["audience"]["citizenship_verified"])
        # a later run that cannot load the page must not leave an old 'true' behind
        verify_quotes.verify(doc, fetch=lambda u: None)
        self.assertNotIn("citizenship_verified", doc["entries"][0]["audience"])
        self.assertIsNone(doc["entries"][0]["audience"]["quote_verified"])


class FitQuoteTests(unittest.TestCase):
    def test_each_fit_quote_is_checked_on_its_page(self):
        page = "<p>Open to domestic and international students.</p><p>Participants receive a $5,000 stipend.</p>"
        doc = {"entries": [{"id": "a", "fit": {
            "noncitizen": "open", "noncitizen_quote": "Open to domestic and international students.",
            "who": "any_college", "who_quote": "Any college student may apply",
            "pay": "stipend", "pay_quote": "receive a $5,000 stipend", "work_auth": True, "work_auth_quote": "must hold a work permit",
            "evidence_url": "https://a.example/"}},
            {"id": "b", "fit": {"noncitizen": "not_stated", "evidence_url": "https://b.example/"}}]}
        counts = verify_quotes.verify_fit(doc, fetch=lambda u: page if u == "https://a.example/" else None)
        self.assertEqual(doc["entries"][0]["fit"]["verified"], {"noncitizen": True, "who": False, "pay": True, "work_auth": False})
        self.assertNotIn("verified", doc["entries"][1]["fit"])
        self.assertEqual(counts, {"verified": 2, "not_found": 2, "page_not_loaded": 0})
        # a later run that cannot load the page clears the old marks
        verify_quotes.verify_fit(doc, fetch=lambda u: None)
        self.assertNotIn("verified", doc["entries"][0]["fit"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
