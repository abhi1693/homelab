"""Exercise the actual firmware helper and bounded reboot guards without a host."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ansible.plugins.filter.core import FilterModule
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import yaml


TASK_DIRECTORY = Path(__file__).resolve().parents[1] / 'tasks'
FIRMWARE_TASKS = yaml.safe_load((TASK_DIRECTORY / 'os_updates_firmware.yml').read_text())
CODE = FIRMWARE_TASKS[0]['ansible.builtin.command']['argv'][2]
ENVIRONMENT = NativeEnvironment(undefined=StrictUndefined)
ENVIRONMENT.filters.update(FilterModule().filters())


def all_tasks(value):
    for item in value:
        yield item
        for child in ('block', 'rescue', 'always'):
            yield from all_tasks(item.get(child, []))


class FirmwareRebootTests(unittest.TestCase):
    def inspect(self, marker=None, pending_files=(), file_timestamp=9500, service_status=0):
        real_path = Path
        with tempfile.TemporaryDirectory() as directory:
            root = real_path(directory)
            (root / 'boot/firmware').mkdir(parents=True)
            (root / 'run').mkdir()
            if marker is not None:
                (root / 'run/rpi-eeprom-update-pending').write_text(marker)
            for name in pending_files:
                pending_file = root / 'boot/firmware' / name
                pending_file.touch()
                os.utime(pending_file, (file_timestamp, file_timestamp))

            def mapped_path(*parts):
                path = real_path(*parts)
                self.assertTrue(str(path).startswith(('/boot/firmware', '/run/')))
                return root / path.relative_to('/')

            # A newer optional release is present, while CURRENT remains above
            # the silent-update minimum. Version difference alone is not pending.
            status = {
                'EXITCODE': 'EXIT_UPDATE_REQUIRED',
                'BOOTLOADER_CURRENT': 100,
                'BOOTLOADER_LATEST': 200,
                'BOOTLOADER_MINIMUM': 50,
            }

            def run(argv, **kwargs):
                if argv[0] == 'rpi-eeprom-update':
                    self.assertEqual(argv, ['rpi-eeprom-update', '-j', '-m', '/dev/stdout'])
                    return SimpleNamespace(returncode=1, stdout=json.dumps(status), stderr='')
                self.assertEqual(argv, ['systemctl', 'is-enabled', 'rpi-eeprom-update.service'])
                return SimpleNamespace(returncode=0, stdout='enabled\n', stderr='')

            service = ('Result=' + ('success' if service_status == 0 else 'exit-code') + '\n'
                       'ExecMainStatus=' + str(service_status) + '\n'
                       'ActiveState=active\nSubState=exited\n')
            output = io.StringIO()
            with patch('pathlib.Path', side_effect=mapped_path), \
                    patch('subprocess.run', side_effect=run), \
                    patch('subprocess.check_output', return_value=service), \
                    patch('time.time', return_value=10000), \
                    patch('time.clock_gettime', return_value=1000), \
                    redirect_stdout(output):
                # Render the actual task body before compiling, as Ansible does.
                rendered = ENVIRONMENT.from_string(CODE).render()
                exec(compile(rendered, 'os_updates_firmware.yml:inline-python', 'exec'), {})
            return json.loads(output.getvalue())

    def test_optional_latest_version_does_not_request_a_reboot(self):
        state = self.inspect()
        self.assertFalse(state['reboot_pending'])
        self.assertFalse(state['pending_staged_this_boot'])

    def test_successful_immediate_spi_update_requires_reboot_without_boot_files(self):
        state = self.inspect(marker='immediate 9500\n')
        self.assertTrue(state['reboot_pending'])
        self.assertTrue(state['pending_staged_this_boot'])
        self.assertEqual(state['pending_files'], [])
        self.assertEqual(state['pending_marker'], {'mode': 'immediate', 'recorded_at': 9500})
        self.assertEqual(state['BOOTLOADER_CURRENT'], 100)

    def test_recovery_marker_and_fresh_boot_files_require_a_reboot(self):
        state = self.inspect(marker='recovery 9500\n', pending_files=('pieeprom.upd', 'pieeprom.sig'))
        self.assertTrue(state['reboot_pending'])
        self.assertTrue(state['pending_staged_this_boot'])

    def test_legacy_updater_fresh_boot_files_still_require_a_reboot(self):
        state = self.inspect(pending_files=('pieeprom.upd',))
        self.assertTrue(state['reboot_pending'])
        self.assertTrue(state['pending_staged_this_boot'])

    def test_stale_marker_stops_instead_of_rebooting(self):
        with self.assertRaisesRegex(RuntimeError, 'not from the current boot'):
            self.inspect(marker='immediate 8990\n')

    def test_future_marker_stops_instead_of_rebooting(self):
        with self.assertRaisesRegex(RuntimeError, 'not from the current boot'):
            self.inspect(marker='immediate 10020\n')

    def test_unknown_marker_format_stops_instead_of_rebooting(self):
        with self.assertRaisesRegex(RuntimeError, 'unrecognized format'):
            self.inspect(marker='immediate\n')

    def test_old_boot_files_cannot_borrow_current_marker_proof(self):
        state = self.inspect(marker='immediate 9500\n', pending_files=('recovery.bin',), file_timestamp=8990)
        self.assertTrue(state['reboot_pending'])
        self.assertFalse(state['pending_staged_this_boot'])

    def test_failed_updater_cannot_request_the_second_reboot(self):
        with self.assertRaisesRegex(RuntimeError, 'service failed'):
            self.inspect(marker='immediate 9500\n', service_status=2)

    def test_consumed_update_has_no_pending_state_on_the_next_boot(self):
        self.assertTrue(self.inspect(marker='immediate 9500\n')['reboot_pending'])
        self.assertFalse(self.inspect()['reboot_pending'])

    def test_marker_only_state_triggers_both_reboot_guards(self):
        tasks = list(all_tasks(yaml.safe_load((TASK_DIRECTORY / 'os_updates.yml').read_text())))
        first = next(item for item in tasks if item['name'] == 'Reboot this node to load updated kernel and userspace components')
        second = next(item for item in tasks if item['name'] == 'Complete a firmware update recorded by the existing OS updater')
        context = {
            'os_prep_os_packages_update': {'changed': False},
            'os_prep_os_reboot_required': {'stat': {'exists': False}},
            'os_prep_os_kernel_state': {'stdout': json.dumps({'running_kernel': 'same', 'expected_kernel': 'same'})},
            'os_prep_os_firmware_state': {'stdout': json.dumps(self.inspect(marker='immediate 9500\n'))},
        }
        self.assertTrue(ENVIRONMENT.compile_expression(first['when'])(context))
        self.assertTrue(ENVIRONMENT.compile_expression(second['when'])(context))
        self.assertEqual(sum('ansible.builtin.reboot' in item for item in tasks), 2)

    def test_final_validation_rejects_marker_only_pending_state(self):
        tasks = yaml.safe_load((TASK_DIRECTORY / 'os_updates_validation.yml').read_text())
        task = next(item for item in tasks if item['name'] == 'Assert no automatic firmware update still requires a reboot')
        expression = task['ansible.builtin.assert']['that'][0]
        self.assertFalse(ENVIRONMENT.compile_expression(expression)(
            os_prep_os_firmware_state={'stdout': json.dumps(self.inspect(marker='immediate 9500\n'))}))
        self.assertTrue(ENVIRONMENT.compile_expression(expression)(
            os_prep_os_firmware_state={'stdout': json.dumps(self.inspect())}))


if __name__ == '__main__':
    unittest.main()
