"""Reject stale vulnerable transitive versions before building Login."""

import copy
import importlib.util
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dependency_policy", ROOT / "check-dependency-policy.py")
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)
POLICY = json.loads((ROOT / "dependency-policy.json").read_text())


def fixture(versions=None):
    versions = versions or POLICY["minimumVersions"]
    entries = "".join(f"  '{package}': {value}\n" for package, value in versions.items())
    keys = "".join(f"  '{package}@{value}':\n    resolution: {{integrity: fixture}}\n" for package, value in versions.items())
    workspace = "overrides:\n" + entries
    return workspace, "lockfileVersion: '9.0'\noverrides:\n" + entries + "packages:\n" + keys + "snapshots:\n" + keys


class DependencyPolicyTest(unittest.TestCase):
    def check(self, workspace, lockfile):
        return GUARD.validate(workspace, lockfile, POLICY)

    def test_actual_workspace_and_lockfile_pass(self):
        self.assertEqual(self.check((ROOT / "pnpm-workspace.yaml").read_text(), (ROOT / "pnpm-lock.yaml").read_text()), [])

    def test_all_reviewed_patch_floors_pass(self):
        self.assertEqual(self.check(*fixture()), [])

    def test_future_coherent_patch_updates_pass(self):
        versions = {package: value.rsplit('.', 1)[0] + '.' + str(int(value.rsplit('.', 1)[1]) + 1)
                    for package, value in POLICY['minimumVersions'].items()}
        self.assertEqual(self.check(*fixture(versions)), [])

    def test_every_old_vulnerable_override_is_rejected(self):
        for package, minimum in POLICY["minimumVersions"].items():
            versions = copy.deepcopy(POLICY["minimumVersions"])
            parts = minimum.split('.');parts[2] = str(int(parts[2]) - 1)
            versions[package] = '.'.join(parts)
            with self.subTest(package=package):
                self.assertTrue(self.check(*fixture(versions)))

    def test_known_affected_versions_remain_rejected_if_policy_is_edited(self):
        affected = {"dompurify": "3.4.16", "ip-address": "10.7.3",
                    "@modelcontextprotocol/sdk": "1.31.0", "follow-redirects": "1.16.0",
                    "@vitest/mocker": "4.1.11"}
        for package, value in affected.items():
            versions = copy.deepcopy(POLICY["minimumVersions"]);versions[package] = value
            with self.subTest(package=package):
                self.assertTrue(self.check(*fixture(versions)))

    def test_caret_override_accepts_a_later_fixed_patch_resolution(self):
        workspace, lockfile = fixture()
        workspace = workspace.replace("'follow-redirects': 1.16.1", "'follow-redirects@<1.16.1': ^1.16.1")
        lockfile = lockfile.replace("'follow-redirects': 1.16.1", "'follow-redirects@<1.16.1': ^1.16.1")
        lockfile = lockfile.replace("follow-redirects@1.16.1", "follow-redirects@1.16.2")
        self.assertEqual(self.check(workspace, lockfile), [])

    def test_old_transitive_resolution_cannot_hide_behind_fixed_override(self):
        workspace, lockfile = fixture()
        for section in ("packages", "snapshots"):
            changed = lockfile.replace(section + ":\n", section + ":\n  'dompurify@3.4.16':\n    resolution: {integrity: fixture}\n", 1)
            with self.subTest(section=section):
                self.assertTrue(self.check(workspace, changed))

    def test_lock_override_drift_is_rejected(self):
        workspace, lockfile = fixture()
        self.assertTrue(self.check(workspace, lockfile.replace("'dompurify': 3.4.17", "'dompurify': 3.4.16")))

    def test_missing_or_empty_blocks_and_duplicate_keys_are_rejected(self):
        workspace, lockfile = fixture()
        for changed in ("", "lockfileVersion: '9.0'\n", lockfile.replace("packages:", "other:"),
                        lockfile.replace("snapshots:\n", "snapshots:\n  'dompurify@3.4.17':\n"),
                        lockfile.replace("'dompurify': 3.4.17", "'dompurify': 3.4.17\n  'dompurify': 3.4.17")):
            with self.subTest(changed=changed[:80]):
                self.assertTrue(self.check(workspace, changed))

    def test_vitest_family_mismatch_and_unreviewed_major_or_prerelease_are_rejected(self):
        for package, value in [("@vitest/mocker", "4.1.13"), ("dompurify", "4.0.0"), ("dompurify", "3.4.18-beta.1")]:
            versions = copy.deepcopy(POLICY["minimumVersions"]);versions[package] = value
            with self.subTest(package=package, value=value):
                self.assertTrue(self.check(*fixture(versions)))

    def test_docker_build_checks_policy_before_frozen_install(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        guard = "RUN python3 /tmp/check-dependency-policy.py --workspace /src/pnpm-workspace.yaml --lockfile /src/pnpm-lock.yaml --policy /tmp/dependency-policy.json"
        self.assertIn("COPY check-dependency-policy.py dependency-policy.json /tmp/", dockerfile)
        self.assertLess(dockerfile.index(guard), dockerfile.index("RUN pnpm install --frozen-lockfile"))

    def test_pr_native_validation_cannot_publish_an_image(self):
        workflow = (ROOT.parents[2] / ".github/workflows/zitadel-login-image.yml").read_text()
        self.assertIn("  pull_request:\n", workflow)
        self.assertIn("    needs: source-policy\n", workflow)
        self.assertIn("      push: ${{ github.event_name != 'pull_request' && github.ref == 'refs/heads/master' }}\n", workflow)
        self.assertIn("python3 kubernetes/images/zitadel-login/check-dependency-policy.py", workflow)
        self.assertIn("python3 -m unittest discover --start-directory kubernetes/images/zitadel-login/tests -v", workflow)

    def test_source_automerge_waits_for_native_branch_checks(self):
        repo = ROOT.parents[2]
        config = (repo / "kubernetes/projects/applications/apps/renovate/configmap.yaml").read_text()
        description = "Require passing Zitadel Login source and image checks before automerge"
        rules = re.findall(r"\{[^{}]*\}", config)
        selected = [rule for rule in rules if description in rule]
        self.assertEqual(len(selected), 1)
        self.assertIn('matchFileNames: ["kubernetes/images/zitadel-login/**", ".github/workflows/zitadel-login-image.yml"]', selected[0])
        self.assertIn("ignoreTests: false", selected[0])
        self.assertEqual(sorted(re.findall(r"^\s*(\w+):", selected[0], re.MULTILINE)),
                         ["description", "ignoreTests", "matchFileNames"])
        self.assertLess(config.index(description), config.index("Require initialized template validation before Terraform automerge"))
        workflow = (repo / ".github/workflows/zitadel-login-image.yml").read_text()
        self.assertIn('      - "renovate/**"\n', workflow)

    def test_global_policy_validation_runs_dependency_regressions(self):
        runner = (ROOT.parents[2] / "scripts/run-pre-commit-validation.sh").read_text()
        self.assertIn("  python3 -m unittest discover -s kubernetes/images/zitadel-login/tests -v\n", runner)

    def test_native_image_scan_sbom_and_unfixed_coverage_are_explicit(self):
        workflow = (ROOT.parents[2] / ".github/workflows/zitadel-login-image.yml").read_text()
        for line in ("      scan: true\n", "      sbom: true\n",
                     "      scan-ignore-unfixed: false\n", "      provenance: mode=max\n"):
            self.assertIn(line, workflow)


if __name__ == "__main__":
    unittest.main()
