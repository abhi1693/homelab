"""Prevent branch automerge from bypassing restore-point cohort regressions."""
import importlib.util
from pathlib import Path
import re
import unittest

APP = Path(__file__).resolve().parents[1]
ROOT = APP / 'proposed' if (APP / 'proposed').is_dir() else APP.parents[4]
SPEC = importlib.util.spec_from_file_location('writer_merge_policy', ROOT / 'scripts/check-renovate-policy.py')
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
CONFIG = (ROOT / POLICY.CONFIG_PATH).read_text()
WORKFLOW = (ROOT / '.github/workflows/infrastructure-regressions.yml').read_text()
RULE = next(block for block in re.findall(r'\{[^{}]*\}', CONFIG)
            if POLICY.BACKUP_WRITER_RULE in block)


class BackupWriterMergePolicyTests(unittest.TestCase):
    def check(self, config=CONFIG, workflow=WORKFLOW):
        return POLICY.check_backup_writer_merge_policy(config, workflow)

    def test_current_scoped_gate_and_final_manual_helper_rule_pass(self):
        self.assertEqual(self.check(), [])
        self.assertEqual(POLICY.check_backup_helper_policy(CONFIG), [])

    def test_missing_or_duplicate_writer_gate_rejected(self):
        for changed in [CONFIG.replace(RULE, ''), CONFIG.replace(RULE, RULE + ',{' + RULE[1:])]:
            with self.subTest():self.assertTrue(self.check(changed))

    def test_writer_test_bypass_rejected(self):
        changed = CONFIG.replace(RULE, RULE.replace('ignoreTests: false', 'ignoreTests: true'))
        self.assertTrue(self.check(changed))

    def test_wrong_package_or_datasource_rejected(self):
        for changed in [RULE.replace('ghcr.io/abhi1693/ryokan', 'ghcr.io/example/unrelated'),
                        RULE.replace('matchDatasources: ["docker"]', 'matchDatasources: ["github-releases"]')]:
            self.assertTrue(self.check(CONFIG.replace(RULE, changed)))

    def test_gate_cannot_expand_to_unrelated_packages(self):
        changed = RULE.replace('"ghcr.io/abhi1693/rack-ops"', '"ghcr.io/abhi1693/rack-ops", "ghcr.io/example/unrelated"')
        self.assertTrue(self.check(CONFIG.replace(RULE, changed)))

    def test_later_override_and_displaced_manual_helper_rule_rejected(self):
        changed = CONFIG.replace(RULE, RULE + ',{ignoreTests: true}')
        self.assertTrue(self.check(changed))
        manual = next(block for block in re.findall(r'\{[^{}]*\}', CONFIG)
                      if 'matchPackageNames: ["cgr.dev/chainguard/python"]' in block)
        changed = CONFIG.replace(RULE, manual).replace(manual + '\n      ],', RULE + '\n      ],')
        self.assertTrue(self.check(changed))
        self.assertTrue(POLICY.check_backup_helper_policy(changed))

    def test_unrelated_default_test_and_branch_automerge_policy_preserved(self):
        self.assertTrue(self.check(CONFIG.replace('ignoreTests: true', 'ignoreTests: false', 1)))
        # The existing guard still enforces branch automerge outside reviewed Hub/License rules.
        reviewed = [block for block in re.findall(r'\{[^{}]*\}', CONFIG)
                    if 'groupSlug: "wardn-hub-images"' in block or 'groupSlug: "wardn-license-server-images"' in block]
        self.assertEqual(POLICY.check_default_merge_policy(CONFIG, *reviewed), [])
        self.assertTrue(POLICY.check_default_merge_policy(CONFIG.replace('automerge: true', 'automerge: false', 1), *reviewed))

    def test_missing_renovate_push_branch_rejected(self):
        self.assertTrue(self.check(workflow=WORKFLOW.replace('      - "renovate/**"\n', '')))

    def test_unbounded_or_missing_master_push_scope_rejected(self):
        for changed in [WORKFLOW.replace('      - "renovate/**"', '      - "**"'),
                        WORKFLOW.replace('      - master\n', '')]:
            self.assertTrue(self.check(workflow=changed))

    def test_missing_app_regression_or_policy_step_rejected(self):
        for command in ['scripts/run-pre-commit-validation.sh kubernetes-tests',
                        'scripts/run-pre-commit-validation.sh renovate-policy']:
            self.assertTrue(self.check(workflow=WORKFLOW.replace('run: ' + command, 'run: true')))

    def test_writer_manifest_push_path_gap_rejected(self):
        self.assertTrue(self.check(workflow=WORKFLOW.replace(
            '      - "kubernetes/projects/home-automation/apps/cluster-ops/**"\n', '', 1)))
