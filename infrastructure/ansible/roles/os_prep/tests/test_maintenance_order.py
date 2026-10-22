"""Verify primary-aware host ordering and the actual serial Ansible limit behavior."""

from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest
import yaml

ROLE = Path(__file__).resolve().parents[1]
ANSIBLE_ROOT = ROLE.parents[1]
TASK_PATH = ROLE / 'tasks/os_updates_order.yml'
TASKS = yaml.safe_load(TASK_PATH.read_text())
CODE = TASKS[0]['ansible.builtin.command']['argv'][2]
MAPPING = {f'server-{i}': f'node-{i}' for i in range(1, 4)}
MAPPING.update({f'worker-{i}': f'node-{i + 3}' for i in range(1, 6)})
SERVERS, WORKERS = list(MAPPING)[:3], list(MAPPING)[3:]
CLUSTER = {'metadata': {'namespace': 'postgresql', 'name': 'postgresql', 'uid': 'cluster-uid'},
           'status': {'currentPrimary': 'postgresql-2', 'targetPrimary': 'postgresql-2'}}
POD = {'metadata': {'namespace': 'postgresql', 'name': 'postgresql-2',
                    'labels': {'cnpg.io/cluster': 'postgresql'},
                    'ownerReferences': [{'kind': 'Cluster', 'uid': 'cluster-uid'}]},
       'spec': {'nodeName': 'node-6'}}


def resolver(selected, cluster=CLUSTER, pod=POD, mapping=MAPPING):
    from contextlib import redirect_stdout
    from unittest.mock import patch
    import io
    import sys
    fixture = [{'items': [cluster]}, pod]
    output = io.StringIO()
    with patch('subprocess.check_output', side_effect=[json.dumps(x) for x in fixture]):
        with patch.object(sys, 'argv', ['order', json.dumps(mapping), json.dumps(selected),
                                      json.dumps(SERVERS), json.dumps(WORKERS)]):
            with redirect_stdout(output):
                exec(compile(CODE, str(TASK_PATH), 'exec'), {})
    return json.loads(output.getvalue())


class OrderingTests(unittest.TestCase):
    def test_stable_partition_preserves_servers_and_selected_workers(self):
        self.assertEqual(resolver(SERVERS + WORKERS)['selected_host_order'],
                         SERVERS + ['worker-1', 'worker-2', 'worker-4', 'worker-5', 'worker-3'])

    def test_primary_only_limit_does_not_expand(self):
        self.assertEqual(resolver(['worker-3'])['selected_host_order'], ['worker-3'])

    def test_excluded_primary_still_reported_without_adding_it(self):
        result = resolver(['worker-2', 'worker-4'])
        self.assertEqual(result['selected_host_order'], ['worker-2', 'worker-4'])
        self.assertEqual(result['current_primaries'][0]['host'], 'worker-3')

    def test_unknown_primary_node_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'inventory node mapping'):
            resolver(WORKERS, pod={**POD, 'spec': {'nodeName': 'unknown'}})

    def test_duplicate_inventory_hostnames_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'must be unique'):
            resolver(WORKERS, mapping={**MAPPING, 'worker-2': 'node-6'})

    def test_failover_in_progress_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'stable current primary'):
            resolver(WORKERS, cluster={**CLUSTER, 'status': {'currentPrimary': 'postgresql-1',
                                                          'targetPrimary': 'postgresql-2'}})

    def test_pooler_or_unowned_pod_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'live instance'):
            resolver(WORKERS, pod={**POD, 'metadata': {**POD['metadata'], 'ownerReferences': []}})

    def test_inline_python_survives_jinja(self):
        from jinja2 import Environment, StrictUndefined
        compile(Environment(undefined=StrictUndefined).from_string(CODE).render(), str(TASK_PATH), 'exec')

    def test_actual_ansible_preplay_serial_order_and_limits(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        (base / 'ansible.cfg').write_text('[defaults]\n')
        inventory = {'all': {'children': {'k3s_nodes': {'children': {
            group: {'hosts': {host: {'ansible_connection': 'local',
                                      'node_identity': {'hostname': MAPPING[host]}} for host in hosts}}
            for group, hosts in [('k3s_servers', SERVERS), ('k3s_workers', WORKERS)]
        }}}}}
        (base / 'inventory.yml').write_text(yaml.safe_dump(inventory, sort_keys=False))
        role = base / 'roles/os_prep/tasks'
        role.mkdir(parents=True, exist_ok=True)
        mocked = yaml.safe_load(TASK_PATH.read_text())
        mocked[0].pop('delegate_to')
        prefix = '''import json, subprocess
fixtures = iter(json.loads(__import__('sys').argv[5]))
subprocess.check_output = lambda *args, **kwargs: json.dumps(next(fixtures))
'''
        mocked[0]['ansible.builtin.command']['argv'][2] = prefix + CODE
        mocked[0]['ansible.builtin.command']['argv'].append(json.dumps([{'items': [CLUSTER]}, POD]))
        (role / 'os_updates_order.yml').write_text(yaml.safe_dump(mocked, sort_keys=False))
        wrapper = yaml.safe_load((ANSIBLE_ROOT / 'playbooks/os_prep.yml').read_text())
        wrapper[0]['become'] = False
        wrapper[1]['become'] = False
        wrapper[1]['gather_facts'] = False
        wrapper[1].pop('post_tasks')
        wrapper[1]['tasks'] = [{'name': 'Record selected host',
                               'ansible.builtin.debug': {'msg': 'ORDER={{ inventory_hostname }}'}}]
        (base / 'integration-probe.yml').write_text(yaml.safe_dump(wrapper, sort_keys=False))
        cases = {
            'all': SERVERS + ['worker-1', 'worker-2', 'worker-4', 'worker-5', 'worker-3'],
            'k3s_workers:!worker-1': ['worker-2', 'worker-4', 'worker-5', 'worker-3'],
            'worker-3': ['worker-3'],
            'worker-2:worker-3': ['worker-2', 'worker-3'],
        }
        for limit, expected in cases.items():
            with self.subTest(limit=limit):
                run = subprocess.run(['ansible-playbook', '-i', str(base / 'inventory.yml'),
                                      str(base / 'integration-probe.yml'), '--limit', limit,
                                      '-e', 'os_prep_entrypoint=os_updates_plan'],
                                     env={**os.environ, 'ANSIBLE_CONFIG': str(base / 'ansible.cfg'),
                                          'ANSIBLE_ROLES_PATH': str(base / 'roles')},
                                     text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertEqual(run.returncode, 0, run.stdout)
                import re
                self.assertEqual(re.findall(r'ORDER=([^"\s]+)', run.stdout), expected)


if __name__ == '__main__':
    unittest.main()
