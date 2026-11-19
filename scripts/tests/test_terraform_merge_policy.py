"""Prevent Terraform automerge from bypassing initialized module validation."""

import importlib.util
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("terraform_policy", ROOT / "scripts/check-renovate-policy.py")
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
CONFIG = (ROOT / POLICY.CONFIG_PATH).read_text()
WORKFLOW = (ROOT / ".github/workflows/terraform-validation.yml").read_text()
RUNNER = (ROOT / "scripts/run-pre-commit-validation.sh").read_text()
RULE = next(block for block in re.findall(r"\{[^{}]*\}", CONFIG) if POLICY.TERRAFORM_RULE in block)
CLI_RULE = next(block for block in re.findall(r"\{[^{}]*\}", CONFIG) if POLICY.TERRAFORM_CLI_RULE in block)
REVIEWED_RULES = [block for block in re.findall(r"\{[^{}]*\}", CONFIG)
                  if 'groupSlug: "wardn-hub-images"' in block
                  or 'groupSlug: "wardn-license-server-images"' in block
                  or f'description: "{POLICY.NETBOX_CHART_RULE}"' in block]


class TerraformMergePolicyTests(unittest.TestCase):
    def check(self, config=CONFIG, workflow=WORKFLOW, runner=RUNNER):
        return POLICY.check_terraform_merge_policy(config, workflow, runner)

    def test_current_gate_and_existing_branch_policy_pass(self):
        self.assertEqual(self.check(), [])
        self.assertEqual(POLICY.check_backup_helper_policy(CONFIG), [])
        self.assertEqual(POLICY.check_default_merge_policy(CONFIG, *REVIEWED_RULES, CLI_RULE), [])

    def test_cli_rule_cannot_be_missing_duplicated_bypassed_or_expanded(self):
        for changed in ("", CLI_RULE + "," + CLI_RULE,
                        CLI_RULE.replace("ignoreTests: false", "ignoreTests: true"),
                        CLI_RULE.replace("automerge: false", "automerge: true"),
                        CLI_RULE.replace('["uses-with"]', '["action"]'),
                        CLI_RULE.replace('["hashicorp/terraform"]', '["terraform"]'),
                        CLI_RULE.replace('[".github/workflows/terraform-validation.yml"]', '["**"]')):
            with self.subTest(changed=changed):
                self.assertTrue(self.check(config=CONFIG.replace(CLI_RULE, changed)))

    def test_cli_release_extraction_strips_only_stable_release_prefix(self):
        pattern = json.loads(re.search(r'extractVersion:\s*("(?:\\.|[^"\\])*")', CLI_RULE)[1])
        # This named capture is the common JS/RE2/Python subset used by Renovate.
        expression = re.compile(pattern.replace("(?<version>", "(?P<version>"))
        for tag, expected in (("v1.17.2", "1.17.2"), ("1.18.0", "1.18.0")):
            self.assertEqual(expression.fullmatch(tag)["version"], expected)
        for tag in ("v1.18.0-beta.1", "terraform-v1.18.0", "latest", "1.18"):
            self.assertIsNone(expression.fullmatch(tag))
        broken = CLI_RULE.replace('extractVersion:', 'extractVersionTemplate:')
        self.assertTrue(self.check(config=CONFIG.replace(CLI_RULE, broken)))

    def test_cli_rule_matches_the_extracted_input_package_only(self):
        # Renovate 44.226.2 known-actions/github-releases.ts and utils.ts emit
        # this identity for hashicorp/setup-terraform's terraform_version input.
        dependency = {"manager": "github-actions", "depType": "uses-with",
                      "datasource": "github-releases", "packageName": "hashicorp/terraform",
                      "packageFile": ".github/workflows/terraform-validation.yml"}
        selectors = {"matchManagers": "manager", "matchDepTypes": "depType",
                     "matchDatasources": "datasource", "matchPackageNames": "packageName",
                     "matchFileNames": "packageFile"}
        values = {key: json.loads(re.search(rf"{key}:\s*(\[[^\]]*\])", CLI_RULE)[1])
                  for key in selectors}

        def matches(value):
            return all(value[field] in values[key] for key, field in selectors.items())

        self.assertTrue(matches(dependency))
        for field, other in (("manager", "terraform"), ("depType", "action"),
                             ("datasource", "github-tags"), ("packageName", "terraform"),
                             ("packageName", "hashicorp/setup-terraform"),
                             ("packageFile", ".github/workflows/other.yml")):
            with self.subTest(field=field, other=other):
                self.assertFalse(matches({**dependency, field: other}))

    def test_cli_pin_is_unprefixed_and_unrelated_merge_defaults_remain(self):
        changed = re.sub(r'terraform_version: "(\d+\.\d+\.\d+)"',
                         r'terraform_version: "v\1"', WORKFLOW)
        self.assertTrue(self.check(workflow=changed))
        defaults = CONFIG.split("packageRules:", 1)[0]
        self.assertIn("ignoreTests: true", defaults)
        self.assertIn("automerge: true", defaults)
        self.assertEqual(POLICY.check_default_merge_policy(CONFIG, *REVIEWED_RULES, CLI_RULE), [])
        self.assertTrue(POLICY.check_default_merge_policy(
            CONFIG + "\n{\n  automerge: false\n}", *REVIEWED_RULES, CLI_RULE))

    def test_missing_duplicate_or_bypassed_gate_fails(self):
        for changed in ("", RULE + "," + RULE, RULE.replace("ignoreTests: false", "ignoreTests: true")):
            with self.subTest(changed=changed):
                self.assertTrue(self.check(config=CONFIG.replace(RULE, changed)))

    def test_expanded_manager_or_file_scope_fails(self):
        for changed in (RULE.replace('["terraform"]', '["terraform", "dockerfile"]'),
                        RULE.replace('["coder/templates/**"]', '["**"]'),
                        RULE.replace("ignoreTests: false", "enabled: false,\n          ignoreTests: false")):
            with self.subTest(changed=changed):
                self.assertTrue(self.check(config=CONFIG.replace(RULE, changed)))

    def test_late_override_fails(self):
        self.assertTrue(self.check(config=CONFIG.replace(RULE, RULE + ",{ignoreTests: true}")))

    def test_missing_changed_or_overbroad_watch_fails_for_each_event(self):
        for path in POLICY.TERRAFORM_CI_PATHS:
            for occurrence in (1, 2):
                line = f'      - "{path}"\n'
                offsets = [match.start() for match in re.finditer(re.escape(line), WORKFLOW)]
                offset = offsets[occurrence - 1]
                changed = WORKFLOW[:offset] + WORKFLOW[offset + len(line):]
                with self.subTest(path=path, event=occurrence):
                    self.assertTrue(self.check(workflow=changed))
        self.assertTrue(self.check(workflow=WORKFLOW.replace('"coder/templates/**/*.tf"', '"**"')))

    def test_push_requires_master_and_renovate_branches(self):
        for changed in (WORKFLOW.replace('      - "renovate/**"\n', ""),
                        WORKFLOW.replace("      - master\n", ""),
                        WORKFLOW.replace('"renovate/**"', '"**"')):
            self.assertTrue(self.check(workflow=changed))

    def test_validation_or_policy_step_cannot_be_replaced(self):
        for command in ("terraform", "renovate-policy"):
            self.assertTrue(self.check(workflow=WORKFLOW.replace(
                f"run: scripts/run-pre-commit-validation.sh {command}", "run: true")))

    def test_job_cannot_skip_or_ignore_failures_or_use_floating_setup(self):
        for changed in (WORKFLOW.replace("    steps:", "    if: false\n    steps:"),
                        WORKFLOW.replace("    steps:", "    continue-on-error: true\n    steps:"),
                        re.sub(r"hashicorp/setup-terraform@[a-f0-9]{40}", "hashicorp/setup-terraform@v4", WORKFLOW),
                        re.sub(r'terraform_version: "\d+\.\d+\.\d+"',
                               'terraform_version: "latest"', WORKFLOW)):
            self.assertTrue(self.check(workflow=changed))

    def test_hook_cannot_validate_stale_modules_or_enable_backend(self):
        init = 'terraform -chdir="${template}" init -backend=false -input=false'
        for changed in (RUNNER.replace(init, "true"),
                        RUNNER.replace(init, init + " -get=false"),
                        RUNNER.replace(init, init.replace("-backend=false", "-backend=true"))):
            with self.subTest(changed=changed):
                self.assertTrue(self.check(runner=changed))

    def test_native_toolchain_observation_cannot_be_skipped_or_moved_after_init(self):
        command = "run: python3 scripts/check-terraform-toolchain.py --expected-platform linux_arm64"
        for changed in (WORKFLOW.replace(command, "run: true"),
                        WORKFLOW.replace(command, command.replace("linux_arm64", "linux_amd64")),
                        WORKFLOW.replace(command, command + " || true"),
                        WORKFLOW.replace(command, "run: true").replace(
                            "run: scripts/run-pre-commit-validation.sh renovate-policy", command)):
            with self.subTest(workflow=changed):
                self.assertTrue(self.check(workflow=changed))

    def test_cli_cannot_regress_below_patched_stable_floor(self):
        changed = re.sub(r'terraform_version: "\d+\.\d+\.\d+"',
                         'terraform_version: "1.13.4"', WORKFLOW)
        self.assertTrue(self.check(workflow=changed))


class RenovateRuntimePolicyTests(unittest.TestCase):
    def setUp(self):
        self.cronjob = (ROOT / "kubernetes/projects/applications/apps/renovate/cronjob.yaml").read_text()

    def test_fixed_runtime_and_error_reporting_pass(self):
        self.assertEqual(POLICY.check_renovate_runtime_policy(CONFIG, self.cronjob), [])

    def test_each_datasource_requires_only_the_next_major_ceiling(self):
        for occurrence in (0, 1):
            before, selected, after = CONFIG.partition('allowedVersions: "<45.0.0"')
            if occurrence:
                tail_before, selected, tail_after = after.partition(selected)
                changed = before + 'allowedVersions: "<45.0.0"' + tail_before + 'allowedVersions: ">=44.164.1 <45.0.0"' + tail_after
            else:
                changed = before + 'allowedVersions: ">=44.164.1 <45.0.0"' + after
            with self.subTest(datasource=occurrence):
                self.assertTrue(POLICY.check_renovate_runtime_policy(changed, self.cronjob))

    def test_runtime_downgrade_and_hidden_failures_are_rejected(self):
        old = re.sub(r"renovate/renovate:\d+\.\d+\.\d+", "renovate/renovate:44.161.0", self.cronjob)
        self.assertTrue(POLICY.check_renovate_runtime_policy(CONFIG, old))
        self.assertTrue(POLICY.check_renovate_runtime_policy(CONFIG.replace("exitCodeForErrors: true", "exitCodeForErrors: false"), self.cronjob))
        self.assertTrue(POLICY.check_renovate_runtime_policy(CONFIG.replace("      exitCodeForErrors: true,\n", ""), self.cronjob))

if __name__ == "__main__":
    unittest.main()
