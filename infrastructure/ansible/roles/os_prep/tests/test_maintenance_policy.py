"""Exercise the actual Jinja transaction guards with APT simulation excerpts."""

from pathlib import Path
from contextlib import redirect_stdout
import io
import json
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from ansible.plugins.filter.core import FilterModule as CoreFilters
from ansible.plugins.filter.mathstuff import FilterModule as MathFilters
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import yaml


TASKS = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "tasks" / "os_updates_plan.yml").read_text()
)
ENVIRONMENT = NativeEnvironment(undefined=StrictUndefined)
ENVIRONMENT.filters.update(CoreFilters().filters())
ENVIRONMENT.filters.update(MathFilters().filters())
SOURCE_POLICIES = yaml.safe_load(
    (Path(__file__).resolve().parents[3] / 'inventories/home/group_vars/all.yml').read_text()
)['os_prep']['apt_https_sources']


def task(name):
    return next(item for item in TASKS if item["name"] == name)


def permits(transaction, replacements):
    context = {
        "os_prep": {"package_replacements": replacements},
        "os_prep_os_transaction": {"stdout": transaction},
    }
    for key, expression in task("Record proposed installs and removals")["ansible.builtin.set_fact"].items():
        context[key] = ENVIRONMENT.from_string(expression).render(context)
    conditions = task("Reject removals without an inventory-managed replacement policy")["ansible.builtin.assert"]["that"]
    if not all(ENVIRONMENT.compile_expression(condition)(context) for condition in conditions):
        return False
    conditions = task("Require each removed package to have its configured replacement installed")["ansible.builtin.assert"]["that"]
    for package in context["os_prep_os_proposed_removals"]:
        if not all(ENVIRONMENT.compile_expression(condition)(context, item=package) for condition in conditions):
            return False
    return True


class MaintenancePolicyTests(unittest.TestCase):
    def rewrite_source(self, path, content):
        for policy in SOURCE_POLICIES:
            if policy['path'] == path:
                content = re.sub(policy['regexp'], policy['replace'], content)
        return content

    def test_debian_https_policy_preserves_signing_keys_suites_and_vendor_sources(self):
        before = (
            'Types: deb deb-src\nURIs: http://deb.debian.org/debian/\n'
            'Suites: trixie trixie-updates\nComponents: main non-free-firmware\n'
            'Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp\n\n'
            'Types: deb\nURIs: http://deb.debian.org/debian-security\n'
            'Suites: trixie-security\nSigned-By: /usr/share/keyrings/debian-archive-keyring.pgp\n\n'
            'Types: deb\nURIs: http://archive.raspberrypi.com/debian\n'
            'Suites: trixie\nSigned-By: /usr/share/keyrings/raspberrypi-archive-keyring.gpg\n'
        )
        expected = before.replace('http://deb.debian.org/', 'https://deb.debian.org/')
        self.assertEqual(self.rewrite_source(SOURCE_POLICIES[0]['path'], before), expected)

    def test_https_policy_preserves_the_original_official_security_hostname(self):
        before = 'URIs: http://security.debian.org/debian-security/\n'
        self.assertEqual(
            self.rewrite_source(SOURCE_POLICIES[0]['path'], before),
            'URIs: https://security.debian.org/debian-security/\n',
        )

    def test_https_policy_does_not_rewrite_similar_domains_or_other_archive_paths(self):
        before = (
            'URIs: http://deb.debian.org.example/debian/ http://deb.debian.org/debian-other/ '
            'http://deb.debian.org/debian/pool/ http://example.org/debian/\n'
        )
        self.assertEqual(self.rewrite_source(SOURCE_POLICIES[0]['path'], before), before)

    def test_vendor_file_is_outside_the_managed_transport_policy(self):
        before = 'URIs: http://archive.raspberrypi.com/debian\n'
        self.assertEqual(self.rewrite_source('/etc/apt/sources.list.d/raspi.sources', before), before)

    def test_https_source_transport_policy_is_idempotent(self):
        before = 'URIs: https://deb.debian.org/debian/\n'
        self.assertEqual(self.rewrite_source(SOURCE_POLICIES[0]['path'], before), before)

    def test_readonly_source_validation_rejects_http_and_accepts_https(self):
        path = Path(__file__).resolve().parents[1] / 'tasks' / 'apt_sources_validation.yml'
        code = yaml.safe_load(path.read_text())[0]['ansible.builtin.command']['argv'][2]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'debian.sources'
            policy = {**SOURCE_POLICIES[0], 'path': str(source)}
            with patch.object(sys, 'argv', ['check-sources', json.dumps([policy])]):
                source.write_text('URIs: http://deb.debian.org/debian/\n')
                with self.assertRaisesRegex(RuntimeError, 'still uses HTTP'):
                    exec(compile(code, str(path), 'exec'), {})
                source.write_text('URIs: https://deb.debian.org/debian/\n')
                with redirect_stdout(io.StringIO()):
                    exec(compile(code, str(path), 'exec'), {})

    def test_verified_downloads_precede_disruptive_maintenance(self):
        path = Path(__file__).resolve().parents[1] / 'tasks' / 'os_updates.yml'
        updates = yaml.safe_load(path.read_text())
        index, download = next((i, t) for i, t in enumerate(updates)
                               if '--download-only' in t.get('ansible.builtin.command', {}).get('argv', []))
        argv = download['ansible.builtin.command']['argv']
        self.assertEqual(argv[0], 'apt-get')
        self.assertIn('dist-upgrade', argv)
        self.assertNotIn('--allow-unauthenticated', argv)
        self.assertNotIn('--force-yes', argv)
        self.assertNotIn('--fix-missing', argv)
        self.assertTrue(any(t.get('ansible.builtin.include_tasks') == 'os_updates_plan.yml'
                            for t in updates[:index]))
        self.assertTrue(any('block' in t for t in updates[index + 1:]))
        self.assertFalse(any('block' in t or 'ansible.builtin.apt' in t or 'ansible.builtin.reboot' in t
                             for t in updates[:index]))

    def check_controller_health(self, controllers):
        path = Path(__file__).resolve().parents[1] / 'tasks' / 'os_updates_health.yml'
        check = next(t for t in yaml.safe_load(path.read_text())
                     if t['name'] == 'Require every application workload controller to be ready')
        code = check['ansible.builtin.command']['argv'][2]
        with patch('subprocess.check_output', return_value=json.dumps({'items': controllers})):
            with redirect_stdout(io.StringIO()):
                exec(compile(code, str(path), 'exec'), {})

    @staticmethod
    def frontend(replicas=3, ready=3, observed=2):
        return {
            'kind': 'Deployment',
            'metadata': {'namespace': 'apps', 'name': 'frontend', 'generation': 2},
            'spec': {'replicas': replicas},
            'status': {'observedGeneration': observed, 'replicas': replicas,
                       'readyReplicas': ready, 'availableReplicas': ready, 'updatedReplicas': replicas},
        }

    def test_frontend_replica_gap_blocks_node_advance(self):
        with self.assertRaisesRegex(RuntimeError, 'frontend.*desired replicas'):
            self.check_controller_health([self.frontend(ready=2)])

    def test_unobserved_application_generation_blocks_node_advance(self):
        with self.assertRaisesRegex(RuntimeError, 'desired generation'):
            self.check_controller_health([self.frontend(observed=1)])

    def test_healthy_and_intentionally_disabled_applications_pass(self):
        self.check_controller_health([self.frontend(), self.frontend(replicas=0, ready=0)])

    def test_ondelete_statefulset_readiness_preserves_its_rollout_policy(self):
        statefulset = self.frontend()
        statefulset['kind'] = 'StatefulSet'
        statefulset['spec']['updateStrategy'] = {'type': 'OnDelete'}
        statefulset['status']['updatedReplicas'] = 0
        self.check_controller_health([statefulset])

    def test_maintenance_assertion_messages_render_as_strings(self):
        context = {
            'os_prep_security_ca_roots': {'stdout': '{"root_count":148,"distrusted_roots":[]}'},
            'os_prep_os_kernel_state': {'stdout': '{"running_kernel":"test-kernel"}'},
        }
        directory = Path(__file__).resolve().parents[1] / 'tasks'
        for filename in ('security_validation.yml', 'os_updates_validation.yml'):
            for item in yaml.safe_load((directory / filename).read_text()):
                message = item.get('ansible.builtin.assert', {}).get('success_msg')
                if message is not None:
                    with self.subTest(file=filename, task=item['name']):
                        self.assertIsInstance(ENVIRONMENT.from_string(message).render(context), str)

    def test_inline_python_survives_task_templating(self):
        def bodies(value):
            if isinstance(value, dict):
                command = value.get('ansible.builtin.command', {})
                if isinstance(command, dict):
                    argv = command.get('argv', [])
                    if isinstance(argv, str):
                        argv = ENVIRONMENT.from_string(argv).render(os_prep={'distrusted_ca_sha256': []})
                    if isinstance(argv, list) and '-c' in argv:
                        yield argv[argv.index('-c') + 1]
                for child in value.values():
                    yield from bodies(child)
            elif isinstance(value, list):
                for child in value:
                    yield from bodies(child)

        for path in sorted((Path(__file__).resolve().parents[1] / 'tasks').glob('*.yml')):
            for index, code in enumerate(bodies(yaml.safe_load(path.read_text()))):
                with self.subTest(path=path.name, body=index):
                    rendered = ENVIRONMENT.from_string(code).render()
                    compile(rendered, f'{path.name}:inline-python-{index}', 'exec')

    def test_kernel_install_without_removals_is_allowed(self):
        self.assertTrue(permits(
            "Inst linux-image-6.18.50+rpt-rpi-2712 (1:6.18.50-1+rpt1 Raspberry Pi Foundation:stable [arm64])\n",
            {},
        ))

    def test_observed_desktop_package_replacement_is_allowed(self):
        self.assertTrue(permits(
            "Remv pcmanfm [1.4.0-1+rpt9] []\n"
            "Inst pcmanfm-pi (1.11 Raspberry Pi Foundation:stable [arm64]) []\n",
            {"pcmanfm": "pcmanfm-pi"},
        ))

    def test_replacement_policy_is_required(self):
        self.assertFalse(permits(
            "Remv pcmanfm [1.4.0-1+rpt9]\nInst pcmanfm-pi (1.11)\n", {},
        ))

    def test_removal_without_the_replacement_is_rejected(self):
        self.assertFalse(permits(
            "Remv pcmanfm [1.4.0-1+rpt9]\n", {"pcmanfm": "pcmanfm-pi"},
        ))

    def test_additional_essential_package_removal_is_rejected(self):
        self.assertFalse(permits(
            "Remv pcmanfm [1.4.0-1+rpt9]\nInst pcmanfm-pi (1.11)\nRemv openssh-server [1:10.0p1]\n",
            {"pcmanfm": "pcmanfm-pi"},
        ))

    def test_similar_replacement_name_does_not_pass(self):
        self.assertFalse(permits(
            "Remv pcmanfm [1.4.0-1+rpt9]\nInst pcmanfm-pi-extra (1.11)\n",
            {"pcmanfm": "pcmanfm-pi"},
        ))

    def test_up_to_date_transaction_is_allowed(self):
        self.assertTrue(permits(
            "0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.\n", {},
        ))


if __name__ == "__main__":
    unittest.main()
