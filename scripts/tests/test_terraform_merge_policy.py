"""Prevent Terraform automerge from bypassing initialized module validation."""

import importlib.util
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


class TerraformMergePolicyTests(unittest.TestCase):
    def check(self, config=CONFIG, workflow=WORKFLOW, runner=RUNNER):
        return POLICY.check_terraform_merge_policy(config, workflow, runner)

    def test_current_gate_and_existing_branch_policy_pass(self):
        self.assertEqual(self.check(), [])
        self.assertEqual(POLICY.check_backup_helper_policy(CONFIG), [])
        reviewed = [block for block in re.findall(r"\{[^{}]*\}", CONFIG)
                    if 'groupSlug: "wardn-hub-images"' in block
                    or 'groupSlug: "wardn-license-server-images"' in block]
        self.assertEqual(POLICY.check_default_merge_policy(CONFIG, *reviewed), [])

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


if __name__ == "__main__":
    unittest.main()
