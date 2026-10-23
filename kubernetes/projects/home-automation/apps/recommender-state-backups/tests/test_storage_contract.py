import hashlib,json
from pathlib import Path
import unittest,yaml
APP=Path(__file__).resolve().parents[1]
NS='cluster-ops'
CLAIM='recommender-state-backup-nfs'
APPOWNER='cluster-ops'
def load(name):return yaml.safe_load((APP/name).read_text())
class StoragePrerequisiteTests(unittest.TestCase):
 def test_namespace_is_created_normally_without_owned_namespace_or_metadata_transfer(self):
  fleet=load('fleet.yaml');self.assertEqual(fleet['defaultNamespace'],NS);self.assertTrue(fleet['createNamespace'])
  self.assertNotIn('namespaceLabels',fleet);self.assertNotIn('namespaceAnnotations',fleet)
  self.assertNotIn({'name':APPOWNER},fleet['dependsOn'])
  for rel in load('kustomization.yaml')['resources']:
   self.assertNotIn(load(rel)['kind'],['Namespace','Secret','SopsSecret','ServiceAccount','Role','RoleBinding','ClusterRole','ClusterRoleBinding'])
 def test_public_image_and_immutable_script_are_locally_locked(self):
  lock=json.loads((APP/'public-helper-image.json').read_text());cm=load('backup-state-configmap.yaml')
  self.assertTrue(cm['immutable']);sha=hashlib.sha256(cm['data']['backup_state.py'].encode()).hexdigest()
  self.assertEqual(sha,lock['helperSHA256']);self.assertEqual(cm['metadata']['name'],'media-prestart-backup-'+sha[:12])
  self.assertRegex(lock['image'],r'^cgr\.dev/chainguard/python:latest@sha256:[0-9a-f]{64}$')
 def test_hook_and_retention_are_normal_and_bounded(self):
  fleet=load('fleet.yaml');self.assertTrue(fleet['helm']['waitForJobs']);self.assertEqual(fleet['helm']['timeoutSeconds'],300)
  job=load('storage-validation-job.yaml');a=job['metadata']['annotations']
  self.assertEqual(a['helm.sh/hook'],'post-install,post-upgrade');self.assertEqual(a['helm.sh/hook-delete-policy'],'before-hook-creation')
  self.assertEqual(job['spec']['ttlSecondsAfterFinished'],86400);self.assertEqual(job['spec']['activeDeadlineSeconds'],180)
  self.assertEqual(job['spec']['backoffLimit'],1)
 def test_validation_has_no_source_credentials_token_or_network_operation(self):
  job=load('storage-validation-job.yaml');pod=job['spec']['template']['spec'];c=pod['containers'][0]
  self.assertEqual(job['metadata']['namespace'],NS);self.assertFalse(pod['automountServiceAccountToken']);self.assertNotIn('imagePullSecrets',pod)
  self.assertEqual([v['persistentVolumeClaim']['claimName'] for v in pod['volumes'] if 'persistentVolumeClaim'in v],[CLAIM])
  self.assertNotIn('envFrom',c);self.assertNotIn('--source',c['args']);self.assertIn('--validate-destination',c['args'])
  self.assertEqual(c['securityContext']['runAsUser'],65532);self.assertTrue(c['securityContext']['readOnlyRootFilesystem']);self.assertEqual(c['securityContext']['capabilities']['drop'],['ALL'])
  self.assertEqual(c['image'],json.loads((APP/'public-helper-image.json').read_text())['image']);self.assertEqual(c['command'][0],'/usr/bin/python')
  self.assertEqual(load('storage-validation-networkpolicy.yaml')['spec']['egress'],[])
 def test_retained_claim_is_new_and_in_its_own_existing_namespace(self):
  pvc=load('backup-pvc.yaml');self.assertEqual(pvc['metadata']['name'],CLAIM);self.assertEqual(pvc['metadata']['namespace'],NS)
  self.assertEqual(pvc['metadata']['annotations']['helm.sh/resource-policy'],'keep');self.assertEqual(pvc['spec']['storageClassName'],'nfs-shared-retain')

 def test_canonical_producer_and_public_image_match_without_a_fork(self):
  canonical=APP.parents[2]/'entertainment/apps/media-state-backups'
  cm=load('backup-state-configmap.yaml');shared=yaml.safe_load((canonical/'backup-state-configmap.yaml').read_text())
  self.assertEqual(cm['data']['backup_state.py'],shared['data']['backup_state.py'])
  self.assertEqual(hashlib.sha256(cm['data']['backup_state.py'].encode()).hexdigest(),'c24c14a3317cbbd4cdbd2e152fb5639191da6d7d7ad45e4608bd4b2d3a50938d')
  lock=json.loads((APP/'public-helper-image.json').read_text());self.assertEqual(lock['image'],json.loads((canonical/'public-helper-image.json').read_text())['image'])
  self.assertFalse((APP/'backup_state.py').exists());self.assertFalse((APP/'verify_backup_receipt.py').exists());self.assertFalse((APP/'backup-storage-policy.json').exists())
 def test_metadata_is_excluded_and_job_tracks_public_docker_package(self):
  ignored=(APP/'.fleetignore').read_text().splitlines()
  for name in ['README.md','public-helper-image.json','tests/','__pycache__/']:self.assertIn(name,ignored)
  lines=(APP/'storage-validation-job.yaml').read_text().splitlines();index=next(i for i,line in enumerate(lines) if line.strip().startswith('image:'))
  self.assertEqual(lines[index-1].strip(),'# renovate: datasource=docker depName=cgr.dev/chainguard/python')
