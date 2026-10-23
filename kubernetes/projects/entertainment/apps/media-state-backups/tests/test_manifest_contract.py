import hashlib
from pathlib import Path
import re
import unittest
import yaml

APP=Path(__file__).resolve().parents[1]
ARTIFACT=(APP/'proposed').is_dir()
REPO=APP/'proposed' if ARTIFACT else APP.parents[4]
QB=REPO/'kubernetes/projects/entertainment/apps/media-qbittorrent'
RY=REPO/'kubernetes/projects/entertainment/apps/media-ryokan'
BK=REPO/'kubernetes/projects/entertainment/apps/media-state-backups'
def load(path):return list(yaml.safe_load_all(path.read_text()))[0]

class ManifestTests(unittest.TestCase):
    def specs(self):return [(load(QB/'smart-queues-controller.yaml'),65532,'smart-queues-state'),(load(RY/'deployment.yaml'),568,'data')]

    def test_existing_application_entrypoints_are_not_rewritten_for_helper_image(self):
        ryokan=load(RY/'deployment.yaml')['spec']['template']['spec']
        sidecar=next(c for c in ryokan['containers'] if c['name']=='import-reconciler')
        self.assertEqual(sidecar['command'],['python','-m','qbittorrent_smart_queues.ryokan_reconciler'])
        sync=next(c for c in ryokan['initContainers'] if c['name']=='sync-qbittorrent-credentials')
        # Credential init has a separately reviewed stdlib-only image/runtime contract.
        self.assertEqual(sync['command'][:2],['/usr/bin/python','-c'])
        self.assertEqual(sync['image'],__import__('json').loads((BK/'public-helper-image.json').read_text())['image'])
        self.assertNotIn('command',next(c for c in ryokan['containers'] if c['name']=='ryokan'))
        qbit=load(QB/'smart-queues-controller.yaml')['spec']['template']['spec']['containers'][0]
        self.assertNotIn('command',qbit)

    def test_first_init_and_recreate_preserved(self):
        for deployment,_,_ in self.specs():
            self.assertEqual(deployment['spec']['replicas'],1)
            self.assertEqual(deployment['spec']['strategy']['type'],'Recreate')
            init=deployment['spec']['template']['spec']['initContainers']
            self.assertEqual(init[0]['name'],'backup-state-before-start')
            if deployment['metadata']['name']=='ryokan':
                self.assertEqual(init[1]['name'],'sync-qbittorrent-credentials')
                main=deployment['spec']['template']['spec']['containers'][0]['image']
                self.assertRegex(main,r'ryokan:[0-9]+\.[0-9]+\.[0-9]+@sha256:[0-9a-f]{64}$')
                version=main.split('ryokan:',1)[1].split('@',1)[0]
                args=init[0]['args'];self.assertIn('ryokan-'+version,args[args.index('--cohort')+1])

    def test_init_no_credentials_nonroot_and_source_readonly(self):
        for deployment,uid,volume in self.specs():
            init=deployment['spec']['template']['spec']['initContainers'][0]
            self.assertNotIn('envFrom',init)
            self.assertEqual({e['name'] for e in init['env']},{'POD_UID','PYTHONDONTWRITEBYTECODE','PYTHONUNBUFFERED','TMPDIR'})
            self.assertEqual(init['securityContext']['runAsUser'],uid)
            self.assertEqual(init['securityContext']['runAsGroup'],uid)
            self.assertEqual(init['securityContext']['capabilities']['drop'],['ALL'])
            self.assertTrue(init['securityContext']['readOnlyRootFilesystem'])
            self.assertTrue(next(v for v in init['volumeMounts'] if v['name']==volume)['readOnly'])
            self.assertEqual(init['command'],['/usr/bin/python','/backup-helper/backup_state.py'])
            image=init['image']
            self.assertRegex(image,r'^cgr\.dev/chainguard/python:latest@sha256:[0-9a-f]{64}$')
            self.assertEqual(image,__import__('json').loads((BK/'public-helper-image.json').read_text())['image'])

    def test_token_is_masked_only_for_backup_main_stays_unchanged(self):
        deployment=load(QB/'smart-queues-controller.yaml');pod=deployment['spec']['template']['spec']
        self.assertTrue(pod['automountServiceAccountToken'])
        mount=next(m for m in pod['initContainers'][0]['volumeMounts'] if m['name']=='prestart-no-api-token')
        self.assertEqual(mount['mountPath'],'/var/run/secrets/kubernetes.io/serviceaccount')
        self.assertTrue(mount['readOnly'])
        self.assertEqual(next(e['value'] for e in pod['containers'][0]['env'] if e['name']=='QBT_STOP_DOWNLOADS_ON_SHUTDOWN'),'true')
        self.assertFalse(load(RY/'deployment.yaml')['spec']['template']['spec']['automountServiceAccountToken'])

    def test_shared_script_exact_hash_and_independent_destination_claims(self):
        helper=(BK/'backup_state.py').read_bytes();cm=load(BK/'backup-state-configmap.yaml')
        self.assertEqual(cm['data']['backup_state.py'].encode(),helper)
        self.assertEqual(cm['metadata']['name'],'media-prestart-backup-'+hashlib.sha256(helper).hexdigest()[:12])
        self.assertTrue(cm['immutable'])
        claims=[]
        for deployment,_,_ in self.specs():
            pod=deployment['spec']['template']['spec']
            self.assertEqual(next(v for v in pod['volumes'] if v['name']=='prestart-backup-helper')['configMap']['name'],cm['metadata']['name'])
            claims.append(next(v for v in pod['volumes'] if v['name']=='prestart-backup-destination')['persistentVolumeClaim']['claimName'])
        self.assertEqual(len(set(claims)),2)
        for p in [BK/'controller-backup-pvc.yaml',BK/'ryokan-backup-pvc.yaml']:
            pvc=load(p);self.assertEqual(pvc['metadata']['annotations']['helm.sh/resource-policy'],'keep')
            self.assertEqual(pvc['spec']['storageClassName'],'nfs-shared-retain')

    def test_scratch_requests_limits_match_and_retention_bounded(self):
        for deployment,_,_ in self.specs():
            pod=deployment['spec']['template']['spec'];init=pod['initContainers'][0]
            work=next(v for v in pod['volumes'] if v['name']=='prestart-backup-work')['emptyDir']['sizeLimit']
            self.assertEqual(init['resources']['requests']['ephemeral-storage'],work)
            self.assertEqual(init['resources']['limits']['ephemeral-storage'],work)
            args=init['args'];self.assertEqual(args[args.index('--retention')+1],'3')
            self.assertEqual(args[args.index('--timeout')+1],'1800')

    def test_rollout_budgets_cover_backup_and_normal_startup(self):
        for deployment,_,_ in self.specs():self.assertGreaterEqual(deployment["spec"]["progressDeadlineSeconds"],2400)
        for path in [QB/"fleet.yaml",RY/"fleet.yaml"]:self.assertGreaterEqual(load(path)["helm"]["timeoutSeconds"],2400)

    def test_ryokan_waits_for_helper_bundle_and_ci_watches_sources(self):
        for app in [QB,RY]:self.assertIn({'name':'media-state-backups'},load(app/'fleet.yaml')['dependsOn'])
        workflow=(REPO/'.github/workflows/infrastructure-regressions.yml').read_text()
        for name in ['media-qbittorrent','media-ryokan','media-state-backups']:
            self.assertEqual(workflow.count(f'kubernetes/projects/entertainment/apps/{name}/**'),2)

    def test_storage_acceptance_hook_waits_and_has_bounded_evidence_retention(self):
        fleet=load(BK/'fleet.yaml');self.assertTrue(fleet['helm']['waitForJobs'])
        self.assertGreaterEqual(fleet['helm']['timeoutSeconds'],300)
        job=load(BK/'storage-validation-job.yaml');annotations=job['metadata']['annotations']
        self.assertEqual(annotations['helm.sh/hook'],'post-install,post-upgrade')
        self.assertEqual(annotations['helm.sh/hook-delete-policy'],'before-hook-creation')
        self.assertEqual(job['spec']['ttlSecondsAfterFinished'],86400)
        self.assertEqual(job['spec']['activeDeadlineSeconds'],180)
        self.assertEqual(job['spec']['backoffLimit'],1)
        self.assertEqual(job['spec']['parallelism'],1)

    def test_storage_acceptance_has_both_real_uids_no_source_secrets_or_api(self):
        job=load(BK/'storage-validation-job.yaml');pod=job['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertNotIn('imagePullSecrets',pod)
        self.assertNotIn('fsGroup',pod['securityContext'])
        self.assertEqual(pod['restartPolicy'],'Never')
        self.assertEqual({c['securityContext']['runAsUser'] for c in pod['containers']},{568,65532})
        self.assertEqual({v['persistentVolumeClaim']['claimName'] for v in pod['volumes'] if 'persistentVolumeClaim' in v},
                         {'qbittorrent-smart-queues-backup-nfs','ryokan-prestart-backup-nfs'})
        self.assertFalse(any('secret' in v for v in pod['volumes']))
        for container in pod['containers']:
            self.assertNotIn('envFrom',container)
            self.assertTrue(container['securityContext']['readOnlyRootFilesystem'])
            self.assertEqual(container['securityContext']['capabilities']['drop'],['ALL'])
            self.assertEqual(len(container['volumeMounts']),2)
            self.assertIn('--validate-destination',container['args'])
            self.assertNotIn('--source',container['args'])
            self.assertEqual(container['image'],self.specs()[0][0]['spec']['template']['spec']['initContainers'][0]['image'])
        network=load(BK/'storage-validation-networkpolicy.yaml')
        self.assertEqual(network['spec']['ingress'],[]);self.assertEqual(network['spec']['egress'],[])

if __name__=='__main__':unittest.main()
