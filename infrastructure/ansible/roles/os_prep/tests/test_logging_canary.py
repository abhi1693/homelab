"""Verify the host canary contract consumed by the independent query checker."""

import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROGRAM = Path(__file__).resolve().parents[1] / 'files/home-lab-log-canary'


class LoggingCanaryTests(unittest.TestCase):
    def test_fixture_exposes_boot_identity_time_and_actual_spool_capacity(self):
        main = runpy.run_path(str(PROGRAM))['main']
        globals_ = main.__globals__
        with patch.object(globals_['os'], 'statvfs', return_value=SimpleNamespace(
                f_bavail=100, f_blocks=1024, f_frsize=4096)), \
                patch.object(globals_['os'], 'uname', return_value=SimpleNamespace(nodename='node-fixture')), \
                patch.object(globals_['time'], 'time', return_value=1793020000.7), \
                patch.object(globals_['Path'], 'read_text', return_value='00000000-1111-2222-3333-444444444444\n'), \
                patch.object(globals_['subprocess'], 'run') as send:
            main()
        command = send.call_args.args[0]
        self.assertEqual(command[:7], ['/usr/bin/logger', '--socket', '/run/systemd/journal/dev-log',
                                      '--priority', 'user.info', '--tag', 'home-lab-log-canary'])
        self.assertEqual(command[-2], '--')
        self.assertEqual(json.loads(command[-1]), {
            'event': 'os-log-canary', 'node': 'node-fixture',
            'boot_id': '00000000-1111-2222-3333-444444444444',
            'unix_time': 1793020000, 'queue_available_bytes': 409600,
            'queue_capacity_bytes': 4194304,
        })
        self.assertEqual(send.call_args.kwargs, {'check': True, 'timeout': 5})


if __name__ == '__main__':
    unittest.main()
