"""Require Blog updates to follow published images rather than release events."""

import importlib.util
from pathlib import Path
import re
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[6]
SPEC = importlib.util.spec_from_file_location(
    "renovate_policy", ROOT / "scripts/check-renovate-policy.py"
)
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
CONFIG = (ROOT / POLICY.CONFIG_PATH).read_text()
BLOG = Path("kubernetes/projects/applications/apps/personal-blog/deployment.yaml")
PACKAGE = "ghcr.io/abhi1693/personal-blog"


class PublishedImagePolicyTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in POLICY.REGISTRY_TRACKED_IMAGES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text((ROOT / name).read_text())

    def check(self, config=CONFIG):
        return POLICY.check_registry_tracked_images(config, self.root)

    def test_actual_published_packages_are_enabled(self):
        self.assertEqual(self.check(), [])

    def test_blog_source_release_marker_is_rejected(self):
        path = self.root / BLOG
        path.write_text(path.read_text().replace(
            "datasource=docker depName=" + PACKAGE,
            "datasource=github-releases depName=abhi1693/personal-blog",
        ))
        self.assertIn("personal-blog must track published Docker images and digests", self.check())

    def test_blog_cannot_follow_another_runtime_package(self):
        path = self.root / BLOG
        path.write_text(path.read_text().replace(
            "datasource=docker depName=" + PACKAGE,
            "datasource=docker depName=ghcr.io/abhi1693/portfolio",
        ))
        self.assertTrue(self.check())

    def test_blog_enabled_registry_rule_cannot_be_removed(self):
        config = CONFIG.replace('            "' + PACKAGE + '",\n', "")
        self.assertNotEqual(config, CONFIG)
        self.assertIn("personal-blog Docker updates need an explicit enabled package rule", self.check(config))

    def test_reintroduced_source_release_enabler_is_rejected(self):
        config = CONFIG + '''\n{
          matchDatasources: ["github-releases"],
          matchPackageNames: ["abhi1693/personal-blog"],
          enabled: true
        }\n'''
        self.assertIn("personal-blog source release must not enable image updates", self.check(config))

    def test_existing_single_image_branch_policy_is_preserved(self):
        rule = next(block for block in re.findall(r"\{[^{}]*\}", CONFIG)
                    if '"' + PACKAGE + '"' in block)
        self.assertIn('matchDatasources: ["docker"]', rule)
        self.assertIn('automerge: true', rule)
        self.assertIn('automergeType: "branch"', rule)
        self.assertIn('platformAutomerge: false', rule)
        self.assertNotIn('automerge: false', rule)

    def test_credential_foundation_changes_run_both_ci_events(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/infrastructure-regressions.yml").read_text()
        )
        events = workflow.get("on", workflow.get(True))
        for event in ("pull_request", "push"):
            with self.subTest(event=event):
                self.assertTrue({
                    "kubernetes/projects/applications/apps/personal-blog/**",
                    "docs/runbooks/personal-blog-credential-cutover.md",
                }.issubset(events[event]["paths"]))


if __name__ == "__main__":
    unittest.main()
