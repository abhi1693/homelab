"""Validate LAN source filtering, bounded records and exact recovery state checks."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('recovery', Path(__file__).parents[1] / 'files/node_recovery.py')
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def config(self):
        return {'node': 'k8s-rpi7', 'address': '192.168.3.181', 'interface': 'eth0',
                'sources': {'192.168.3.181': 'k8s-rpi7'},
                'receivers': [{'node': 'k8s-rpi1', 'address': '192.168.3.243', 'mac': '02:00:00:00:00:01'},
                              {'node': 'k8s-rpi2', 'address': '192.168.3.193', 'mac': '02:00:00:00:00:02'}]}

    def test_config_rejects_unsafe_interface_and_missing_redundancy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            data = self.config()
            path.write_text(json.dumps(data))
            self.assertEqual(recovery.load_config(path), data)
            for field, value in [('interface', '../sys'), ('node', 'other-host')]:
                invalid = {**data, field: value}
                path.write_text(json.dumps(invalid))
                with self.assertRaises(ValueError):
                    recovery.load_config(path)
            data['receivers'] = data['receivers'][:1]
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                recovery.load_config(path)

    def test_unknown_sources_dropped_and_multiline_payload_remains_one_json_record(self):
        sources = self.config()['sources']
        self.assertIsNone(recovery.record_for_packet(b'panic', '192.168.3.99', sources))
        record = recovery.record_for_packet(b'panic\nforged-record\xff', '192.168.3.181', sources)
        encoded = json.dumps(record)
        self.assertEqual(len(encoded.splitlines()), 1)
        self.assertEqual(record['source_node'], 'k8s-rpi7')
        self.assertLessEqual(len(recovery.record_for_packet(b'x' * 20000, '192.168.3.181', sources)['message']), 8192)

    def test_exact_target_configuration_and_idempotence_preserve_unmanaged_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config()
            for peer in config['receivers']:
                target = root / ('home_lab_' + peer['node'].replace('-', '_'))
                target.mkdir()
                for key, value in recovery.target_values(config, peer).items():
                    (target / key).write_text(value)
                (target / 'enabled').write_text('1')
            unmanaged = root / 'external';unmanaged.mkdir()
            with patch.object(recovery, 'TARGETS', root):
                recovery.configure(config)
                self.assertTrue(unmanaged.exists())
                target = root / 'home_lab_k8s_rpi1'
                (target / 'remote_mac').write_text('02:00:00:00:00:ff')
                recovery.configure(config)
                self.assertEqual((target / 'remote_mac').read_text(), config['receivers'][0]['mac'])
                self.assertEqual((target / 'enabled').read_text(), '1')

    def test_evidence_health_remains_valid_without_a_hardware_watchdog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config()
            for peer in config['receivers']:
                target = root / ('home_lab_' + peer['node'].replace('-', '_'))
                target.mkdir()
                for key, value in recovery.target_values(config, peer).items():
                    (target / key).write_text(value)
                (target / 'enabled').write_text('1')

            def no_watchdog_path(value):
                if str(value).startswith('/sys/class/watchdog'):
                    raise AssertionError('Evidence collection must not depend on watchdog hardware')
                return Path(value)

            with patch.object(recovery, 'TARGETS', root), patch.object(recovery, 'Path', side_effect=no_watchdog_path):
                state = recovery.inspect(config)
            self.assertEqual(state['netconsole_targets'], state['expected_targets'])
            self.assertFalse(state['is_receiver'])
            self.assertFalse(any('watchdog' in key for key in state))

    def test_disabled_target_is_not_disabled_again_kernel_returns_einval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config()
            for peer in config['receivers']:
                target = root / ('home_lab_' + peer['node'].replace('-', '_'))
                target.mkdir()
                for key, value in recovery.target_values(config, peer).items():
                    (target / key).write_text(value)
                (target / 'enabled').write_text('0')
            original = Path.write_text

            def kernel_write(path, value, *args, **kwargs):
                if path.name == 'enabled' and path.read_text() == value:
                    raise OSError(22, 'Configfs unchanged state')
                return original(path, value, *args, **kwargs)

            with patch.object(recovery, 'TARGETS', root), patch.object(Path, 'write_text', kernel_write):
                recovery.configure(config)
            for target in root.iterdir():
                self.assertEqual((target / 'enabled').read_text(), '1')


if __name__ == '__main__':
    unittest.main()
