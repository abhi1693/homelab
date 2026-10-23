import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('backup_state', ROOT / 'backup_state.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.dest, self.work = [self.root / x for x in ['source','dest','work']]
        for p in [self.source,self.dest,self.work]: p.mkdir()
        self.connections=[]
        self.addCleanup(lambda:[c.close() for c in self.connections])

    def controller(self):
        (self.source/'torrent-health.json').write_text('{"torrents":{"synthetic":1}}')
        (self.source/'udm-usage-corrections.json').write_text('{"corrections":[]}')

    def ryokan(self):
        c=sqlite3.connect(self.source/'ryokan.db');self.connections.append(c)
        c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA wal_autocheckpoint=0')
        c.executescript('CREATE TABLE schema_migrations(id TEXT PRIMARY KEY);CREATE TABLE receipts(id INTEGER PRIMARY KEY,value TEXT);')
        c.execute('INSERT INTO schema_migrations VALUES(?)',('migration_text_v1',));c.commit()
        c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        # These committed records exist ONLY in WAL; naive DB-only backup loses them.
        c.execute('INSERT INTO schema_migrations VALUES(?)',('wal_text_v2',))
        c.execute('INSERT INTO receipts VALUES(1,?)',('private-synthetic-receipt',));c.commit()
        key=self.source/'.ryokan-key';key.write_bytes(bytes(range(32)));key.chmod(0o660)
        (self.source/'cache/artwork').mkdir(parents=True)
        (self.source/'cache/artwork/poster.bin').write_bytes(b'public-fixture-artwork')
        (self.source/'import-reconciler.json').write_text('{"synthetic":true}')
        return c

    def run_backup(self,app='controller',**kwargs):
        return b.run_backup(app,self.source,self.dest,self.work,'synthetic-pod','qbit-0.2.13',
                            scratch_reserve=0,destination_reserve=0,**kwargs)

    def restore(self,receipt,app):
        archive=self.dest/b.OWNER[app]/receipt['point']/'state.tar'
        with tarfile.open(archive) as t:
            manifest=json.load(t.extractfile('manifest.json'))
        target=self.root/'operator-restore'
        b.restore_verify(archive,target,manifest)
        return target,manifest

    def test_controller_roundtrip_optional_absence_modes_and_private_destination(self):
        self.controller();(self.source/'empty').mkdir()
        before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.source.iterdir() if p.is_file()}
        r=self.run_backup();out,m=self.restore(r,'controller')
        self.assertEqual((out/'torrent-health.json').read_bytes(),before['torrent-health.json'][0])
        self.assertFalse((out/'rpi-cooling.json').exists());self.assertTrue((out/'empty').is_dir())
        self.assertEqual(stat.S_IMODE((self.dest/b.OWNER['controller']).stat().st_mode),0o700)
        for p in (self.dest/b.OWNER['controller']/r['point']).iterdir():self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o600)
        self.assertEqual(before,{p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.source.iterdir() if p.is_file()})
        self.assertFalse(list(self.work.iterdir()))

    def test_sqlite_wal_text_migrations_key_artwork_sidecar_and_no_source_mutation(self):
        self.ryokan()
        before={str(p.relative_to(self.source)):(b.digest(p),p.stat().st_mtime_ns) for p in self.source.rglob('*') if p.is_file()}
        # Baseline main DB lacks WAL-only row: proves test would catch DB-only copy.
        raw=self.root/'main-only.db';shutil.copyfile(self.source/'ryokan.db',raw)
        with sqlite3.connect(raw) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM receipts').fetchone()[0],0)
        r=self.run_backup('ryokan');out,m=self.restore(r,'ryokan')
        with sqlite3.connect(out/'ryokan.db') as c:
            self.assertEqual(c.execute('SELECT value FROM receipts').fetchone()[0],'private-synthetic-receipt')
            self.assertEqual(b.database_fingerprint(c),m['database'])
        self.assertEqual(m['database']['migration_ids'],['migration_text_v1','wal_text_v2'])
        self.assertEqual((out/'.ryokan-key').read_bytes(),bytes(range(32)))
        self.assertEqual((out/'cache/artwork/poster.bin').read_bytes(),b'public-fixture-artwork')
        self.assertTrue((out/'import-reconciler.json').is_file())
        self.assertEqual(before,{str(p.relative_to(self.source)):(b.digest(p),p.stat().st_mtime_ns) for p in self.source.rglob('*') if p.is_file()})
        self.assertFalse((out/'ryokan.db-wal').exists())
        self.assertNotIn('migration_ids',r);self.assertNotIn('.ryokan-key',json.dumps(r))

    def test_missing_source_shm_still_recovers_committed_wal_in_scratch(self):
        self.ryokan();(self.source/'ryokan.db-shm').unlink()
        r=self.run_backup('ryokan');out,_=self.restore(r,'ryokan')
        with sqlite3.connect(out/'ryokan.db') as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM receipts').fetchone()[0],1)
        self.assertFalse((self.source/'ryokan.db-shm').exists())

    def test_invalid_json_blocks_completion(self):
        self.controller();(self.source/'torrent-health.json').write_text('{bad')
        with self.assertRaises(b.BackupError):self.run_backup()
        self.assertFalse(list(self.dest.iterdir()))

    def test_duplicate_json_key_blocks(self):
        self.controller();(self.source/'torrent-health.json').write_text('{"a":1,"a":2}')
        with self.assertRaises(b.BackupError):self.run_backup()

    def test_json_nan_blocks(self):
        self.controller();(self.source/'torrent-health.json').write_text('{"a":NaN}')
        with self.assertRaises(b.BackupError):self.run_backup()

    def test_missing_required_controller_state_blocks(self):
        self.controller();(self.source/'torrent-health.json').unlink()
        with self.assertRaises(b.BackupError):self.run_backup()

    def test_missing_private_key_blocks(self):
        self.ryokan();(self.source/'.ryokan-key').unlink()
        with self.assertRaises(b.BackupError):self.run_backup('ryokan')

    def test_world_readable_private_key_blocks(self):
        self.ryokan();(self.source/'.ryokan-key').chmod(0o664)
        with self.assertRaises(b.BackupError):self.run_backup('ryokan')

    def test_corrupt_database_blocks_and_retains_prior_point(self):
        self.ryokan();r=self.run_backup('ryokan')
        with (self.source/'ryokan.db').open('r+b') as f:f.write(b'not SQLite')
        with self.assertRaises(Exception):self.run_backup('ryokan')
        self.assertTrue((self.dest/'ryokan'/r['point']/'receipt.json').is_file())

    def test_pending_restore_and_auth_reset_each_block(self):
        self.ryokan()
        for name in b.FORBIDDEN:
            p=self.source/name;p.touch()
            with self.assertRaises(b.BackupError):self.run_backup('ryokan')
            p.unlink()

    def test_symlink_and_hardlink_block(self):
        self.controller();p=self.source/'escape';p.symlink_to('/etc/passwd')
        with self.assertRaises(b.BackupError):self.run_backup()
        p.unlink();p.hardlink_to(self.source/'torrent-health.json')
        with self.assertRaises(b.BackupError):self.run_backup()

    def test_existing_backup_artifacts_are_not_recursively_archived(self):
        self.ryokan();(self.source/'backups').mkdir();(self.source/'backups/prior.tar.gz').write_bytes(b'old')
        for rel in b.RYOKAN_EXCLUDE - {'backups','ryokan.db','ryokan.db-wal','ryokan.db-shm'}:
            path=self.source/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'old')
        r=self.run_backup('ryokan');_,m=self.restore(r,'ryokan')
        self.assertFalse(any(p in b.RYOKAN_EXCLUDE - {'ryokan.db'} for p in m['files']))
        for rel in b.RYOKAN_EXCLUDE - {'backups','ryokan.db','ryokan.db-wal','ryokan.db-shm'}:self.assertEqual((self.source/rel).read_bytes(),b'old')

    def test_source_size_bound_blocks_before_write(self):
        self.controller()
        with self.assertRaises(b.BackupError):self.run_backup(max_source=1)
        self.assertFalse(list(self.dest.iterdir()))

    def test_scratch_bound_blocks_before_write(self):
        self.controller()
        with self.assertRaises(b.BackupError):self.run_backup(max_work=1)
        self.assertFalse(list(self.dest.iterdir()))

    def test_full_node_or_destination_blocks_before_write(self):
        self.controller()
        with patch.object(b.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(10,10,0)):
            with self.assertRaises(b.BackupError):self.run_backup()
        self.assertFalse(list(self.dest.iterdir()))

    def test_failed_readback_publishes_nothing_and_does_not_prune(self):
        self.controller();r=self.run_backup()
        with patch.object(b,'restore_verify',side_effect=b.BackupError('synthetic readback failure')):
            with self.assertRaises(b.BackupError):self.run_backup()
        self.assertEqual(len(b.completed_points(self.dest/b.OWNER['controller'],'controller')),1)
        self.assertTrue((self.dest/b.OWNER['controller']/r['point']).exists())
        self.assertFalse(any(p.name.startswith('.partial') for p in (self.dest/b.OWNER['controller']).iterdir()))

    def test_corrupt_archive_readback_blocks_completion(self):
        self.controller();original=b.make_archive
        def corrupt(path,*args):
            original(path,*args)
            with path.open('r+b') as f:f.seek(1024);f.write(b'CORRUPTED')
        with patch.object(b,'make_archive',side_effect=corrupt):
            with self.assertRaises(Exception):self.run_backup()
        self.assertFalse(list((self.dest/b.OWNER['controller']).iterdir()))

    def test_retention_only_completed_owned_points(self):
        self.controller();root=self.dest/b.OWNER['controller'];root.mkdir();(root/'unrelated.txt').write_text('keep');(root/'.partial-other').mkdir()
        for _ in range(5):self.run_backup(retention=2)
        self.assertEqual(len(b.completed_points(root,'controller')),2)
        self.assertTrue((root/'unrelated.txt').exists());self.assertTrue((root/'.partial-other').exists())

    def test_corrupt_old_receipt_blocks_and_never_prunes(self):
        self.controller();r=self.run_backup();p=self.dest/b.OWNER['controller']/r['point']/'receipt.json';p.write_text('{"owner":"other"}')
        with self.assertRaises(b.BackupError):self.run_backup()
        self.assertTrue(p.is_file())

    def test_completed_receipt_requires_restore_verified_flag(self):
        self.controller();r=self.run_backup();p=self.dest/b.OWNER["controller"]/r["point"]/"receipt.json"
        receipt=json.loads(p.read_text());receipt["restored_verified"]=False;p.write_text(json.dumps(receipt))
        with self.assertRaises(b.BackupError):self.run_backup()
        self.assertTrue(p.exists())

    def test_unsafe_destination_symlink_blocks(self):
        self.controller();(self.dest/b.OWNER['controller']).symlink_to(self.work,target_is_directory=True)
        with self.assertRaises(b.BackupError):self.run_backup()
        self.assertFalse(list(self.work.iterdir()))

    def test_source_changes_during_copy_blocks(self):
        self.controller();original=b.make_archive
        # Final source guard runs before tar; inject during copy for meaningful failure.
        copy=shutil.copyfile
        def racing(src,dst,*args,**kw):
            result=copy(src,dst,*args,**kw)
            if Path(src).name=='torrent-health.json':Path(src).write_text('{"changed":true}')
            return result
        with patch.object(b.shutil,'copyfile',side_effect=racing):
            with self.assertRaises(b.BackupError):self.run_backup()

    def test_destination_acceptance_checks_contract_without_source_or_backup_points(self):
        self.controller();r=self.run_backup();point=self.dest/b.OWNER['controller']/r['point']
        before={str(p.relative_to(self.source)):b.digest(p) for p in self.source.rglob('*') if p.is_file()}
        point_before={p.name:b.digest(p) for p in point.iterdir()}
        result=b.validate_destination('controller',self.dest,'storage-fixture')
        self.assertEqual(result['status'],'storage-verified')
        self.assertEqual(point_before,{p.name:b.digest(p) for p in point.iterdir()})
        self.assertEqual(before,{str(p.relative_to(self.source)):b.digest(p) for p in self.source.rglob('*') if p.is_file()})
        self.assertFalse(any(p.name.startswith('.validate') for p in point.parent.iterdir()))

    def test_destination_acceptance_fsync_failure_preserves_existing_points_and_source(self):
        self.controller();r=self.run_backup();point=self.dest/b.OWNER['controller']/r['point']
        before={p.name:b.digest(p) for p in point.iterdir()}
        source_before={p.name:b.digest(p) for p in self.source.iterdir()}
        with patch.object(b,'sync_dir',side_effect=OSError('synthetic directory fsync unavailable')):
            with self.assertRaises(OSError):b.validate_destination('controller',self.dest,'storage-fixture')
        self.assertEqual(before,{p.name:b.digest(p) for p in point.iterdir()})
        self.assertEqual(source_before,{p.name:b.digest(p) for p in self.source.iterdir()})
        self.assertFalse(any(p.name.startswith('.validate') for p in point.parent.iterdir()))

    def test_destination_acceptance_rename_failure_blocks_and_cleans_own_attempt(self):
        with patch.object(b.os,'rename',side_effect=OSError('synthetic rename failure')):
            with self.assertRaises(OSError):b.validate_destination('ryokan',self.dest,'storage-fixture')
        self.assertEqual(list((self.dest/'ryokan').iterdir()),[])

    def test_destination_acceptance_permission_failure_blocks(self):
        with patch.object(b.os,'chmod',side_effect=PermissionError('synthetic private permissions unavailable')):
            with self.assertRaises(PermissionError):b.validate_destination('ryokan',self.dest,'storage-fixture')

    def test_destination_acceptance_cli_has_no_source_and_logs_no_marker(self):
        cmd=[sys.executable,str(ROOT/'backup_state.py'),'--app','ryokan','--validate-destination','--destination',str(self.dest),'--pod-uid','fixture','--termination-log',str(self.root/'termination')]
        p=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(p.returncode,0);self.assertEqual(json.loads(p.stdout)['status'],'storage-verified')
        self.assertNotIn('storage-contract-v1',p.stdout+p.stderr)
        p=subprocess.run(cmd+['--source',str(self.source)],capture_output=True,text=True)
        self.assertEqual(p.returncode,1);self.assertFalse(list(self.source.iterdir()))

    def test_nested_writable_root_blocks(self):
        self.controller();nested=self.source/"destination";nested.mkdir()
        with self.assertRaises(b.BackupError):b.run_backup("controller",self.source,nested,self.work,"fixture","test",scratch_reserve=0,destination_reserve=0)

    def test_archive_write_bound_stops_before_completion(self):
        self.controller()
        with self.assertRaises(b.BackupError):self.run_backup(max_archive=512)
        self.assertFalse(list((self.dest/b.OWNER["controller"]).iterdir()))

    def test_cli_failure_redacts_json_content_and_does_not_report_success(self):
        self.controller();marker='DO-NOT-LOG-SYNTHETIC-PASSWORD';(self.source/'torrent-health.json').write_text('{'+marker)
        cmd=[sys.executable,str(ROOT/'backup_state.py'),'--app','controller','--source',str(self.source),'--destination',str(self.dest),'--work',str(self.work),'--pod-uid','fixture','--cohort','test','--source-pvc','fixture','--source-pvc-uid','fixture','--termination-log',str(self.root/'termination')]
        p=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(p.returncode,1);self.assertNotIn(marker,p.stdout+p.stderr+(self.root/'termination').read_text())
        self.assertEqual(json.loads(p.stdout)['status'],'failed')

if __name__=='__main__':unittest.main(verbosity=2)
