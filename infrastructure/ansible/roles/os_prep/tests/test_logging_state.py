"""Exercise filesystem safety guards against real disposable ext4 images."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROLE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('logging_state', ROLE / 'files/logging_state.py')
logging_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(logging_state)


@unittest.skipUnless(shutil.which('mkfs.ext4') and shutil.which('blkid'), 'ext4 tools required')
class LoggingFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.image = self.parent / 'otel-queue.ext4'
        self.mountpoint = self.parent / 'otel'
        self.mountpoint.mkdir()
        self.real_command = logging_state.command
        self.source = '/dev/nvme0n1p2'
        self.command_mock = patch.object(logging_state, 'command', self.run_command)
        self.command_mock.start()
        self.addCleanup(self.command_mock.stop)

    def run_command(self, *args):
        if args[0] == 'findmnt':
            return json.dumps({'filesystems': [{'source': self.source, 'fstype': 'ext4', 'target': '/'}]})
        return self.real_command(*args)

    def make_image(self, label='alloy-otel-queue'):
        with self.image.open('wb') as image:
            image.truncate(8 * 1024 * 1024)
        subprocess.run(['mkfs.ext4', '-q', '-m', '0', '-L', label, str(self.image)], check=True)

    def inspect(self, **kwargs):
        return logging_state.inspect(self.image, self.mountpoint, 8, 2, **kwargs)

    def test_recognized_unmounted_image_is_preserved_byte_for_byte(self):
        self.make_image()
        original = self.image.read_bytes()
        result = self.inspect()
        self.assertTrue(result['image_exists'])
        self.assertFalse(result['mounted'])
        self.assertEqual(original, self.image.read_bytes())

    def test_unrelated_ext4_image_is_rejected_without_changing_it(self):
        self.make_image(label='unrelated-data')
        original = self.image.read_bytes()
        with self.assertRaisesRegex(ValueError, 'unrecognized'):
            self.inspect()
        self.assertEqual(original, self.image.read_bytes())

    def test_nonempty_mountpoint_preserves_source_records_and_refuses_handover(self):
        self.make_image()
        existing = self.mountpoint / 'payloads.db'
        existing.write_text('existing queued evidence')
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            self.inspect()
        self.assertEqual(existing.read_text(), 'existing queued evidence')

    def test_resize_is_rejected(self):
        self.make_image()
        with self.assertRaisesRegex(ValueError, 'configured size'):
            logging_state.inspect(self.image, self.mountpoint, 16, 2)

    def test_symlink_is_rejected(self):
        self.make_image()
        linked = self.parent / 'linked'
        linked.symlink_to(self.image)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            logging_state.inspect(linked, self.mountpoint, 8, 2)

    def test_nas_backing_is_rejected_before_allocation(self):
        self.source = 'nas:/shared'
        with self.assertRaisesRegex(ValueError, 'NVMe'):
            self.inspect()
        self.assertFalse(self.image.exists())

    def test_validation_requires_the_actual_mount(self):
        self.make_image()
        with self.assertRaisesRegex(ValueError, 'not mounted'):
            self.inspect(validate=True)

    def test_free_space_reserve_stops_allocation_without_creating_an_image(self):
        class FullFilesystem:
            f_bavail = 1
            f_frsize = 4096

        with patch.object(logging_state.os, 'statvfs', return_value=FullFilesystem()):
            with self.assertRaisesRegex(ValueError, 'free-space reserve'):
                self.inspect()
        self.assertFalse(self.image.exists())


if __name__ == '__main__':
    unittest.main()
