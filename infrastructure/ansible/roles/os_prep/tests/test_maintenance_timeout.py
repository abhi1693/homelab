"""Exercise phase-specific OS timeout wiring through the real health template."""

import json
from pathlib import Path
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
import yaml


ROLE_DIRECTORY = Path(__file__).resolve().parents[1]
SHARED_ROLE_DIRECTORY = ROLE_DIRECTORY.parent / 'k3s_server'
HEALTH_TASKS = yaml.safe_load((ROLE_DIRECTORY / 'tasks/os_updates_health.yml').read_text())
def render(expression, context):
    return Templar(loader=DataLoader(), variables=context).template(trust_as_template(expression))


class MaintenanceTimeoutTests(unittest.TestCase):
    def guard(self, settings):
        guard = next(task for task in HEALTH_TASKS if task['name'] == 'Validate the bounded OS maintenance recovery timeout')
        return all(render('{{ ' + expression + ' }}', {'os_prep': settings})
                   for expression in guard['ansible.builtin.assert']['that'])

    def health_config(self, phase, settings):
        include = next(task for task in HEALTH_TASKS if task.get('ansible.builtin.include_role', {}).get('name') == 'k3s_server')
        context = yaml.safe_load((SHARED_ROLE_DIRECTORY / 'defaults/main.yml').read_text())
        context.update({
            'os_prep': settings,
            'os_prep_os_health_phase': phase,
            'groups': {'k3s_servers': ['server-1', 'server-2', 'server-3']},
            'hostvars': {
                name: {'ansible_host': '192.0.2.' + str(index), 'node_identity': {'hostname': 'node-' + str(index)}}
                for index, name in enumerate(['server-1', 'server-2', 'server-3'], start=1)
            },
            'node_identity': {'hostname': 'node-4'},
            'k3s': {'version': 'v-test', 'registration_vip': '192.0.2.100'},
            'k3s_server_etcdctl_version': 'test',
            'k3s_server_health_deployments': ['apps/frontend'],
            'k3s_server_health_daemonsets': ['kube-system/network'],
            'k3s_server_health_gitrepos': ['apps'],
        })
        # Render the actual include_role variable expressions, then the unchanged
        # shared role's JSON configuration consumed by its bounded health loop.
        for variable in ('k3s_server_health_phase', 'k3s_server_health_timeout'):
            context[variable] = render(include['vars'][variable], context)
        result = render((SHARED_ROLE_DIRECTORY / 'templates/health-config.json.j2').read_text(), context)
        return json.loads(result) if isinstance(result, str) else result

    def test_default_recovery_and_standalone_validation_allow_1800_seconds(self):
        for phase in ('recovery', 'validation'):
            with self.subTest(phase=phase):
                config = self.health_config(phase, {})
                self.assertEqual(config['timeout'], 1800)
                self.assertEqual(config['phase'], phase)
                self.assertEqual(config['interval'], 20)
                self.assertEqual(config['samples'], 2)
                self.assertEqual(config['max_index_lag'], 1000)
                self.assertEqual(config['deployments'], ['apps/frontend'])

    def test_custom_recovery_timeout_reaches_both_health_phases(self):
        for phase in ('recovery', 'validation'):
            with self.subTest(phase=phase):
                self.assertEqual(self.health_config(phase, {'maintenance_recovery_timeout': 2400})['timeout'], 2400)

    def test_preflight_keeps_600_seconds_with_default_or_custom_recovery_timeout(self):
        for settings in ({}, {'maintenance_recovery_timeout': 2400}):
            with self.subTest(settings=settings):
                self.assertEqual(self.health_config('preflight', settings)['timeout'], 600)

    def test_guard_accepts_default_minimum_and_larger_bounded_values(self):
        self.assertTrue(self.guard({}))
        for value in (600, 1800, 2400):
            with self.subTest(value=value):
                self.assertTrue(self.guard({'maintenance_recovery_timeout': value}))

    def test_guard_rejects_short_non_integer_or_missing_timeout_values(self):
        for value in (-1, 0, 599, 600.5, '1800', True, None):
            with self.subTest(value=value):
                self.assertFalse(self.guard({'maintenance_recovery_timeout': value}))

    def test_os_argument_spec_declares_integer_default_without_changing_shared_role_default(self):
        spec = yaml.safe_load((ROLE_DIRECTORY / 'meta/argument_specs.yml').read_text())
        option = spec['argument_specs']['main']['options']['os_prep']['options']['maintenance_recovery_timeout']
        self.assertEqual(option['type'], 'int')
        self.assertEqual(option['default'], 1800)
        shared_defaults = yaml.safe_load((SHARED_ROLE_DIRECTORY / 'defaults/main.yml').read_text())
        self.assertEqual(shared_defaults['k3s_server_health_timeout'], 600)


if __name__ == '__main__':
    unittest.main()
