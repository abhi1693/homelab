"""Verify create-once ledger rendering and the guarded legacy migration."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
import yaml

APP = Path(__file__).parents[1]

@unittest.skipUnless(shutil.which('helm'), 'Helm is required for chart regressions')
class LedgerChartTests(unittest.TestCase):
    def render(self, *arguments):
        return subprocess.run(['helm', 'template', 'pi-recovery', str(APP), '-n',
                               'cattle-monitoring-system', *arguments], text=True,
                              capture_output=True, timeout=15)
    def resources(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return [d for d in yaml.safe_load_all(result.stdout) if d]
    def test_fresh_install_creates_an_idle_ledger_with_keep_policy(self):
        resources = self.resources(self.render('--set', 'ledgerBootstrap.migrateExisting=false'))
        lease = next(d for d in resources if d['kind'] == 'Lease')
        self.assertEqual(lease['metadata']['annotations']['helm.sh/resource-policy'], 'keep')
        self.assertEqual(json.loads(lease['metadata']['annotations']['home-lab.io/recovery-state']),
                         {'phase': 'idle', 'actions': []})
        self.assertNotIn('resourceVersion', lease['metadata'])
    def test_normal_upgrade_never_renders_or_overwrites_the_runtime_ledger(self):
        resources = self.resources(self.render('--is-upgrade', '--set', 'ledgerBootstrap.migrateExisting=false'))
        self.assertFalse(any(d['kind'] == 'Lease' for d in resources))
    def test_reviewed_migration_uses_optimistic_concurrency(self):
        resources = self.resources(self.render('--is-upgrade', '--set', 'ledgerBootstrap.migrateExisting=true'))
        lease = next(d for d in resources if d['kind'] == 'Lease')
        value = yaml.safe_load((APP / 'values.yaml').read_text())['ledgerBootstrap']
        self.assertEqual(lease['metadata']['uid'], value['uid'])
        self.assertEqual(lease['metadata']['resourceVersion'], value['resourceVersion'])
        self.assertEqual(json.loads(lease['metadata']['annotations']['home-lab.io/recovery-state']), value['state'])
        self.assertEqual(lease['metadata']['annotations']['helm.sh/resource-policy'], 'keep')
    def test_migration_requires_the_reviewed_resource_version(self):
        result = self.render('--is-upgrade', '--set', 'ledgerBootstrap.migrateExisting=true',
                             '--set', 'ledgerBootstrap.resourceVersion=')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Reviewed migration resourceVersion is required', result.stderr)
    def test_deployment_uses_a_pinned_application_image_without_embedded_code(self):
        resources = self.resources(self.render('--set', 'ledgerBootstrap.migrateExisting=false'))
        deployment = next(d for d in resources if d['kind'] == 'Deployment')
        spec = deployment['spec']['template']['spec']
        image = spec['containers'][0]['image']
        self.assertRegex(image, r'^registry\.home/ghcr\.io/abhi1693/pi-recovery:[0-9]+\.[0-9]+\.[0-9]+@sha256:[a-f0-9]{64}$')
        self.assertEqual(image.split('@')[0].rsplit(':', 1)[1],
                         yaml.safe_load((APP / 'Chart.yaml').read_text())['appVersion'])
        self.assertFalse(any(d['kind'] == 'ConfigMap' for d in resources))
        self.assertFalse(any(v['name'] == 'code' for v in spec['volumes']))

if __name__ == '__main__':
    unittest.main()
