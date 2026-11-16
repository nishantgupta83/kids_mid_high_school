#!/usr/bin/env python3
"""Run: /usr/bin/python3 /Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school/roadmap/tests/test_roadmap.py"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROADMAP = "/Users/nishantgupta/Documents/nishant_projects/kids_mid_high_school/roadmap"
REPO = os.path.dirname(ROADMAP)
sys.path.insert(0, ROADMAP)

import push  # noqa: E402
import validate  # noqa: E402

REAL = os.path.join(ROADMAP, "data")
APPS = os.path.join(REPO, "data", "summer_apps.json")


@unittest.skipUnless(os.path.isdir(REAL), "roadmap/data is local-only (gitignored); these tests run on the Mac")
class Sandbox(unittest.TestCase):
    """Each test edits a throwaway copy of the real data, never the real files."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="roadmap-test-")
        self.data = os.path.join(self.tmp, "data")
        shutil.copytree(REAL, self.data)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def edit(self, name, fn):
        path = os.path.join(self.data, name)
        with open(path) as f:
            doc = json.load(f)
        fn(doc)
        with open(path, "w") as f:
            json.dump(doc, f)


class ValidateTests(Sandbox):
    def test_real_data_is_clean(self):
        self.assertEqual(validate.validate(REAL), [])

    def test_email_address_is_refused(self):
        self.edit("start.json", lambda d: d["flags"].append({"id": "x-flag", "text": "write to someone@example.org"}))
        self.assertTrue(any("email" in e for e in validate.validate(self.data)))

    def test_family_last_name_is_refused(self):
        self.edit("start.json", lambda d: d["flags"].append({"id": "x-flag", "text": "the Gupta family"}))
        self.assertTrue(any("last name" in e for e in validate.validate(self.data)))

    def test_phone_number_is_refused(self):
        self.edit("start.json", lambda d: d["flags"].append({"id": "x-flag", "text": "call 925-555-0100"}))
        self.assertTrue(any("phone" in e for e in validate.validate(self.data)))

    def test_duplicate_id_is_refused(self):
        self.edit("milestones.json", lambda d: d["milestones"].append(dict(d["milestones"][0])))
        self.assertTrue(any("duplicate id" in e for e in validate.validate(self.data)))

    def test_bad_date_is_refused(self):
        self.edit("milestones.json", lambda d: d["milestones"][0].update(date="Dec 2026"))
        self.assertTrue(any("date" in e for e in validate.validate(self.data)))

    def test_exact_must_be_a_boolean(self):
        self.edit("milestones.json", lambda d: d["milestones"][0].update(exact="yes"))
        self.assertTrue(any("exact" in e for e in validate.validate(self.data)))

    def test_non_http_link_is_refused(self):
        self.edit("source_docs.json", lambda d: d["sources"][0].update(url="javascript:alert(1)"))
        self.assertTrue(any("url" in e for e in validate.validate(self.data)))

    def test_missing_file_is_refused(self):
        os.remove(os.path.join(self.data, "courses.json"))
        self.assertTrue(any("courses.json" in e for e in validate.validate(self.data)))

    def test_broken_json_is_reported_not_raised(self):
        with open(os.path.join(self.data, "summers.json"), "w") as f:
            f.write("{not json")
        self.assertTrue(any("summers.json" in e for e in validate.validate(self.data)))

    def test_commitment_blocks_must_be_real_times_or_hours(self):
        self.edit("courses.json", lambda d: d["commitments"][0]["blocks"][0].update(start="evening"))
        self.assertTrue(any("commitments" in e for e in validate.validate(self.data)))

    def test_commitment_hours_must_be_a_positive_number(self):
        def bad(d):
            d["commitments"][1]["blocks"][0] = {"day": 2, "hours": 0}
        self.edit("courses.json", bad)
        self.assertTrue(any("commitments" in e for e in validate.validate(self.data)))

    def test_commitment_season_flag_is_checked(self):
        self.edit("courses.json", lambda d: d["commitments"][0].update(when="sometimes"))
        self.assertTrue(any("commitments" in e for e in validate.validate(self.data)))

    def test_last_name_lint_ignores_case(self):
        self.edit("start.json", lambda d: d["flags"].append({"id": "x-flag", "text": "the gupta family"}))
        self.assertTrue(any("last name" in e for e in validate.validate(self.data)))


class MoneyTests(Sandbox):
    def test_an_award_must_say_how_sure_we_are(self):
        self.edit("money.json", lambda d: d["awards"][1].update(confidence="definitely"))
        self.assertTrue(any("confidence" in e for e in validate.validate(self.data)))

    def test_a_confirmed_award_must_carry_its_source_link(self):
        def strip(d):
            row = next(a for a in d["awards"] if a["confidence"] == "confirmed")
            row.pop("url")
        self.edit("money.json", strip)
        self.assertTrue(any("confirmed" in e and "url" in e for e in validate.validate(self.data)))

    def test_a_confirmed_point_must_carry_its_source_link(self):
        def strip(d):
            row = next(p for p in d["points"] if p["confidence"] == "confirmed")
            row.pop("url")
        self.edit("money.json", strip)
        self.assertTrue(any("confirmed" in e and "url" in e for e in validate.validate(self.data)))

    def test_award_kind_is_checked(self):
        self.edit("money.json", lambda d: d["awards"][0].update(kind="free money"))
        self.assertTrue(any("kind" in e for e in validate.validate(self.data)))

    def test_checked_on_must_be_a_date(self):
        self.edit("money.json", lambda d: d.update(checked_on="last week"))
        self.assertTrue(any("checked_on" in e for e in validate.validate(self.data)))

    def test_money_travels_in_the_content(self):
        content = push.build_content(REAL, APPS)
        self.assertGreaterEqual(len(content["money"]["awards"]), 10)
        self.assertTrue(content["money"]["points"])


class ResearchFileTests(Sandbox):
    """options.json, status.json and community.json share one rule: every researched
    statement says how far it was confirmed, and 'confirmed' needs a link the parent can open."""

    def test_confirmed_route_fact_needs_a_link(self):
        def strip(d):
            fact = next(f for r in d["routes"] for f in r["facts"] if f["confidence"] == "confirmed")
            fact.pop("url")
        self.edit("options.json", strip)
        self.assertTrue(any("options.json" in e and "url" in e for e in validate.validate(self.data)))

    def test_route_fact_confidence_is_checked(self):
        self.edit("options.json", lambda d: d["routes"][0]["facts"][0].update(confidence="sure"))
        self.assertTrue(any("options.json" in e and "confidence" in e for e in validate.validate(self.data)))

    def test_confirmed_status_fact_needs_a_link(self):
        def strip(d):
            next(f for f in d["facts"] if f["confidence"] == "confirmed").pop("url")
        self.edit("status.json", strip)
        self.assertTrue(any("status.json" in e and "url" in e for e in validate.validate(self.data)))

    def test_bulletin_dates_must_be_real_dates(self):
        self.edit("status.json", lambda d: d["bulletin"]["rows"][0].update(final_action="Nov 2013"))
        self.assertTrue(any("status.json" in e and "final_action" in e for e in validate.validate(self.data)))

    def test_questions_say_who_they_are_for(self):
        self.edit("status.json", lambda d: d["questions"][0].update(ask="someone"))
        self.assertTrue(any("status.json" in e and "ask" in e for e in validate.validate(self.data)))

    def test_family_pattern_needs_a_source(self):
        self.edit("community.json", lambda d: d["patterns"][0].update(sources=[]))
        self.assertTrue(any("community.json" in e and "source" in e for e in validate.validate(self.data)))

    def test_family_pattern_source_must_be_http(self):
        self.edit("community.json", lambda d: d["patterns"][0]["sources"][0].update(url="ftp://x"))
        self.assertTrue(any("community.json" in e and "url" in e for e in validate.validate(self.data)))

    def test_no_family_category_or_date_in_committed_data(self):
        # The family's own petition category and priority date live in the browser only.
        import re
        sys.path.insert(0, os.path.join(ROADMAP, "lists"))
        import private_terms
        terms = private_terms.load()["never_in_data"]
        self.assertTrue(terms, "private terms file is missing or has no never_in_data entries")
        for name in os.listdir(REAL):
            text = open(os.path.join(REAL, name)).read()
            self.assertIsNone(re.search(r"priority date (is|of|=)", text, re.I), name)
            for t in terms:
                self.assertIsNone(re.search(t, text, re.I), name)

    def test_research_travels_in_the_content(self):
        content = push.build_content(REAL, APPS)
        self.assertGreaterEqual(len(content["options"]["routes"]), 5)
        self.assertTrue(content["status"]["questions"])
        self.assertTrue(content["community"]["patterns"])


class BuildContentTests(Sandbox):
    def test_every_application_is_carried(self):
        with open(APPS) as f:
            expected = [a["id"] for a in json.load(f)["applications"]]
        content = push.build_content(REAL, APPS)
        self.assertEqual([a["id"] for a in content["applications"]], expected)
        self.assertEqual(len(expected), 24)
        for key in ("start", "courses", "summers", "milestones", "sources", "generated"):
            self.assertIn(key, content)

    def test_missing_applications_file_degrades_never_raises(self):
        content = push.build_content(REAL, os.path.join(self.tmp, "nope.json"))
        self.assertEqual(content["applications"], [])
        self.assertTrue(content["applications_note"])

    def test_malformed_applications_file_degrades(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w") as f:
            f.write('{"applications": "not a list"}')
        content = push.build_content(REAL, bad)
        self.assertEqual(content["applications"], [])

    def test_only_known_application_fields_travel(self):
        apps = os.path.join(self.tmp, "apps.json")
        with open(apps, "w") as f:
            json.dump({"applications": [{"id": "a-1", "title": "T", "secret": "x", "deadline": "2027-01-01"}]}, f)
        content = push.build_content(REAL, apps)
        self.assertNotIn("secret", content["applications"][0])

    def test_content_fits_the_store(self):
        size = len(json.dumps(push.build_content(REAL, APPS)))
        self.assertLess(size, push.MAX_CONTENT_BYTES)

    def test_push_refuses_invalid_data(self):
        self.edit("start.json", lambda d: d["flags"].append({"id": "x-flag", "text": "someone@example.org"}))
        rc = push.main(["--dry-run", "--data-dir", self.data])
        self.assertEqual(rc, 2)

    def test_dry_run_is_clean_on_real_data(self):
        self.assertEqual(push.main(["--dry-run"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
