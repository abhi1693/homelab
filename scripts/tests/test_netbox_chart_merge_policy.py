"""Keep canonical NetBox chart updates behind review and projection validation."""

import importlib.util
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("netbox_chart_policy", ROOT / "scripts/check-renovate-policy.py")
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
CONFIG = (ROOT / POLICY.CONFIG_PATH).read_text()
WORKFLOW = (ROOT / ".github/workflows/workload-catalog.yml").read_text()
RULE = next(rule for rule in re.findall(r"\{[^{}]*\}", CONFIG)
            if f'description: "{POLICY.NETBOX_CHART_RULE}"' in rule)


class NetboxChartMergePolicyTests(unittest.TestCase):
    def check(self, config=CONFIG, workflow=WORKFLOW):
        return POLICY.check_netbox_chart_merge_policy(config, workflow)

    def test_current_policy_and_unrelated_defaults_pass(self):
        self.assertEqual(self.check(), [])
        reviewed = [rule for rule in re.findall(r"\{[^{}]*\}", CONFIG)
                    if 'groupSlug: "wardn-hub-images"' in rule
                    or 'groupSlug: "wardn-license-server-images"' in rule
                    or f'description: "{POLICY.TERRAFORM_CLI_RULE}"' in rule
                    or f'description: "{POLICY.NETBOX_CHART_RULE}"' in rule]
        self.assertEqual(POLICY.check_default_merge_policy(CONFIG, *reviewed), [])
        self.assertTrue(POLICY.check_default_merge_policy(
            CONFIG.replace("automerge: true", "automerge: false", 1), *reviewed))
        self.assertEqual(re.findall(r"^\s*ignoreTests:\s*([^,\n]+)",
                                   CONFIG.split("packageRules:", 1)[0], re.MULTILINE), ["true"])

    def test_missing_duplicate_bypass_and_late_override_fail(self):
        for changed in ("", RULE + "," + RULE,
                        RULE.replace("ignoreTests: false", "ignoreTests: true"),
                        RULE.replace("automerge: false", "automerge: true"),
                        RULE.replace("ignoreTests: false", "enabled: false,\n          ignoreTests: false"),
                        RULE + ",{ignoreTests: true}"):
            with self.subTest(changed=changed):
                self.assertTrue(self.check(config=CONFIG.replace(RULE, changed)))

    def test_selector_scope_cannot_expand_or_select_a_different_dependency(self):
        for before, after in (
            ('["custom.regex"]', '["custom.regex", "helm-values"]'),
            ('["docker"]', '["github-releases"]'),
            ('["ghcr.io/netbox-community/netbox-chart/netbox"]', '["ghcr.io/netbox-community/netbox"]'),
            ('"kubernetes/projects/training/_shared/netbox/chart.yaml"', '"**"'),
            ('"kubernetes/projects/home-automation/apps/netbox/helmop.yaml"',
             '"kubernetes/projects/home-automation/apps/netbox/values.yaml"'),
            ('"kubernetes/projects/home-automation/apps/netbox/helmop.yaml"',
             '"kubernetes/projects/home-automation/apps/netbox/helmop.yaml", "kubernetes/projects/training/apps/instructor-netbox/helmop.yaml"'),
        ):
            with self.subTest(before=before, after=after):
                self.assertTrue(self.check(config=CONFIG.replace(RULE, RULE.replace(before, after))))

    def test_exact_extracted_identity_matches_both_canonical_files_only(self):
        selectors = {"matchManagers": "manager", "matchDatasources": "datasource",
                     "matchPackageNames": "packageName", "matchFileNames": "packageFile"}
        values = {name: json.loads(re.search(rf"{name}:\s*(\[[^\]]*\])", RULE)[1])
                  for name in selectors}

        def matches(dependency):
            return all(dependency[field] in values[name] for name, field in selectors.items())

        for path in POLICY.NETBOX_CHART_FILES:
            dependency = {"manager": "custom.regex", "datasource": "docker",
                          "packageName": "ghcr.io/netbox-community/netbox-chart/netbox",
                          "packageFile": path}
            self.assertTrue(matches(dependency))
            for field, other in (("manager", "helm-values"), ("manager", "github-actions"),
                                 ("datasource", "github-releases"),
                                 ("packageName", "ghcr.io/netbox-community/netbox"),
                                 ("packageFile", "kubernetes/projects/training/apps/instructor-netbox/helmop.yaml"),
                                 ("packageFile", "kubernetes/projects/home-automation/apps/other/helmop.yaml")):
                with self.subTest(path=path, field=field, other=other):
                    self.assertFalse(matches({**dependency, field: other}))

    def test_generated_outputs_remain_excluded(self):
        for path in ("kubernetes/projects/training/apps/*-netbox/helmop.yaml",
                     "kubernetes/projects/training/apps/*-netbox/values.yaml"):
            self.assertTrue(self.check(config=CONFIG.replace(f'"{path}"', '"unrelated.yaml"')))

    def test_each_event_watches_the_canonical_and_render_inputs(self):
        for path in POLICY.NETBOX_RENDER_CI_PATHS:
            line = f'      - "{path}"\n'
            offsets = [match.start() for match in re.finditer(re.escape(line), WORKFLOW)]
            self.assertEqual(len(offsets), 2)
            for offset in offsets:
                changed = WORKFLOW[:offset] + WORKFLOW[offset + len(line):]
                with self.subTest(path=path, offset=offset):
                    self.assertTrue(self.check(workflow=changed))

    def test_projection_check_cannot_be_missing_skipped_or_ignored(self):
        command = "run: python scripts/render-training-netbox.py --check"
        for changed in (WORKFLOW.replace(command, "run: true"),
                        WORKFLOW.replace(command, command + " || true"),
                        WORKFLOW.replace(command, "if: false\n        " + command),
                        WORKFLOW.replace(command, command + "\n        continue-on-error: true")):
            with self.subTest(changed=changed):
                self.assertTrue(self.check(workflow=changed))


if __name__ == "__main__":
    unittest.main()
