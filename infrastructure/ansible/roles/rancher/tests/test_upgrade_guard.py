"""Exercise the production surge guard with Ansible's expression evaluator."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


class UpgradeGuardTests(unittest.TestCase):
    def test_upgrade_capacity_and_missing_manifest(self):
        role = Path(__file__).resolve().parents[1]
        tasks = yaml.safe_load((role / 'tasks/main.yml').read_text())
        guard = next(t for t in tasks if t['name'] ==
                     'Refuse Rancher chart upgrades that cannot schedule a surge pod')
        expression = guard['ansible.builtin.assert']['that'][0]
        scenarios = [
            ('missing manifest with full deployment', False, 3, 3, True, False),
            ('new installation', False, None, 3, True, True),
            ('unchanged full deployment', True, 3, 3, False, True),
            ('changed full deployment', True, 3, 3, True, False),
            ('free capacity at source version', False, 3, 2, True, True),
            ('upgrade with spare capacity', True, 2, 2, True, True),
            ('restore three replicas', True, 2, 3, True, True),
        ]
        checks = []
        for name, exists, live, desired, changed, expected in scenarios:
            checks.append({
                'name': name,
                'ansible.builtin.assert': {'that': [f'({expression}) == expected']},
                'vars': {
                    'expected': expected,
                    'rancher': {'replicas': desired, 'anti_affinity': 'required'},
                    'rancher_existing_chart_manifest': {'stat': {'exists': exists}},
                    'rancher_chart_manifest_preflight': {'changed': changed},
                    'rancher_live_upgrade_deployment': {
                        'stdout': '' if live is None else json.dumps({'spec': {'replicas': live}})},
                },
            })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / 'inventory.yml'
            inventory.write_text(yaml.safe_dump({'all': {'children': {
                'k3s_servers': {'hosts': {f'server-{i}': {} for i in range(1, 4)}}}}}))
            playbook = root / 'test.yml'
            playbook.write_text(yaml.safe_dump([
                {'hosts': 'localhost', 'gather_facts': False, 'tasks': checks}]))
            result = subprocess.run(
                [shutil.which('ansible-playbook'), '-i', str(inventory), str(playbook)],
                cwd=root, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


    def test_stage_variables_restore_inventory(self):
        ansible_root = Path(__file__).resolve().parents[3]
        workflow = yaml.safe_load((ansible_root / 'playbooks/rancher_upgrade.yml').read_text())
        imports = [p for p in workflow if 'import_playbook' in p]
        expected = [('2.15.2', 2), ('2.15.2', 2), ('2.15.3', 2),
                    ('2.15.3', 2), ('2.15.3', 3), ('2.15.3', 3)]
        self.assertEqual(len(imports), len(expected))
        plays = []
        for stage, (version, replicas) in zip(imports, expected):
            plays.append({
                'hosts': 'localhost', 'gather_facts': False,
                'vars': stage.get('vars', {}),
                'tasks': [{'ansible.builtin.assert': {'that': [
                    f"rancher.chart_version == '{version}'",
                    f'rancher.replicas == {replicas}',
                    "rancher.hostname == 'rancher.home'",
                    "rancher.anti_affinity == 'required'",
                ]}}],
            })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / 'inventory.yml'
            inventory.write_text(yaml.safe_dump({'all': {
                'hosts': {'localhost': {}},
                'vars': {'rancher_upgrade_source_version': '2.15.2', 'rancher': {
                    'chart_version': '2.15.3', 'replicas': 3,
                    'hostname': 'rancher.home', 'anti_affinity': 'required',
                }},
            }}))
            playbook = root / 'test.yml'
            playbook.write_text(yaml.safe_dump(plays))
            result = subprocess.run(
                [shutil.which('ansible-playbook'), '-i', str(inventory), str(playbook)],
                cwd=root, capture_output=True, text=True, check=False,
                env={**os.environ, 'ANSIBLE_HASH_BEHAVIOUR': 'merge'},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
