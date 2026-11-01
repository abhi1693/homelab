"""Verify steady priority consumers and the ongoing schema upgrade boundary."""

import ast
import hashlib
import json
from pathlib import Path
import unittest

import yaml

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[4]
POOLS = {'high': 2, 'default': 2, 'low': 1}


def document(name):
    return yaml.safe_load((APP / name).read_text())


class PriorityWorkerTests(unittest.TestCase):
    def test_each_priority_has_independent_capacity_and_full_backend(self):
        total_cpu = 0
        total_memory = 0
        total_replicas = 0
        for pool, replicas in POOLS.items():
            with self.subTest(pool=pool):
                doc = document(f'deployment-worker-{pool}.yaml')
                pod = doc['spec']['template']['spec']
                container = pod['containers'][0]
                environment = {item['name']: item.get('value') for item in container['env']}
                self.assertEqual(doc['spec']['replicas'], replicas)
                self.assertEqual(environment['DEVFEED_WORKER_QUEUE'], pool)
                self.assertIn('/backend:', container['image'])
                self.assertNotIn('cpu', container['resources']['limits'])
                self.assertEqual(container['resources']['limits']['memory'], '1Gi')
                self.assertEqual(doc['spec']['strategy']['rollingUpdate']['maxUnavailable'], 0)
                self.assertGreaterEqual(pod['terminationGracePeriodSeconds'], 1560)
                total_replicas += replicas
                total_cpu += int(container['resources']['requests']['cpu'].removesuffix('m')) * replicas
                total_memory += int(container['resources']['requests']['memory'].removesuffix('Mi')) * replicas
        for pool in ('images', 'solver'):
            doc = document(f'deployment-worker-{pool}.yaml')
            container = doc['spec']['template']['spec']['containers'][0]
            total_replicas += doc['spec']['replicas']
            total_cpu += int(container['resources']['requests']['cpu'].removesuffix('m'))
            total_memory += int(container['resources']['requests']['memory'].removesuffix('Mi'))
        self.assertEqual((total_replicas, total_cpu, total_memory), (7, 1150, 2464))

    def test_all_general_pools_can_deliver_notifications_and_trust_codex(self):
        for pool in POOLS:
            with self.subTest(pool=pool):
                pod = document(f'deployment-worker-{pool}.yaml')['spec']['template']['spec']
                container = pod['containers'][0]
                secrets = {item['secretRef']['name'] for item in container['envFrom'] if 'secretRef' in item}
                self.assertIn('devfeed-codex', secrets)
                self.assertNotIn('devfeed-image-storage', secrets)
                self.assertFalse(pod['automountServiceAccountToken'])
                self.assertEqual(container['command'][:3], ['python', '/opt/devfeed/consumer.py', 'worker'])
                volumes = {item['name']: item for item in pod['volumes']}
                self.assertEqual(volumes['devfeed-inbox-worker']['persistentVolumeClaim']['claimName'], 'devfeed-inbox-worker')
                mounts = {item['name']: item for item in container['volumeMounts']}
                self.assertTrue(mounts['devfeed-inbox-worker']['readOnly'])
                self.assertTrue(mounts['ca-bundle']['readOnly'])
                self.assertEqual({item['name'] for item in pod['initContainers']},
                                 {'trust-codex-ca', 'wait-for-inbox', 'wait-for-schema'})
                env = {item['name']: item.get('value') for item in container['env']}
                self.assertNotIn('DEVFEED_SOLVER_SERVICES', env)
                self.assertEqual(env['SSL_CERT_FILE'], '/run/ca/ca-bundle.crt')
        images = document('deployment-worker-images.yaml')['spec']['template']['spec']['containers'][0]
        self.assertIn({'secretRef': {'name': 'devfeed-image-storage'}}, images['envFrom'])
        solver = document('deployment-worker-solver.yaml')['spec']['template']['spec']['containers'][0]
        self.assertIn('DEVFEED_SOLVER_SERVICES', {item['name'] for item in solver['env']})

    def test_rendered_catalog_and_routing_have_consumers(self):
        kustomize = document('kustomization.yaml')['resources']
        files = {path.name for path in APP.glob('deployment-worker-*.yaml')}
        self.assertEqual(files, {f'deployment-worker-{pool}.yaml' for pool in (*POOLS, 'images', 'solver')})
        self.assertTrue(files.issubset(kustomize))
        for item in document('catalog.yaml')['spec']['workloads']:
            docs = list(yaml.safe_load_all((ROOT / item['sourcePath']).read_text()))
            deployment = next(doc for doc in docs if doc and doc.get('kind') == item['kind']
                              and doc['metadata']['name'] == item['name'])
            self.assertEqual(item['desiredReplicas'], deployment['spec']['replicas'])
        config = next(doc for doc in yaml.safe_load_all((APP / 'configmap.yaml').read_text())
                      if doc['metadata']['name'] == 'devfeed')
        routing = config['data']['DEVFEED_JOB_QUEUE_OVERRIDES']
        self.assertTrue(set(json.loads(routing).values()).issubset({*POOLS, 'images', 'solver'}))
        for service in ('api', 'user-api', 'admin-api', 'partner-api', 'scheduler', *('worker-' + pool for pool in (*POOLS, 'images', 'solver'))):
            container = document(f'deployment-{service}.yaml')['spec']['template']['spec']['containers'][0]
            self.assertIn({'configMapRef': {'name': 'devfeed'}}, container['envFrom'])
        # MCP proxies application operations through the APIs; it is not an RQ publisher.
        mcp = document('deployment-mcp.yaml')['spec']['template']['spec']['containers'][0]
        self.assertNotIn({'secretRef': {'name': 'devfeed-database'}}, mcp['envFrom'])

    def test_network_and_telemetry_follow_the_new_layout(self):
        policies = {doc['metadata']['name']: doc for doc in yaml.safe_load_all((APP / 'networkpolicy.yaml').read_text()) if doc}
        values = policies['devfeed-worker-public-egress']['spec']['podSelector']['matchExpressions'][0]['values']
        self.assertEqual(set(values), {'devfeed-worker-' + pool for pool in (*POOLS, 'images')})
        self.assertNotIn('devfeed-worker-ai-public-egress', policies)
        data = document('configmap-telemetry.yaml')['data']
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        for name in ('web', 'admin'):
            annotation = document(f'deployment-{name}.yaml')['spec']['template']['metadata']['annotations']
            self.assertEqual(annotation['devfeed.tech/telemetry-config-sha256'], digest)
        self.assertFalse((APP / 'faro-secrets.sops.yaml').exists())
        for path in APP.glob('*.yaml'):
            self.assertNotIn('faro', path.read_text().lower(), path.name)


class SchemaMigrationTests(unittest.TestCase):
    def test_schema_hook_requires_verified_image_and_bounded_lifecycle(self):
        schema = document('migration-hook.yaml')
        self.assertEqual(schema['metadata']['annotations']['helm.sh/hook'], 'pre-upgrade')
        self.assertLess(schema['spec']['activeDeadlineSeconds'], document('fleet.yaml')['helm']['timeoutSeconds'])
        pod = schema['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        container = pod['containers'][0]
        self.assertTrue(container['securityContext']['runAsNonRoot'])
        self.assertTrue(container['securityContext']['readOnlyRootFilesystem'])
        guard = next(node for node in ast.parse(container['command'][-1]).body
                     if isinstance(node, ast.If) and '__version__' in ast.unparse(node.test))
        check = compile(ast.Module(body=[guard], type_ignores=[]), '<release-guard>', 'exec')
        for version, revision in [('0.1.5', '0038'), ('0.1.6', '0038'), ('0.1.6', '0039'), ('0.1.7', '0038'), ('0.1.5', '0039'), ('0.1.7', '0039'), ('0.1.8', '0038')]:
            with self.subTest(version=version, revision=revision), self.assertRaises(RuntimeError):
                exec(check, {'__version__': version, 'SCHEMA_REVISION': revision})
        exec(check, {'__version__': '0.1.8', 'SCHEMA_REVISION': '0039'})

    def test_schema_hook_disables_unused_inference_and_uses_direct_owner(self):
        container = document('migration-hook.yaml')['spec']['template']['spec']['containers'][0]
        env = {item['name']: item for item in container['env']}
        for name in ('DEVFEED_AI_ENABLED', 'DEVFEED_FULL_AUTOMATION'):
            self.assertEqual(env[name]['value'], 'false')
        self.assertEqual(env['DEVFEED_CODEX_APP_SERVER_URL']['value'], '')
        self.assertNotIn({'secretRef': {'name': 'devfeed-codex'}}, container['envFrom'])
        self.assertEqual(env['DEVFEED_DATABASE_URL']['valueFrom']['secretKeyRef']['key'],
                         'DEVFEED_DIRECT_DATABASE_URL')
        self.assertIn({'secretRef': {'name': 'devfeed-clickhouse-ingest'}}, container['envFrom'])


if __name__ == '__main__':
    unittest.main()
