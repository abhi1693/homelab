"""Exercise shutdown ordering with isolated kubectl/SSH fixtures; no host access."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
root=Path(os.environ['SHUTDOWN_FIXTURE'])
name=Path(sys.argv[0]).name
args=sys.argv[1:]
with (root/'calls').open('a') as stream:stream.write(json.dumps([name,args])+'\n')
if name=='sleep':sys.exit(0)
if name=='ssh':
 if args[-1]=='hostname':print(os.environ.get('REMOTE_HOST','k8s-rpi4'))
 elif 'poweroff' in args:(root/'powered-off').touch()
 elif os.environ.get('SUDO_FAIL')=='1':sys.exit(1)
 sys.exit(0)
if args[0]=='api-resources':print('volumes longhorn.io')
elif args[0]=='get' and args[1]=='nodes':
 for n in range(int(os.environ.get('PEERS','2'))):print('k8s-rpi'+str(n+1)+' Ready node-role.kubernetes.io/control-plane=true')
elif args[0]=='get' and args[1]=='node':
 if '--show-labels' in args:print('k8s-rpi4 Ready '+('node-role.kubernetes.io/control-plane=true' if os.environ.get('CONTROL_PLANE') else 'kubernetes.io/arch=arm64'))
 elif '-o' in args:
  if 'InternalIP' in args[-1]:print('192.0.2.4')
  else:print('False' if (root/'powered-off').exists() else 'True')
 else:print('k8s-rpi4')
elif 'volumes.longhorn.io' in args and os.environ.get('ATTACHED')=='1' and 'jsonpath=' in args[-1]:print('volume\tmedia\tbusy\t3')
elif args[0]=='drain' and os.environ.get('DRAIN_FAIL')=='1':sys.exit(1)
'''

class ShutdownTests(unittest.TestCase):
    def run_fixture(self, **overrides):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ['kubectl','ssh','sleep']:
                script=root/name;script.write_text(FIXTURE);script.chmod(0o755)
            env=os.environ.copy()
            env.update(PATH=str(root)+os.pathsep+env['PATH'],SHUTDOWN_FIXTURE=str(root),
                       LONGHORN_DETACH_TIMEOUT='0',SHUTDOWN_WAIT_TIMEOUT='0',**overrides)
            result=subprocess.run(['bash',str(ROOT/'scripts/safe-node-shutdown.sh'),'k8s-rpi4'],
                                  env=env,capture_output=True,text=True,timeout=10)
            calls=[json.loads(line) for line in (root/'calls').read_text().splitlines()]
            return result,calls

    def power_calls(self,calls):
        return [args for command,args in calls if command=='ssh' and 'poweroff' in args]

    def test_success_uses_internal_ip_and_powers_off_only_after_drain(self):
        result,calls=self.run_fixture()
        self.assertEqual(result.returncode,0,result.stderr)
        power=self.power_calls(calls)
        self.assertEqual(len(power),1)
        self.assertIn('192.0.2.4',power[0])
        self.assertEqual(power[0][-5:],['sudo','-n','systemctl','poweroff','--no-block'])
        drain=next(i for i,(command,args) in enumerate(calls) if command=='kubectl' and args[0]=='drain')
        off=next(i for i,(command,args) in enumerate(calls) if command=='ssh' and 'poweroff' in args)
        self.assertLess(drain,off)

    def test_identity_and_sudo_failure_leave_node_uncordoned(self):
        for case in [dict(REMOTE_HOST='different-node'),dict(SUDO_FAIL='1')]:
            result,calls=self.run_fixture(**case)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(self.power_calls(calls))
            self.assertFalse(any(command=='kubectl' and args[0]=='cordon' for command,args in calls))

    def test_drain_or_attached_storage_failure_prevents_poweroff(self):
        for case in [dict(DRAIN_FAIL='1'),dict(ATTACHED='1')]:
            result,calls=self.run_fixture(**case)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(self.power_calls(calls))

    def test_missing_etcd_quorum_prevents_ssh_or_cordon(self):
        result,calls=self.run_fixture(CONTROL_PLANE='1',PEERS='1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(command=='ssh' for command,args in calls))
        self.assertFalse(any(command=='kubectl' and args[0]=='cordon' for command,args in calls))
