"""Reject incomplete automated updates of the actual coupled Hub manifests."""

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
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Path(self.temp.name)
        self.digests = {
            "backend": "a" * 64,
            "frontend": "b" * 64,
            "codex-app-server": "c" * 64,
        }
        for name in POLICY.HUB_COHORT:
            source = (APP / name).read_text()
            source = re.sub(
                r"(image: registry\.home/ghcr\.io/abhi1693/wardn-hub-"
                r"(backend|frontend|codex-app-server)):([^\s]+)",
                lambda match: (
                    f"{match[1]}:0.2.182@sha256:{self.digests[match[2]]}"
                ),
                source,
            )
            (self.app / name).write_text(source)

    def change(self, name, old, new):
        path = self.app / name
        source = path.read_text()
        self.assertIn(old, source)
        path.write_text(source.replace(old, new, 1))

    def test_complete_cohort_accepts_independently_versioned_scoring(self):
        self.assertEqual(POLICY.check_hub_image_cohort(self.app), [])

    def test_new_tag_on_only_one_init_container_is_rejected(self):
        self.change("deployment-scoring.yaml", ":0.2.182@", ":0.2.183@")
        self.assertTrue(POLICY.check_hub_image_cohort(self.app))

    def test_missing_digest_on_paused_worker_is_rejected(self):
        self.change("deployment-worker.yaml", "@sha256:" + "a" * 64, "")
        self.assertTrue(POLICY.check_hub_image_cohort(self.app))

    def test_different_digest_for_same_component_is_rejected(self):
        self.change("next-builder-job.yaml", "sha256:" + "b" * 64,
                    "sha256:" + "d" * 64)
        self.assertTrue(POLICY.check_hub_image_cohort(self.app))

    def test_removing_hook_image_from_coverage_is_rejected(self):
        self.change("find-skills-refresh-job.yaml", "image: registry.home/",
                    "image: different-registry.invalid/")
        self.assertTrue(POLICY.check_hub_image_cohort(self.app))

    def test_source_release_metadata_cannot_replace_published_container_metadata(self):
        self.change("deployment-api.yaml", "datasource=docker",
                    "datasource=github-releases")
        self.assertTrue(POLICY.check_hub_image_cohort(self.app))

    def test_new_manifest_cannot_add_an_unreviewed_image_reference(self):
        (self.app / "extra-worker.yaml").write_text(
            "spec:\n  containers:\n    - name: extra\n"
            "      # renovate: datasource=docker depName=ghcr.io/abhi1693/wardn-hub-backend\n"
            "      image: registry.home/ghcr.io/abhi1693/wardn-hub-backend:"
            "0.2.183@sha256:" + "a" * 64 + "\n"
        )
        self.assertTrue(POLICY.check_hub_image_cohort(self.app))

    def test_quoted_extra_image_in_existing_manifest_is_rejected(self):
        path = self.app / "deployment-api.yaml"
        path.write_text(path.read_text() +
                        '\nimage: "registry.home/ghcr.io/abhi1693/wardn-hub-backend:'
                        '0.2.183@sha256:' + "a" * 64 + '"\n')
        self.assertTrue(POLICY.check_hub_image_cohort(self.app))

    def test_quotes_on_existing_cohort_image_are_supported(self):
        path = self.app / "deployment-api.yaml"
        original = path.read_text()
        image = "registry.home/ghcr.io/abhi1693/wardn-hub-backend:0.2.182@sha256:" + "a" * 64
        for quote in ("'", '"'):
            path.write_text(original.replace(image, quote + image + quote, 1))
            self.assertEqual(POLICY.check_hub_image_cohort(self.app), [])

    def test_reviewed_hub_rule_does_not_disable_other_direct_updates(self):
        defaults = ('automerge: true,\nautomergeType: "branch",\n'
                    'platformAutomerge: false,\nprCreation: "immediate",\n'
                    'dependencyDashboard: false,\nrecreateWhen: "always",\n')
        reviewed = '{\n  groupSlug: "wardn-hub-images",\n  automerge: false\n}\n'
        self.assertEqual(POLICY.check_default_merge_policy(defaults + reviewed, reviewed), [])
        self.assertTrue(POLICY.check_default_merge_policy(
            defaults.replace("automerge: true", "automerge: false") + reviewed, reviewed
        ))
        self.assertTrue(POLICY.check_default_merge_policy(
            defaults + reviewed + '{\n  automerge: false\n}\n', reviewed
        ))


if __name__ == "__main__":
    unittest.main()
