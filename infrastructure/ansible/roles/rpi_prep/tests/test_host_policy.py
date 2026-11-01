import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import yaml
from ansible.template import Templar
from ansible.parsing.dataloader import DataLoader
from ansible.module_utils.common.arg_spec import ArgumentSpecValidator
from ansible.template import trust_as_template
ROOT = Path(__file__).resolve().parents[1]
ANSIBLE = ROOT.parents[1]
spec = importlib.util.spec_from_file_location('host', ROOT / 'files/check_vendor_kernel.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
class HostPolicyTests(unittest.TestCase):
    def render(self, expression, variables):
        return Templar(loader=DataLoader(), variables=variables).template(trust_as_template(expression))

    def test_bootstrap_role_schemas_accept_the_real_inventory_settings(self):
        all_vars = yaml.safe_load((ANSIBLE / 'inventories/home/group_vars/all.yml').read_text())
        node_vars = yaml.safe_load((ANSIBLE / 'inventories/home/group_vars/k3s_nodes.yml').read_text())
        for role, value in [('os_prep', all_vars['os_prep']), ('rpi_prep', node_vars['rpi_prep'])]:
            spec = yaml.safe_load((ROOT.parent / role / 'meta/argument_specs.yml').read_text())['argument_specs']['main']['options']
            result = ArgumentSpecValidator(spec).validate({role: value})
            self.assertEqual(result.errors.messages, [], role)

    def test_netplan_radio_removal_preserves_wired_routes_and_other_wifi(self):
        spec = importlib.util.spec_from_file_location('netplan_wireless', ROOT.parent / 'rpi_prep/files/netplan_wireless.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = {'network': {'version': 2, 'ethernets': {'eth0': {'dhcp4': True, 'dhcp4-overrides': {'route-metric': 100}}},
                                'wifis': {'wlan0': {'access-points': {'test': {'password': 'fixture'}}}, 'wlan1': {'dhcp4': True}}}}
        before = copy.deepcopy(original)
        updated = module.without_radios(original, ['wlan0'])
        self.assertEqual(original, before)
        self.assertEqual(updated['network']['ethernets'], original['network']['ethernets'])
        self.assertEqual(updated['network']['wifis'], {'wlan1': {'dhcp4': True}})
        self.assertEqual(module.without_radios(updated, ['wlan0']), updated)
        with self.assertRaises(RuntimeError):
            module.without_radios({'network': {'version': 2, 'wifis': {'wlan0': {'dhcp4': True}}}}, ['wlan0'])

    def test_ubuntu_ab_loader_resolves_normal_boot_and_rejects_alternate_assets(self):
        config = ('[all]\nos_prefix=current/\n[tryboot]\nos_prefix=new/\n[all]\n'
                  'kernel=vmlinuz\ninitramfs initrd.img followkernel\n'
                  '[pi3+]\ndtoverlay=unrelated\n[pi02]\ndtoverlay=unrelated\n[cm4]\ndtoverlay=unrelated\n[all]\n')
        self.assertEqual(host.boot_selection(config), {'prefix': 'current/', 'image': 'vmlinuz', 'initramfs': 'initrd.img'})
        for bad in [config.replace('current/', 'old/'), config.replace('new/', 'unreviewed/'),
                    config.replace('os_prefix=new/', 'kernel=custom.img'), config + 'include override.txt\n',
                    config + 'kernel=custom.img\n', config.replace('[tryboot]\nos_prefix=new/\n', '')]:
            with self.subTest(config=bad), self.assertRaises(RuntimeError):
                host.boot_selection(bad)

    def test_ubuntu_cmdline_selection_includes_staged_trial(self):
        tasks = yaml.safe_load((ROOT.parent / 'rpi_prep/tasks/boot_profile.yml').read_text())
        expression = tasks[-1]['ansible.builtin.set_fact']['rpi_cmdline_paths']
        for trial in [False, True]:
            actual = self.render(expression, {'ansible_facts': {'distribution': 'Ubuntu'}, 'rpi_trial_cmdline': {'stat': {'exists': trial}}})
            expected = ['/boot/firmware/current/cmdline.txt'] + (['/boot/firmware/new/cmdline.txt'] if trial else [])
            self.assertEqual(actual, expected)

    def test_ubuntu_validation_rejects_missing_update_pocket_and_autonomous_upgrades(self):
        task = yaml.safe_load((ROOT.parent / 'os_prep/tasks/ubuntu_validation.yml').read_text())[0]
        script = task['ansible.builtin.command']['argv'][2]
        source = ('URIs: https://archive.ubuntu.com/ubuntu/\nSuites: resolute resolute-updates resolute-security\n'
                  'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n')
        policy = 'APT::Periodic::Unattended-Upgrade "0";\nUnattended-Upgrade::Automatic-Reboot "false";\n'
        for text, settings, accepted in [(source, policy, True), (source.replace(' resolute-updates', ''), policy, False),
                                          (source.replace('https:', 'http:'), policy, False),
                                          (source, policy.replace('"0"', '"1"'), False)]:
            with patch('pathlib.Path.read_text', return_value=text), patch('subprocess.check_output', return_value=settings), \
                    patch('sys.argv', ['validator', 'https://archive.ubuntu.com/ubuntu/']), patch('builtins.print'):
                if accepted:
                    exec(compile(script, '<ubuntu-policy>', 'exec'), {})
                else:
                    with self.assertRaises(AssertionError):
                        exec(compile(script, '<ubuntu-policy>', 'exec'), {})

    def test_smart_check_rejects_critical_nvme_and_missing_health_without_self_tests(self):
        task = yaml.safe_load((ROOT.parent / 'smartctl_exporter/tasks/health.yml').read_text())[0]
        script = task['ansible.builtin.command']['argv'][2]
        scan = json.dumps({'devices': [{'name': '/dev/nvme0', 'type': 'nvme'}]})
        for passed, warning, rc, accepted in [(True, 0, 0, True), (True, 1, 0, False), (False, 0, 0, False), (True, 0, 2, False)]:
            health = {'smart_status': {'passed': passed}, 'nvme_smart_health_information_log': {'critical_warning': warning}}
            result = subprocess.CompletedProcess([], rc, json.dumps(health), '')
            with patch('subprocess.check_output', return_value=scan), patch('subprocess.run', return_value=result) as command, patch('builtins.print'):
                if accepted:
                    exec(compile(script, '<smart-health>', 'exec'), {})
                else:
                    with self.assertRaises(AssertionError):
                        exec(compile(script, '<smart-health>', 'exec'), {})
                self.assertNotIn('--test', command.call_args.args[0])
