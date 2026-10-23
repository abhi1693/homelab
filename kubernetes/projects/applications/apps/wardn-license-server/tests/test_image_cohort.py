"""Reject partial License API/frontend/migration-hook image updates."""

import importlib.util
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


class ImageCohortTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.app = Path(temporary.name)
        self.digests = {"backend": "a" * 64, "frontend": "b" * 64}
        for name in POLICY.LICENSE_COHORT:
            source = (APP / name).read_text()
            source = re.sub(
                r"(image: registry\.home/ghcr\.io/abhi1693/wardn-license-server-"
                r"(backend|frontend)):([^\s\"']+)",
                lambda match: f"{match[1]}:0.1.2@sha256:{self.digests[match[2]]}",
                source,
            )
            (self.app / name).write_text(source)

    def change(self, name, old, new):
        path = self.app / name
        source = path.read_text()
        self.assertIn(old, source)
        path.write_text(source.replace(old, new, 1))

    def check(self):
        return POLICY.check_license_image_cohort(self.app)

    def test_complete_cohort_allows_distinct_component_digests(self):
        self.assertEqual(self.check(), [])

    def test_all_references_can_move_to_next_stable_version(self):
        for path in self.app.iterdir():
            path.write_text(path.read_text().replace(":0.1.2@", ":0.1.3@"))
        self.assertEqual(self.check(), [])

    def test_partial_api_publication_rejected(self):
        self.change("deployment.yaml", ":0.1.2@", ":0.1.3@")
        self.assertTrue(self.check())

    def test_stale_migration_hook_rejected(self):
        self.change("migration-job.yaml", ":0.1.2@", ":0.1.1@")
        self.assertTrue(self.check())

    def test_backend_api_and_hook_digest_must_match(self):
        self.change("migration-job.yaml", "sha256:" + "a" * 64, "sha256:" + "c" * 64)
        self.assertTrue(self.check())

    def test_missing_hook_digest_rejected(self):
        self.change("migration-job.yaml", "@sha256:" + "a" * 64, "")
        self.assertTrue(self.check())

    def test_unpinned_old_baseline_has_no_exception(self):
        for path in self.app.iterdir():
            path.write_text(re.sub(r":0\.1\.2@sha256:[a-f0-9]{64}", ":0.1.1", path.read_text()))
        self.assertTrue(self.check())

    def test_unstable_and_noncanonical_tags_rejected(self):
        path = self.app / "deployment.yaml"
        original = path.read_text()
        for tag in ["latest", "v0.1.2", "0.1.2-rc.1", "0.1.2+build.1", "00.1.2"]:
            with self.subTest(tag=tag):
                path.write_text(original.replace(":0.1.2@", ":" + tag + "@", 1))
                self.assertTrue(self.check())

    def test_noncanonical_registry_rejected(self):
        self.change("deployment.yaml", "image: registry.home/", "image: different.invalid/")
        self.assertTrue(self.check())

    def test_quoted_image_supported(self):
        path = self.app / "deployment.yaml"
        path.write_text(re.sub(r"(image: )(\S+)", r'\1"\2"', path.read_text()))
        self.assertEqual(self.check(), [])

    def test_unreviewed_additional_yaml_image_rejected(self):
        (self.app / "extra.yml").write_text(
            "spec:\n  containers:\n    - name: extra\n"
            "      # renovate: datasource=docker depName=ghcr.io/abhi1693/wardn-license-server-backend\n"
            '      image: "registry.home/ghcr.io/abhi1693/wardn-license-server-backend:'
            '0.1.2@sha256:' + "a" * 64 + '"\n'
        )
        self.assertTrue(self.check())

    def test_removed_migration_hook_rejected(self):
        (self.app / "migration-job.yaml").unlink()
        self.assertTrue(self.check())

    def test_swapped_api_and_frontend_images_rejected(self):
        path = self.app / "deployment.yaml"
        source = path.read_text().replace("- name: api\n", "- name: swap\n")
        source = source.replace("- name: frontend\n", "- name: api\n")
        path.write_text(source.replace("- name: swap\n", "- name: frontend\n"))
        self.assertTrue(self.check())

    def test_source_release_metadata_rejected(self):
        self.change("migration-job.yaml", "datasource=docker", "datasource=github-releases")
        self.assertTrue(self.check())


if __name__ == "__main__":
    unittest.main()
