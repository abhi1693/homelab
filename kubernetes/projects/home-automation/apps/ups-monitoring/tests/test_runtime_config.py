"""Exercise real init writes after the NUT entrypoint changes its config directory mode."""

from pathlib import Path
import os
import stat
import subprocess
import tempfile
import unittest

import yaml


APP = Path(__file__).resolve().parents[1]
POD = yaml.safe_load((APP / 'deployment.yaml').read_text())['spec']['template']['spec']
INIT = next(container for container in POD['initContainers']
            if container['name'] == 'prepare-runtime-config')
NUT = next(container for container in POD['containers'] if container['name'] == 'nut-upsd')
CONFIG_MOUNT = next(mount for mount in NUT['volumeMounts'] if mount['name'] == 'nut-local-config')


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.paths = {name: self.root / name for name in
                      ('nut-secrets', 'nut-local', 'peanut-config', 'peanut-config-seed')}
        for path in self.paths.values():
            path.mkdir()
        (self.paths['peanut-config-seed'] / 'settings.yml').write_text('HOST: fixture\n')
        self.script = INIT['args'][0]
        for name, path in self.paths.items():
            self.script = self.script.replace('/' + name + '/', str(path) + '/')
        # Root test runners must also exercise normal DAC checks, as the real init does.
        self.identity = {}
        if os.geteuid() == 0:
            self.identity = {'user': 65534, 'group': 65534, 'extra_groups': []}
            for path in [self.root, *self.root.rglob('*')]:
                os.chown(path, 65534, 65534)

    def run_init(self):
        return subprocess.run(INIT['command'] + [self.script], text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              **self.identity)

    def assert_private_consistent_config(self):
        password_path = self.paths['nut-secrets'] / 'nut-upsd-password'
        config_path = self.paths['nut-local'] / 'upsmon.conf'
        password = password_path.read_text().strip()
        monitor = config_path.read_text().splitlines()[0].split()
        self.assertTrue(bool(password) and monitor[4] == password)
        self.assertEqual(stat.S_IMODE(password_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(config_path.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE((self.paths['peanut-config'] / 'settings.yml').stat().st_mode), 0o640)

    def test_init_retains_unprivileged_security_context(self):
        security = INIT['securityContext']
        self.assertEqual((security['runAsUser'], security['runAsGroup']), (1000, 1000))
        self.assertTrue(security['runAsNonRoot'])
        self.assertFalse(security['allowPrivilegeEscalation'])
        self.assertEqual(security['capabilities']['drop'], ['ALL'])

    def test_nut_receives_only_readonly_config_file(self):
        self.assertEqual(CONFIG_MOUNT['mountPath'], '/etc/nut/local/upsmon.conf')
        self.assertEqual(CONFIG_MOUNT['subPath'], 'upsmon.conf')
        self.assertTrue(CONFIG_MOUNT['readOnly'])

    def test_legacy_shared_directory_mode_reproduces_repeat_init_failure(self):
        self.assertEqual(self.run_init().returncode, 0)
        shared = self.paths['nut-local']
        # Upstream entrypoint: chmod 640 /etc/nut/* also includes /etc/nut/local.
        shared.chmod(0o640)
        try:
            result = self.run_init()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Permission denied', result.stderr)
        finally:
            shared.chmod(0o700)

    def test_retained_volume_survives_repeated_init_after_consumer_chmod(self):
        for iteration in range(3):
            result = self.run_init()
            self.assertEqual(result.returncode, 0, 'Retained-volume initialization failed')
            self.assert_private_consistent_config()
            if CONFIG_MOUNT['mountPath'] == '/etc/nut/local':
                consumer_local = self.paths['nut-local']
            else:
                # A file bind mount leaves the consumer parent separate from the shared root.
                consumer_local = self.root / ('consumer-local-' + str(iteration))
                consumer_local.mkdir()
                (consumer_local / 'upsmon.conf').symlink_to(self.paths['nut-local'] / 'upsmon.conf')
            consumer_local.chmod(0o640)
            self.addCleanup(consumer_local.chmod, 0o700)


if __name__ == '__main__':
    unittest.main()
