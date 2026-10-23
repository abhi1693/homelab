"""Prevent unreviewed rolling interpreter changes for retained state backups."""
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[6]
SPEC = importlib.util.spec_from_file_location("policy", ROOT / "scripts/check-renovate-policy.py")
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
CONFIG = (ROOT / POLICY.CONFIG_PATH).read_text()


class HelperImagePolicyTests(unittest.TestCase):
    def test_current_manual_policy(self):
        self.assertEqual(POLICY.check_backup_helper_policy(CONFIG), [])

    def test_automatic_or_broader_helper_rule_rejected(self):
        rule = next(rule for rule in re.findall(r"\{[^{}]*\}", CONFIG)
                    if '"cgr.dev/chainguard/python"' in rule)
        for old, new in [("enabled: false", "enabled: true"),
                         ('["cgr.dev/chainguard/python"]', '["cgr.dev/chainguard/python", "another/package"]'),
                         ('["docker"]', '["github-releases"]')]:
            with self.subTest(change=new):
                self.assertTrue(POLICY.check_backup_helper_policy(CONFIG.replace(rule, rule.replace(old, new))))

    def test_later_rule_cannot_override_manual_boundary(self):
        changed = CONFIG.replace("\n      ],\n      lockFileMaintenance:",
                                 ',\n        { matchDatasources: ["docker"], enabled: true }\n      ],\n      lockFileMaintenance:')
        self.assertTrue(POLICY.check_backup_helper_policy(changed))

    def test_all_five_media_python_consumers_have_exact_docker_metadata(self):
        locations = ["media-qbittorrent/smart-queues-controller.yaml",
                     "media-ryokan/deployment.yaml",
                     "media-state-backups/storage-validation-job.yaml"]
        count = 0
        for location in locations:
            lines = (ROOT / "kubernetes/projects/entertainment/apps" / location).read_text().splitlines()
            for index, line in enumerate(lines):
                if re.match(r"\s*image: cgr\.dev/chainguard/python:", line):
                    self.assertEqual(lines[index - 1].strip(),
                                     "# renovate: datasource=docker depName=cgr.dev/chainguard/python")
                    count += 1
        self.assertEqual(count, 5)
