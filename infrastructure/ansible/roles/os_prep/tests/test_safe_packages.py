"""Evaluate the actual Ansible package-transaction boundary with hostile plans."""
from pathlib import Path
import unittest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[3]
TASKS = yaml.safe_load((ROOT / 'playbooks/os_safe_packages.yml').read_text())[0]['tasks']
BOUNDARY = next(t['ansible.builtin.assert']['that'] for t in TASKS if t['name'].startswith('Reject removals'))
PINS = {'libbrotli1': '1.2.0-3ubuntu0.1', 'bpftool': '7.7.0+7.0.0-42.42'}


class SafePackageTests(unittest.TestCase):
    def accepted(self, plan):
        variables = {'os_prep': {'safe_package_pins': PINS}, 'os_safe_plan': {'stdout': plan}}
        templar = Templar(loader=DataLoader(), variables=variables)
        return all(templar.template(trust_as_template('{{ ' + expression + ' }}')) for expression in BOUNDARY)

    def test_noop_and_exact_reviewed_updates_pass(self):
        self.assertTrue(self.accepted('0 upgraded, 0 newly installed, 0 to remove'))
        self.assertTrue(self.accepted('Inst libbrotli1 [old] (new Ubuntu [arm64])\nInst bpftool:arm64 [old] (new Ubuntu)\nConf libbrotli1 (new)'))

    def test_firmware_activity_is_never_treated_as_idle(self):
        tasks = yaml.safe_load((ROOT / 'playbooks/os_refresh_library_consumers.yml').read_text())[0]['tasks']
        expression = next(t['ansible.builtin.assert']['that'][0] for t in tasks if t['name'].startswith('Require the daemon'))
        for status in range(15):
            templar = Templar(loader=DataLoader(), variables={'os_library_fwupd_status': {'stdout': f'u {status}'}})
            actual = templar.template(trust_as_template('{{ ' + expression + ' }}'))
            self.assertEqual(actual, status == 1)

    def test_removal_kernel_service_or_new_dependency_blocks(self):
        for plan in ('Remv libbrotli1 [old]', 'Inst linux-image-raspi [old] (new)', 'Inst systemd [old] (new)', 'Inst libunexpected:arm64 (new)'):
            with self.subTest(plan=plan):
                self.assertFalse(self.accepted(plan))


if __name__ == '__main__':
    unittest.main()
