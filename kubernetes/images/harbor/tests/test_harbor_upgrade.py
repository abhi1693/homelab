"""Keep chart publication and complete ARM64 cohorts as independent gates."""

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("harbor_upgrade", ROOT / "scripts/check-harbor-upgrade.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class HarborUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.candidate = json.loads((ROOT / "kubernetes/images/harbor/upgrade-candidate.json").read_text())
        self.inspections = {entry["component"]: {"Architecture": "arm64", "Digest": entry["digest"]}
                            for entry in self.candidate["images"]}
        self.catalog = {"entries": {"harbor": [{"version": "1.20.0", "appVersion": "2.16.0"}]}}

    def test_published_matching_chart_and_full_cohort_pass(self):
        self.assertTrue(CHECK.evaluate(self.candidate, self.catalog, self.inspections)["ready"])

    def test_wrong_application_or_unreleased_chart_cannot_pass(self):
        for chart in ({"version": "1.19.4", "appVersion": "2.15.4"},
                      {"version": "1.20.0-dev", "appVersion": "2.16.0"}):
            with self.subTest(chart=chart):
                self.assertFalse(CHECK.evaluate(self.candidate, {"entries": {"harbor": [chart]}}, self.inspections)["ready"])

    def test_incomplete_cohort_wrong_architecture_and_digest_are_rejected(self):
        self.candidate["images"].pop()
        self.assertFalse(CHECK.evaluate(self.candidate, self.catalog, self.inspections)["ready"])
        self.setUp()
        self.inspections["harbor-core"]["Architecture"] = "amd64"
        self.assertFalse(CHECK.evaluate(self.candidate, self.catalog, self.inspections)["ready"])
        self.setUp()
        self.inspections["harbor-core"]["Digest"] = "sha256:" + "0" * 64
        self.assertFalse(CHECK.evaluate(self.candidate, self.catalog, self.inspections)["ready"])


if __name__ == "__main__":
    unittest.main()
