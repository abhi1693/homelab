from pathlib import Path
import unittest,yaml
APP=Path(__file__).resolve().parents[1]
MANIFEST='rack-ops-controller.yaml'
SOURCE='rack-ops-state-nfs'
BUNDLE='rack-state-backups'
def load(name):return list(yaml.safe_load_all((APP/name).read_text()))[0]
class AppBackupContractTests(unittest.TestCase):
 def pod(self):return load(MANIFEST)['spec']['template']['spec']
 def test_single_stopped_writer_and_first_backup(self):
  deployment=load(MANIFEST);self.assertEqual(deployment['spec']['replicas'],1);self.assertEqual(deployment['spec']['strategy']['type'],'Recreate')
  self.assertEqual(self.pod()['initContainers'][0]['name'],'backup-state-before-start');self.assertEqual(deployment['spec']['progressDeadlineSeconds'],2400)
 def test_backup_only_mounts_own_readonly_source_and_no_app_credentials(self):
  pod=self.pod();c=pod['initContainers'][0];self.assertNotIn('envFrom',c)
  self.assertEqual({e['name'] for e in c['env']},{'POD_UID','PYTHONDONTWRITEBYTECODE','PYTHONUNBUFFERED','TMPDIR'})
  self.assertEqual(next(v for v in c['volumeMounts'] if v['name']=='state'),{'name':'state','mountPath':'/source','readOnly':True})
  self.assertFalse(any(v['mountPath']in['/git','/home/nonroot'] for v in c['volumeMounts']))
  self.assertEqual(next(v for v in pod['volumes'] if v['name']=='state')['persistentVolumeClaim']['claimName'],SOURCE)
  self.assertTrue(next(v for v in c['volumeMounts'] if v['name']=='prestart-no-api-token')['readOnly'])
  self.assertEqual(c['securityContext']['runAsUser'],65532);self.assertEqual(c['command'][0],'/usr/bin/python')
 def test_own_prerequisite_and_full_budget(self):
  fleet=load('fleet.yaml');self.assertIn({'name':BUNDLE},fleet['dependsOn']);self.assertEqual(fleet['helm']['timeoutSeconds'],2400)
 def test_existing_main_behavior_is_preserved(self):
  pod=self.pod()
  main=pod['containers'][0];self.assertNotIn('command',main)
  self.assertEqual(next(e['value'] for e in main['env'] if e['name']=='RACK_OPS_STATE'),'/state/rack-ops.json')
  policy=yaml.safe_load(load('rack-ops-policy.yaml')['data']['policy.yaml']);self.assertFalse(policy['dryRun'])
