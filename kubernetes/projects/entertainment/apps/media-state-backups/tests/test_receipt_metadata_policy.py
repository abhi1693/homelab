"""NAS metadata policy and anti-substitution checks; only disposable local files."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('receipt_metadata', APP / 'verify_backup_receipt.py')
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)
PRODUCTION = json.loads((APP / 'backup-storage-policy.json').read_text())


class ReceiptMetadataTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # Emulate the process after the privileged caller has dropped extra groups.
        groups = patch.object(VERIFY.os, "getgroups", return_value=[os.getegid()])
        groups.start()
        self.addCleanup(groups.stop)
        self.policy = deepcopy(PRODUCTION)
        self.policy['mapped_owner'] = {'uid': os.geteuid(), 'gid': os.getegid()}
        self.owner = self.root / 'ryokan'
        self.point_name = 'point-20261023T100000Z-0123456789abcdef0123456789abcdef'
        self.point = self.owner / self.point_name
        self.point.mkdir(parents=True)
        for path in [self.owner, self.point]:
            path.chmod(0o770)
        self.root.chmod(0o777)
        # Deliberately not a tar: metadata verification must never read/rehash it.
        self.archive = self.point / 'state.tar'
        self.archive.write_bytes(b'not a tar: metadata inspection only')
        self.archive.chmod(0o660)
        self.request = {'mount':str(self.root), 'uid':os.geteuid(), 'gid':os.getegid(),
            'owner':'ryokan', 'point':self.point_name, 'pod_uid':'11111111-2222-4333-8444-555555555555',
            'source_pvc':'ryokan-data', 'expected_source_pvc_uid':'22222222-3333-4444-8555-666666666666',
            'cohort':'ryokan-1.9.13', 'restored_verified':True,
            'termination':{'status':'verified', 'point':self.point_name,
                'archive_sha256':'a'*64, 'archive_bytes':self.archive.stat().st_size, 'file_count':208}}
        self.receipt = self.point / 'receipt.json'
        self.raw = VERIFY.expected_metadata(self.request, self.policy)
        self.write_receipt()

    def write_receipt(self):
        self.receipt.write_text(json.dumps(self.raw))
        self.receipt.chmod(0o660)

    def verify(self):
        return VERIFY.verify_receipt(self.request, self.policy)

    def test_production_policy_pins_reviewed_nas_boundary(self):
        self.assertEqual(PRODUCTION['mapped_owner'], {'uid':977, 'gid':988})
        self.assertFalse(PRODUCTION['owner_only'])
        self.assertFalse(PRODUCTION['encryption_claimed'])
        VERIFY.validate_policy(PRODUCTION)

    def test_effective_group_boundary_passes_without_owner_only_claim(self):
        result = self.verify()
        self.assertEqual(result['status'], 'PASS')
        self.assertFalse(result['owner_only'])
        self.assertEqual(result['directories']['claim_root']['mode'], '0777')
        self.assertEqual(result['files']['archive']['mode'], '0660')

    def test_stricter_existing_modes_pass_and_are_not_changed(self):
        for path in [self.owner, self.point]:path.chmod(0o700)
        for path in [self.receipt, self.archive]:path.chmod(0o600)
        result = self.verify()
        self.assertTrue(result['stricter_protected_modes_observed'])
        self.assertFalse(result['owner_only'])
        self.assertEqual(stat.S_IMODE(self.archive.stat().st_mode), 0o600)

    def test_archive_is_metadata_only_and_never_opened_for_body_read(self):
        original = os.open
        def checked(name, flags, *args, **kwargs):
            if name == 'state.tar':self.assertTrue(flags & os.O_PATH)
            return original(name, flags, *args, **kwargs)
        with patch.object(VERIFY.os, 'open', side_effect=checked):result = self.verify()
        self.assertFalse(result['archive_body_read'])
        self.assertFalse(result['archive_hash_recomputed'])
        self.assertFalse(result['key_data_read'])

    def test_world_special_and_executable_protected_modes_rejected(self):
        for path, mode in [(self.owner,0o777),(self.point,0o1770),
                           (self.archive,0o664),(self.archive,0o760),(self.receipt,0o4660)]:
            with self.subTest(mode=oct(mode)):
                prior=stat.S_IMODE(path.stat().st_mode);path.chmod(mode)
                with self.assertRaises(VERIFY.VerificationError):self.verify()
                path.chmod(prior)

    def test_already_unprivileged_reader_rejects_unexpected_supplementary_groups(self):
        with patch.object(VERIFY.os, "getgroups", return_value=[self.request["gid"], self.request["gid"] + 1]):
            with self.assertRaisesRegex(VERIFY.VerificationError, "unexpected_reader_supplementary_groups"):
                self.verify()

    def test_wrong_nas_owner_or_group_rejected(self):
        st=SimpleNamespace(st_mode=stat.S_IFREG|0o660,st_uid=977,st_gid=988,st_nlink=1)
        VERIFY.check_stat(st,'file',PRODUCTION)
        for field in ['st_uid','st_gid']:
            wrong=deepcopy(st);setattr(wrong,field,999)
            with self.assertRaises(VERIFY.VerificationError):VERIFY.check_stat(wrong,'file',PRODUCTION)

    def test_symlink_receipt_archive_owner_point_or_mount_rejected(self):
        for path in [self.receipt,self.archive,self.point,self.owner,self.root]:
            with self.subTest(path=path.name):
                moved=path.with_name(path.name+'-original');path.rename(moved);path.symlink_to(moved)
                with self.assertRaises((OSError,VERIFY.VerificationError)):self.verify()
                path.unlink();moved.rename(path)

    def test_intermediate_mount_symlink_rejected(self):
        link=self.root/'link';link.symlink_to(self.owner, target_is_directory=True)
        self.request['mount']=str(link/self.point_name)
        with self.assertRaises(OSError):self.verify()

    def test_hardlink_receipt_and_archive_rejected(self):
        for path in [self.receipt,self.archive]:
            linked=self.root/'external-link';os.link(path,linked)
            with self.assertRaises(VERIFY.VerificationError):self.verify()
            linked.unlink()

    def test_all_expected_identities_hash_counts_and_restore_state_are_bound(self):
        for key,value in [('pod_uid','33333333-4444-4555-8666-777777777777'),
                ('expected_source_pvc_uid','33333333-4444-4555-8666-777777777777'),
                ('cohort','different-cohort'),('point','point-20261023T100000Z-'+'b'*32),
                ('archive_sha256','b'*64),('archive_bytes',1),('file_count',1),
                ('restored_verified',False),('format',True)]:
            prior=self.raw[key];self.raw[key]=value;self.write_receipt()
            with self.subTest(key=key), self.assertRaises(VERIFY.VerificationError):self.verify()
            self.raw[key]=prior;self.write_receipt()

    def test_archive_size_drift_and_extra_point_contents_rejected(self):
        self.archive.write_bytes(b'changed size')
        with self.assertRaises(VERIFY.VerificationError):self.verify()
        self.archive.write_bytes(b'not a tar: metadata inspection only')
        extra=self.point/'unexpected';extra.write_text('never read')
        with self.assertRaises(VERIFY.VerificationError):self.verify()

    def test_oversized_duplicate_and_nonfinite_receipts_rejected(self):
        for body in ['x'*8193, '{"format":1,"format":1}', '{"format":NaN}']:
            self.receipt.write_text(body)
            with self.assertRaises((ValueError,VERIFY.VerificationError)):self.verify()

    def test_request_path_traversal_and_unverified_termination_rejected(self):
        for field,value in [('owner','../ryokan'),('point','../point'),('restored_verified',False)]:
            prior=self.request[field];self.request[field]=value
            with self.subTest(field=field),self.assertRaises(VERIFY.VerificationError):self.verify()
            self.request[field]=prior
        self.request['termination']['status']='pending'
        with self.assertRaises(VERIFY.VerificationError):self.verify()
