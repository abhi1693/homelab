"""Keep License image publication independent of source release timing."""

import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest


APP = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[6]
SPEC = importlib.util.spec_from_file_location(
    "renovate_policy", ROOT / "scripts/check-renovate-policy.py"
)
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
CONFIG = (ROOT / POLICY.CONFIG_PATH).read_text()


class ImagePolicyTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.app = Path(temporary.name)
        for name in ["deployment.yaml", "migration-job.yaml"]:
            (self.app / name).write_text((APP / name).read_text())

    def check(self, config=CONFIG):
        return POLICY.check_license_image_policy(config, self.app)

    def test_actual_docker_metadata_and_reviewed_group(self):
        self.assertEqual(self.check(), [])

    def test_source_release_cannot_replace_migration_image_metadata(self):
        path = self.app / "migration-job.yaml"
        path.write_text(path.read_text().replace(
            "datasource=docker depName=ghcr.io/abhi1693/wardn-license-server-backend",
            "datasource=github-releases depName=abhi1693/wardn-license-server",
        ))
        self.assertTrue(self.check())

    def test_frontend_cannot_track_backend_package(self):
        path = self.app / "deployment.yaml"
        path.write_text(path.read_text().replace(
            "depName=ghcr.io/abhi1693/wardn-license-server-frontend",
            "depName=ghcr.io/abhi1693/wardn-license-server-backend",
        ))
        self.assertTrue(self.check())

    def test_incomplete_or_extra_package_set_rejected(self):
        rule = next(block for block in re.findall(r"\{[^{}]*\}", CONFIG)
                    if 'groupSlug: "wardn-license-server-images"' in block)
        selected = re.search(r"matchPackageNames:\s*(\[[^\]]*\])", rule)
        packages = json.loads(selected[1])
        for changed in [packages[:1], packages + ["unrelated/package"]]:
            changed_rule = rule.replace(selected[0], "matchPackageNames: " + json.dumps(changed))
            self.assertTrue(self.check(CONFIG.replace(rule, changed_rule)))

    def test_automerge_or_missing_digest_policy_rejected(self):
        rule = next(block for block in re.findall(r"\{[^{}]*\}", CONFIG)
                    if 'groupSlug: "wardn-license-server-images"' in block)
        for old, new in [("automerge: false", "automerge: true"),
                         ("pinDigests: true", "pinDigests: false"),
                         ('matchDatasources: ["docker"]', 'matchDatasources: ["github-releases"]')]:
            self.assertTrue(self.check(CONFIG.replace(rule, rule.replace(old, new))))

    def test_only_hub_and_license_are_removed_from_default_merge_checks(self):
        blocks = re.findall(r"\{[^{}]*\}", CONFIG)
        hub = next(block for block in blocks if 'groupSlug: "wardn-hub-images"' in block)
        license_rule = next(block for block in blocks if 'groupSlug: "wardn-license-server-images"' in block)
        self.assertEqual(POLICY.check_default_merge_policy(CONFIG, hub, license_rule), [])
        self.assertTrue(POLICY.check_default_merge_policy(CONFIG, hub))
        self.assertTrue(POLICY.check_default_merge_policy(
            CONFIG + '\n{\n  automerge: false\n}\n', hub, license_rule,
        ))
        self.assertTrue(POLICY.check_default_merge_policy(
            CONFIG.replace("automerge: true", "automerge: false", 1), hub, license_rule,
        ))


if __name__ == "__main__":
    unittest.main()
