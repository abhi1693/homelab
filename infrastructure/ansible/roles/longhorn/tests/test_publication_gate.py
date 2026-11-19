"""Prevent unavailable or mismatched chart pairs reaching mutation stages."""

from pathlib import Path
import unittest
import copy
import shutil
import subprocess
import tempfile
import yaml

ROOT = Path(__file__).resolve().parents[5]
PLAY = yaml.safe_load((ROOT / "infrastructure/ansible/playbooks/longhorn_upgrade.yml").read_text())[0]


class PublicationGateTests(unittest.TestCase):
    def test_authorization_then_read_only_publication_checks_precede_cluster_work(self):
        tasks = PLAY["pre_tasks"]
        self.assertEqual(tasks[0]["name"], "Require explicit stage and independent recovery verification")
        self.assertIn("ansible.builtin.uri", tasks[1])
        self.assertIn("ansible.builtin.assert", tasks[2])
        self.assertIn("ansible.builtin.assert", tasks[3])
        self.assertEqual(tasks[4]["name"], "Check the local API readiness endpoint")
        uri = tasks[1]["ansible.builtin.uri"]
        self.assertEqual(uri["url"], "https://charts.rancher.io/index.yaml")
        self.assertTrue(uri["validate_certs"])
        self.assertEqual(tasks[1]["delegate_to"], "localhost")
        self.assertFalse(tasks[1]["become"])
        self.assertFalse(tasks[1]["check_mode"])

    def test_both_exact_artifacts_and_matching_application_versions_are_required(self):
        assertions = PLAY["pre_tasks"][2]["ansible.builtin.assert"]["that"]
        self.assertEqual(len(assertions), 2)
        self.assertIn("longhorn.chart_version", assertions[0])
        self.assertIn("entries['longhorn']", assertions[0])
        self.assertIn("longhorn.crd_chart_version", assertions[1])
        self.assertIn("entries['longhorn-crd']", assertions[1])
        pair = PLAY["pre_tasks"][3]["ansible.builtin.assert"]["that"][0]
        self.assertEqual(pair.count(".appVersion"), 2)
        self.assertIn("==", pair)


class PublicationBehaviorTests(unittest.TestCase):
    def run_gate(self, manager=True, crd=True, matching=True):
        catalog = {"entries": {
            "longhorn": [{"version": "manager-pin", "appVersion": "1.12.1"}] if manager else [],
            "longhorn-crd": [{"version": "crd-pin", "appVersion": "1.12.1" if matching else "1.11.0"}] if crd else [],
        }}
        play = [{"hosts": "localhost", "gather_facts": False, "vars": {
            "longhorn": {"chart_version": "manager-pin", "crd_chart_version": "crd-pin"},
            "longhorn_upgrade_chart_catalog": {"content": yaml.safe_dump(catalog)},
        }, "tasks": copy.deepcopy(PLAY["pre_tasks"][2:4])}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gate.yml"
            path.write_text(yaml.safe_dump(play, sort_keys=False))
            return subprocess.run([shutil.which("ansible-playbook"), "--check", "-i", "localhost,",
                                   "-c", "local", str(path)], text=True, capture_output=True, timeout=30)

    def test_published_matching_pair_passes_actual_ansible_assertions(self):
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_artifact_fails_before_pair_comparison(self):
        for manager, crd in ((False, True), (True, False)):
            with self.subTest(manager=manager, crd=crd):
                result = self.run_gate(manager=manager, crd=crd)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Both exact Rancher manager and CRD charts must exist", result.stdout)

    def test_mismatched_application_releases_fail(self):
        result = self.run_gate(matching=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("target different Longhorn application releases", result.stdout)


if __name__ == "__main__":
    unittest.main()
