"""Keep the sidecar able to read the official image's private data directory."""
from pathlib import Path
import unittest

import yaml


class SharedStateIdentityTests(unittest.TestCase):
    def test_reconciler_uses_the_owner_of_the_private_ryokan_state(self):
        app = Path(__file__).resolve().parents[1]
        config = yaml.safe_load((app / 'configmap.yaml').read_text())['data']
        spec = yaml.safe_load((app / 'deployment.yaml').read_text())['spec']['template']['spec']
        sidecar = next(c for c in spec['containers'] if c['name'] == 'import-reconciler')
        security = sidecar['securityContext']
        self.assertGreater(int(config['PUID']), 0)
        self.assertEqual(security['runAsUser'], int(config['PUID']))
        self.assertEqual(security['runAsGroup'], int(config['PGID']))
