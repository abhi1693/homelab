"""Verify the direct-analytics handover's deployment and credential boundaries."""
from pathlib import Path
import ast
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import unittest

import yaml

APP = Path(__file__).resolve().parents[1]


class AnalyticsRuntimeTests(unittest.TestCase):
    def assert_importer_capacity(self, importer):
        entries = yaml.safe_load((APP / 'catalog.yaml').read_text())['spec']['workloads']
        catalog = {entry['name']: entry['desiredReplicas'] for entry in entries}
        self.assertEqual(len(catalog), len(entries), 'Catalog workload names must be unique')
        replicas = importer['spec']['replicas']
        if replicas != 0:
            self.assertEqual(replicas, 1)
            self.assertEqual(catalog.get('devfeed-analytics-importer'), 1)
            return

        # Zero is valid only for the complete offline upgrade drain. Solver may
        # remain available in phase 1 while dependent jobs finish, then stop.
        publishers = ('api', 'user-api', 'admin-api', 'partner-api', 'mcp',
                      'scheduler', 'search-indexer', 'analytics-importer')
        deployments = [yaml.safe_load((APP / f'deployment-{name}.yaml').read_text())
                       for name in publishers]
        workers = [yaml.safe_load(path.read_text()) for path in APP.glob('deployment-worker-*.yaml')]
        worker_names = {worker['metadata']['name'] for worker in workers}
        self.assertIn('devfeed-worker-solver', worker_names)
        self.assertIn('devfeed-worker-images', worker_names)
        self.assertGreater(len(worker_names), 2, 'A complete worker layout must be present')
        for deployment in [*deployments, *workers]:
            name = deployment['metadata']['name']
            desired = deployment['spec']['replicas']
            self.assertEqual(catalog.get(name), desired, f'Catalog replica mismatch for {name}')
            if name == 'devfeed-worker-solver':
                self.assertIn(desired, (0, 1), 'Only the two staged solver drain states are valid')
            else:
                self.assertEqual(desired, 0, f'Importer maintenance requires {name} to stop')

    def test_workers_use_native_health_and_allow_admitted_jobs_to_drain(self):
        count = 0
        for path in APP.glob('deployment-worker-*.yaml'):
            document = yaml.safe_load(path.read_text())
            pod = document['spec']['template']['spec']
            for container in pod['containers']:
                if 'DEVFEED_WORKER_QUEUE' not in {v['name'] for v in container.get('env', [])}:
                    continue
                with self.subTest(worker=path.name):
                    count += 1
                    self.assertGreaterEqual(pod['terminationGracePeriodSeconds'], 1560)
                    for probe in ('readinessProbe', 'livenessProbe'):
                        self.assertEqual(container[probe]['exec']['command'], ['devfeed-worker-health'])
                    self.assertNotIn('exec devfeed worker', '\n'.join(container.get('command', [])))
        self.assertEqual(count, 5)

    def test_service_credentials_keep_api_boundaries(self):
        for filename, role in [('api', 'public'), ('user-api', 'user'), ('admin-api', 'admin'), ('partner-api', 'partner')]:
            with self.subTest(service=filename):
                doc = yaml.safe_load((APP / f'deployment-{filename}.yaml').read_text())
                container = doc['spec']['template']['spec']['containers'][0]
                secrets = [item['secretRef']['name'] for item in container['envFrom'] if 'secretRef' in item]
                self.assertIn(f'devfeed-clickhouse-{role}', secrets)
                self.assertNotIn('devfeed-clickhouse-ingest', secrets)

    def test_projectors_stay_retired_and_importer_uses_schema_owner(self):
        kustomize = yaml.safe_load((APP / 'kustomization.yaml').read_text())
        self.assertFalse(any('read-model' in item for item in kustomize['resources']))
        importer = yaml.safe_load((APP / 'deployment-analytics-importer.yaml').read_text())
        spec = importer['spec']['template']['spec']
        self.assert_importer_capacity(importer)
        self.assertEqual(spec.get('restartPolicy', 'Always'), 'Always')
        self.assertEqual(importer['spec']['strategy']['type'], 'Recreate')
        container = spec['containers'][0]
        self.assertEqual(container['command'], ['python', '-m', 'devfeed_core.analytics_worker'])
        self.assertIn({'secretRef': {'name': 'devfeed-clickhouse-ingest'}}, container['envFrom'])
        hook = yaml.safe_load((APP / 'migration-hook.yaml').read_text())
        migration = hook['spec']['template']['spec']['containers'][0]
        self.assertNotIn({'configMapRef': {'name': 'devfeed-clickhouse-client'}}, migration['envFrom'])
        env = {item['name']: item.get('value') for item in migration['env']}
        self.assertEqual(env['DEVFEED_CLICKHOUSE_URL'], 'http://clickhouse.clickhouse.svc.cluster.local:8123')
        command = migration['command'][-1]
        self.assertLess(command.index('run(["db", "upgrade"])'), command.index('run(["analytics", "upgrade"])'))


    def test_importer_policy_inputs_follow_admin_without_codex_credentials(self):
        document = yaml.safe_load((APP / 'deployment-analytics-importer.yaml').read_text())
        self.assertEqual(document['spec']['template']['metadata']['labels']['devfeed-redis-client'], 'true')
        container = document['spec']['template']['spec']['containers'][0]
        environment = {item['name']: item for item in container['env']}
        for name in ('DEVFEED_AI_ENABLED', 'DEVFEED_FULL_AUTOMATION',
                     'DEVFEED_CODEX_MODEL', 'DEVFEED_CODEX_APP_SERVER_URL'):
            with self.subTest(setting=name):
                self.assertEqual(environment[name]['valueFrom']['configMapKeyRef'],
                                 {'name': 'devfeed-automation', 'key': name})
        secrets = [item['secretRef']['name'] for item in container['envFrom'] if 'secretRef' in item]
        self.assertNotIn('devfeed-codex', secrets)

    def test_unchanged_schema_does_not_compete_with_the_history_import_lock(self):
        hook = yaml.safe_load((APP / 'migration-hook.yaml').read_text())
        code = hook['spec']['template']['spec']['containers'][0]['command'][-1]
        function = next(node for node in ast.parse(code).body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'analytics_schema_prepared')
        for pending, cutover, expected in [((), 'fixed-cutover', True), ((), None, False), ((2,), None, False)]:
            with self.subTest(pending=pending, cutover=cutover):
                client = AsyncMock()
                client.__aenter__.return_value = client
                runner = SimpleNamespace(current=AsyncMock(return_value=SimpleNamespace(pending_versions=pending)))
                opens = SimpleNamespace(_cutover=AsyncMock(return_value=(cutover, False)))
                namespace = {'AnalyticsClient': lambda settings: client, 'get_settings': lambda: None, 'ClickHouseMigrationRunner': lambda client: runner, 'ArticleOpenAnalytics': lambda client: opens}
                exec(compile(ast.Module(body=[function], type_ignores=[]), '<schema-hook>', 'exec'), namespace)
                self.assertEqual(asyncio.run(namespace['analytics_schema_prepared']()), expected)
                self.assertEqual(opens._cutover.await_count, 0 if pending else 1)
                runner.current.side_effect = RuntimeError('Invalid migration history')
                with self.assertRaisesRegex(RuntimeError, 'Invalid migration history'):
                    asyncio.run(namespace['analytics_schema_prepared']())


if __name__ == '__main__':
    unittest.main()
