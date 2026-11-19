#!/usr/bin/env python3
"""Qualify collation SQL only in an explicitly labelled, isolated Docker fixture.

The caller creates an ephemeral PostgreSQL17 container with no host data mounts,
network=none, read-only root, UID26, tmpfs /tmp and the exact fixture label. This
program deliberately creates inconsistent synthetic catalogue metadata ONLY in
that disposable fixture; it never invokes kubectl or connects to a remote DB.
"""
import argparse
import json
import os
import pathlib
import subprocess
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container',required=True)
    parser.add_argument('--output',type=pathlib.Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Refusing to overwrite fixture evidence')
    os.umask(0o077)
    C=args.container
    inspect=json.loads(subprocess.check_output(['docker','inspect',C],text=True))[0]
    assert inspect['Config']['Labels'].get('home-lab.task')=='unused-collation-metadata-fixture'
    assert inspect['HostConfig']['NetworkMode']=='none' and inspect['HostConfig']['ReadonlyRootfs']
    assert not inspect['HostConfig'].get('Binds') and all(x['Type']=='tmpfs' for x in inspect['Mounts'])
    root=pathlib.Path(__file__).resolve().parents[1]
    SQL=(root/'kubernetes/projects/database/apps/postgresql/unused-collation-version-maintenance.sql').read_text()
    BASE=['docker','exec','-i',C,'psql','-X','-qAt','-U','postgres','-h','/tmp','-p','55432','-d','postgres','-v','ON_ERROR_STOP=1']
    def sql(text,check=True):
     r=subprocess.run(BASE,input=text,text=True,capture_output=True,timeout=25)
     if check and r.returncode: raise RuntimeError(r.stderr)
     return r
    for _ in range(30):
     r=sql('SELECT 1;',False)
     if r.returncode==0:break
     time.sleep(0.2)
    else:raise RuntimeError('Fixture did not start')
    sid=sql('SELECT system_identifier FROM pg_control_system();').stdout.strip()
    version=sql('SHOW server_version_num;').stdout.strip();assert int(version)//10000==17
    vars=['-v','expected_database=postgres','-v','expected_system_identifier='+sid,'-v','expected_server_version='+version,'-v','batch_size=32']
    def maintenance(extra=None):return subprocess.run(BASE+vars+(extra or []),input=SQL,text=True,capture_output=True,timeout=25)
    results=[]
    # Legacy incompatible-encoding catalogue metadata must stay untouched.
    incompatible=sql("WITH target AS (SELECT oid FROM pg_collation WHERE collprovider='c' AND collencoding NOT IN (-1,pg_char_to_encoding(current_setting('server_encoding'))) AND pg_collation_actual_version(oid) IS NOT NULL LIMIT 1) UPDATE pg_collation SET collversion='2.31' WHERE oid IN (SELECT oid FROM target) RETURNING oid;").stdout.strip();assert incompatible
    sql("CREATE COLLATION pg_catalog.fixture_unused (provider=libc,locale='en_US.utf8',version='2.31');")
    r=maintenance();assert r.returncode==0,r.stderr;x=json.loads(r.stdout);assert x['refreshed']==1,x
    assert sql("SELECT collversion FROM pg_collation WHERE oid="+incompatible+";").stdout.strip()=='2.31'
    results.append('unused applicable metadata refreshes; incompatible encoding is preserved')
    r=maintenance();assert r.returncode==0 and json.loads(r.stdout)['refreshed']==0;results.append('repeat is idempotent')
    sql("CREATE COLLATION pg_catalog.fixture_used (provider=libc,locale='en_US.utf8',version='2.31'); CREATE TABLE fixture_use (value text COLLATE pg_catalog.fixture_used); CREATE INDEX fixture_use_index ON fixture_use(value); CREATE COLLATION pg_catalog.fixture_untouched (provider=libc,locale='en_US.utf8',version='2.31');")
    r=maintenance();assert r.returncode!=0 and 'stored dependencies' in r.stderr,r.stderr
    assert sql("SELECT collversion FROM pg_collation WHERE collname='fixture_untouched';").stdout.strip()=='2.31';results.append('used mismatch refuses entire batch before changing unused peers')
    sql('DROP TABLE fixture_use; DROP COLLATION pg_catalog.fixture_used;')
    r=maintenance(['-v','expected_system_identifier=1']);assert r.returncode!=0 and 'identity fence failed' in r.stderr,r.stderr;results.append('wrong physical cluster identity fails closed')
    # Lock contention must time out before catalog changes.
    locker=subprocess.Popen(BASE,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    locker.stdin.write('BEGIN; LOCK TABLE pg_catalog.pg_attribute IN ROW EXCLUSIVE MODE; SELECT pg_sleep(4); COMMIT;\n');locker.stdin.close();time.sleep(0.3)
    r=maintenance();assert r.returncode!=0 and 'lock timeout' in r.stderr,r.stderr
    locker.wait(timeout=8);results.append('concurrent schema-catalog writer causes bounded lock refusal')
    # After locks clear the same reviewed operation succeeds.
    r=maintenance();assert r.returncode==0 and json.loads(r.stdout)['refreshed']==1,r.stderr;results.append('bounded retry succeeds once schema writer releases its locks')
    # While maintenance holds the catalog locks, normal DML remains available and
    # a newly introduced schema dependency must wait/fail before it can be stored.
    sql("CREATE TABLE fixture_dml(value integer); CREATE COLLATION pg_catalog.fixture_race (provider=libc,locale='en_US.utf8',version='2.31');")
    held=SQL.replace('DO $maintenance$', 'SELECT pg_sleep(3);\nDO $maintenance$',1)
    worker=subprocess.Popen(BASE+vars,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    worker.stdin.write(held);worker.stdin.close()
    for _ in range(20):
     locked=sql("SELECT count(*) FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid WHERE a.application_name='unused-collation-version-maintenance' AND l.relation='pg_catalog.pg_depend'::regclass AND l.mode='ShareLock' AND l.granted;").stdout.strip()
     if locked!='0':break
     time.sleep(0.1)
    else:raise AssertionError('Maintenance fixture did not acquire catalog locks')
    assert sql('INSERT INTO fixture_dml VALUES(1);').returncode==0
    r=sql("SET lock_timeout='200ms'; CREATE TABLE fixture_race_use(value text COLLATE pg_catalog.fixture_race);",False)
    assert r.returncode!=0 and 'lock timeout' in r.stderr,r.stderr
    worker.wait(timeout=10);assert worker.returncode==0,worker.stderr.read()
    assert sql("SELECT collversion=pg_collation_actual_version(oid) FROM pg_collation WHERE collname='fixture_race';").stdout.strip()=='t'
    results.append('catalog locks allow ordinary DML and fence new schema dependencies before the refresh')
    p=args.output;p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);p.write_text(json.dumps({'passed':True,'checks':results},indent=2)+'\n');print(p.read_text())


if __name__=='__main__':
    main()
