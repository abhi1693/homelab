"""Hermetic restore-point coverage for non-media safety controllers."""
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

APP=Path(__file__).resolve().parents[1]
REPO=Path(os.environ['CONTROLLER_BACKUP_REVIEW_ROOT']) if 'CONTROLLER_BACKUP_REVIEW_ROOT' in os.environ else APP.parents[4]
HELPER=REPO/'kubernetes/projects/entertainment/apps/media-state-backups/backup_state.py'
spec=importlib.util.spec_from_file_location('controller_backup',HELPER)
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

class ControllerProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source,self.dest,self.work=[self.root/x for x in ['source','dest','work']]
        for p in [self.source,self.dest,self.work]:p.mkdir()
        self.connections=[];self.addCleanup(lambda:[c.close() for c in self.connections])

    def database(self):
        c=sqlite3.connect(self.source/'shipyard.db');self.connections.append(c)
        c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA wal_autocheckpoint=0')
        c.executescript('CREATE TABLE proposal_events(id INTEGER PRIMARY KEY,status TEXT);PRAGMA user_version=7;PRAGMA application_id=1693;')
        c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        c.execute('INSERT INTO proposal_events VALUES(1,?)',('pending',));c.commit()
        return c

    def rack(self):
        d={'active_stage':'on-battery','active_stage_since':1,'line_power_since':None,
           'observed':{'ups_online':0,'ups_on_battery':1},'targets':{'synthetic':{'shed':True,'replicas':2}},
           'fleet_refs':{'synthetic':{'paused_by_rack_ops':True,'original_paused':False}}}
        (self.source/'rack-ops.json').write_text(json.dumps(d));return d

    def backup(self,app,**kwargs):
        return b.run_backup(app,self.source,self.dest,self.work,'fixture-pod','controller-release',
                            scratch_reserve=0,destination_reserve=0,**kwargs)

    def restore(self,r,app):
        archive=self.dest/b.OWNER[app]/r['point']/'state.tar'
        with tarfile.open(archive) as t:manifest=json.load(t.extractfile('manifest.json'))
        out=self.root/'restored';b.restore_verify(archive,out,manifest);return out,manifest

    def test_recommender_committed_wal_schema_version_and_rowcounts_roundtrip(self):
        self.database();before={p.name:(b.digest(p),p.stat().st_mtime_ns) for p in self.source.iterdir()}
        r=self.backup('recommender');out,m=self.restore(r,'recommender')
        with closing(sqlite3.connect(out/'shipyard.db')) as c:
            self.assertEqual(c.execute('SELECT status FROM proposal_events').fetchone(),('pending',))
            self.assertEqual(b.database_fingerprint(c,False),m['database'])
        self.assertEqual(m['database']['user_version'],7);self.assertEqual(m['database']['application_id'],1693)
        self.assertIsNone(m['database']['migration_ledger']);self.assertEqual(m['database']['migration_ids'],[])
        self.assertEqual(m['database']['table_row_counts'],{'proposal_events':1})
        self.assertEqual(before,{p.name:(b.digest(p),p.stat().st_mtime_ns) for p in self.source.iterdir()})
        self.assertFalse((out/'shipyard.db-wal').exists())

    def test_recommender_missing_shm_recovers_only_scratch(self):
        self.database();(self.source/'shipyard.db-shm').unlink()
        r=self.backup('recommender');out,_=self.restore(r,'recommender')
        with closing(sqlite3.connect(out/'shipyard.db')) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM proposal_events').fetchone()[0],1)
        self.assertFalse((self.source/'shipyard.db-shm').exists())

    def test_recommender_schema_and_user_version_changes_are_fingerprinted(self):
        c=self.database();first=b.database_fingerprint(c,False)
        c.execute('PRAGMA user_version=8');self.assertNotEqual(b.database_fingerprint(c,False),first)
        c.execute('PRAGMA user_version=7');c.execute('ALTER TABLE proposal_events ADD COLUMN note TEXT')
        self.assertNotEqual(b.database_fingerprint(c,False)['schema_sha256'],first['schema_sha256'])

    def test_recommender_explicit_text_ledger_preserved_if_present(self):
        c=self.database();c.execute('CREATE TABLE schema_migrations(id TEXT PRIMARY KEY)')
        c.execute('INSERT INTO schema_migrations VALUES(?)',('future_text_migration',));c.commit()
        _,m=self.restore(self.backup('recommender'),'recommender')
        self.assertEqual(m['database']['migration_ids'],['future_text_migration'])

    def test_ryokan_still_requires_its_real_migration_ledger(self):
        c=self.database()
        with self.assertRaises(b.BackupError):b.database_fingerprint(c,True)

    def test_recommender_corrupt_database_fails_without_completion(self):
        (self.source/'shipyard.db').write_bytes(b'invalid sqlite database')
        with self.assertRaises(Exception):self.backup('recommender')
        root=self.dest/b.OWNER['recommender'];self.assertFalse(root.exists() and list(root.iterdir()))

    def test_recommender_missing_database_fails(self):
        with self.assertRaises(b.BackupError):self.backup('recommender')

    def test_recommender_unknown_second_database_fails(self):
        self.database();(self.source/'other.db').write_bytes(b'unknown')
        with self.assertRaises(b.BackupError):self.backup('recommender')

    def test_recommender_source_and_scratch_bounds_fail_before_publish(self):
        self.database()
        for args in [{'max_source':1},{'max_work':1}]:
            with self.assertRaises(b.BackupError):self.backup('recommender',**args)
        self.assertFalse(list(self.dest.iterdir()))

    def test_rack_retains_shed_and_original_restore_state_exactly(self):
        original=self.rack();before=(self.source/'rack-ops.json').read_bytes()
        r=self.backup('rack');out,m=self.restore(r,'rack')
        self.assertEqual(json.loads((out/'rack-ops.json').read_text()),original)
        self.assertEqual((out/'rack-ops.json').read_bytes(),before)
        self.assertIsNone(m['database']);self.assertNotIn('targets',json.dumps(r))
        self.assertEqual((self.source/'rack-ops.json').read_bytes(),before)

    def test_rack_known_stale_temp_preserved_on_source_and_excluded(self):
        self.rack();name=next(iter(b.RACK_STALE));size,mtime=b.RACK_STALE[name]
        stale=self.source/name;stale.write_bytes(b'x'*size);os.utime(stale,(mtime,mtime))
        out,m=self.restore(self.backup('rack'),'rack')
        self.assertNotIn(name,m['files']);self.assertFalse((out/name).exists());self.assertEqual(stale.read_bytes(),b'x'*size)

    def test_rack_changed_known_stale_temp_fails(self):
        self.rack();stale=self.source/next(iter(b.RACK_STALE));stale.write_bytes(b'changed')
        with self.assertRaises(b.BackupError):self.backup('rack')
        self.assertEqual(stale.read_bytes(),b'changed')

    def test_rack_unknown_temp_fails_and_is_untouched(self):
        self.rack();stale=self.source/'.rack-ops.json.unexpected.tmp';stale.write_bytes(b'unexpected')
        with self.assertRaises(b.BackupError):self.backup('rack')
        self.assertEqual(stale.read_bytes(),b'unexpected')

    def test_rack_missing_or_partial_state_cannot_silently_initialize(self):
        with self.assertRaises(b.BackupError):self.backup('rack')
        (self.source/'rack-ops.json').write_text('{}')
        with self.assertRaises(b.BackupError):self.backup('rack')

    def test_rack_invalid_state_types_fail(self):
        d=self.rack();d['fleet_refs']=[];(self.source/'rack-ops.json').write_text(json.dumps(d))
        with self.assertRaises(b.BackupError):self.backup('rack')

    def test_unreadable_subdirectory_cannot_be_silently_omitted(self):
        self.rack()
        def denied(*args,**kwargs):kwargs['onerror'](PermissionError('synthetic'))
        with patch.object(b.os,'walk',side_effect=denied):
            with self.assertRaises(b.BackupError):b.inventory(self.source,'rack')

if __name__=='__main__':unittest.main(verbosity=2)
