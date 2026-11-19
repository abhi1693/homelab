#!/usr/bin/env python3
"""Audit or explicitly refresh unused, encoding-applicable collation metadata.

Uses read-only Kubernetes discovery and SQL operator maintenance; never changes
Kubernetes resources. The plan freezes database/pod identities and a completed
recovery point. Database DDL requires the explicit apply subcommand.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / 'kubernetes/projects/database/apps/postgresql/unused-collation-version-maintenance.sql'
AUDIT_SQL = """WITH bad AS (
 SELECT c.oid,c.collencoding,n.nspname FROM pg_collation c JOIN pg_namespace n ON n.oid=c.collnamespace
 WHERE c.collprovider<>'d' AND c.collversion IS DISTINCT FROM pg_collation_actual_version(c.oid)
) SELECT json_build_object(
 'all_mismatches',(SELECT count(*) FROM bad),
 'applicable_mismatches',(SELECT count(*) FROM bad WHERE collencoding IN (-1,pg_char_to_encoding(current_setting('server_encoding')))),
 'non_catalog_mismatches',(SELECT count(*) FROM bad WHERE nspname<>'pg_catalog'),
 'dependent_objects',(SELECT count(*) FROM pg_depend d JOIN bad b ON d.refclassid='pg_collation'::regclass AND d.refobjid=b.oid),
 'column_usages',(SELECT count(*) FROM pg_attribute a JOIN bad b ON b.oid=a.attcollation WHERE NOT a.attisdropped),
 'index_usages',(SELECT count(*) FROM pg_index i CROSS JOIN LATERAL unnest(i.indcollation) AS ci(oid) JOIN bad b ON b.oid=ci.oid),
 'type_usages',(SELECT count(*) FROM pg_type t JOIN bad b ON b.oid=t.typcollation),
 'range_usages',(SELECT count(*) FROM pg_range r JOIN bad b ON b.oid=r.rngcollation),
 'application_collations',(SELECT md5(coalesce(jsonb_agg(to_jsonb(c) ORDER BY c.oid)::text,'[]')) FROM pg_collation c JOIN pg_namespace n ON n.oid=c.collnamespace WHERE n.nspname<>'pg_catalog'));
"""
UNSAFE = ('non_catalog_mismatches','dependent_objects','column_usages','index_usages','type_usages','range_usages')


def run(argv, text_input=None, timeout=60):
    return subprocess.check_output(argv, input=text_input, text=True, timeout=timeout)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['audit','apply'])
    parser.add_argument('--kubeconfig',required=True)
    parser.add_argument('--namespace',default='postgresql')
    parser.add_argument('--cluster',default='postgresql')
    parser.add_argument('--backup',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--batch-size',type=int,default=32)
    args=parser.parse_args()
    if args.output.exists(): parser.error('Refusing to overwrite evidence')
    if args.output.resolve().is_relative_to(ROOT): parser.error('Store private evidence outside the repository')
    if not 1<=args.batch_size<=64: parser.error('Batch size must be 1..64')
    if args.mode=='apply' and not args.plan: parser.error('apply requires a reviewed --plan')
    os.umask(0o077)
    kube=['kubectl','--kubeconfig',args.kubeconfig,'--request-timeout=15s']
    def get(*argv): return json.loads(run(kube+['get',*argv,'-o','json']))
    def state():
        cluster=get('clusters.postgresql.cnpg.io',args.cluster,'-n',args.namespace)
        status=cluster['status'];conditions={x['type']:x['status'] for x in status['conditions']}
        if cluster['spec'].get('instances')!=3 or status.get('readyInstances')!=3 or status.get('instances')!=3 or any(conditions.get(x)!='True' for x in ['Ready','ContinuousArchiving']):
            raise ValueError('Require three Ready instances and healthy continuous archiving')
        backup=get('backups.postgresql.cnpg.io',args.backup,'-n',args.namespace)
        if backup['spec']['cluster']['name']!=args.cluster or backup['status'].get('phase')!='completed':
            raise ValueError('Named recovery-point backup is not completed for this cluster')
        stopped=datetime.fromisoformat(backup['status']['stoppedAt'].replace('Z','+00:00'))
        if not 0<=(datetime.now(timezone.utc)-stopped).total_seconds()<86400:
            raise ValueError('Require a completed backup less than 24 hours old')
        pods=get('pods','-n',args.namespace,'-l','cnpg.io/cluster='+args.cluster+',cnpg.io/podRole=instance')['items']
        if len(pods)!=3 or any(not any(c['type']=='Ready' and c['status']=='True' for c in p['status'].get('conditions',[])) or p['metadata'].get('deletionTimestamp') for p in pods):
            raise ValueError('Require exactly three non-terminating Ready database pods')
        pod_images={p['metadata']['name']:next(c['image'] for c in p['spec']['containers'] if c['name']=='postgres') for p in pods}
        if any(image!=status['image'] for image in pod_images.values()): raise ValueError('Every native PostgreSQL container must match the selected image')
        return {'cluster_uid':cluster['metadata']['uid'],'primary':status['currentPrimary'],'image':status['image'],'pod_images':pod_images,
                'pods':{p['metadata']['name']:p['metadata']['uid'] for p in pods},
                'backup_uid':backup['metadata']['uid'],'backup_id':backup['status']['backupId']}
    initial=state();primary=initial['primary']
    def query(db,sql,variables=None):
        argv=kube+['exec','-i','-n',args.namespace,primary,'-c','postgres','--','psql','-X','-qAt','-v','ON_ERROR_STOP=1','-d',db]
        for key,value in (variables or {}).items(): argv+=['-v',str(key)+'='+str(value)]
        return json.loads(run(argv,sql,timeout=45))
    def require_streaming():
        replicas=sorted(set(initial['pods'])-{primary})
        if len(replicas)!=2: raise ValueError('Require exactly two expected standbys')
        result=query('postgres',"SELECT json_build_object('count',count(*),'distinct_names',count(DISTINCT application_name),'healthy',coalesce(bool_and(state='streaming' AND sync_state IN ('sync','quorum')),false)) FROM pg_stat_replication WHERE application_name IN (:'first_replica',:'second_replica');",{'first_replica':replicas[0],'second_replica':replicas[1]})
        if result['count']!=2 or result['distinct_names']!=2 or not result['healthy']:
            raise ValueError('Both expected standbys must be streaming synchronously')
    identity=query('postgres',"SELECT json_build_object('system_identifier',system_identifier::text,'version',current_setting('server_version_num'),'in_recovery',pg_is_in_recovery()) FROM pg_control_system();")
    if identity['in_recovery']: raise ValueError('Selected primary is a standby')
    require_streaming()
    databases=query('postgres',"SELECT json_agg(json_build_object('name',datname,'allow_connections',datallowconn,'is_template',datistemplate,'collation',datcollate,'version',datcollversion,'actual_version',pg_database_collation_actual_version(oid)) ORDER BY datname) FROM pg_database;")
    if any(x['version']!=x['actual_version'] for x in databases): raise ValueError('Database-default collation mismatch needs separate reviewed rebuild')
    template0=[x for x in databases if x['name']=='template0']
    if len(template0)!=1 or template0[0]['allow_connections'] or not template0[0]['is_template']: raise ValueError('Require pristine, connection-disabled template0')
    targets=[d['name'] for d in databases if d['allow_connections'] and d['name']!='template0']
    audits={db:query(db,AUDIT_SQL) for db in targets}
    if any(a[k] for a in audits.values() for k in UNSAFE): raise ValueError('A mismatch has stored dependencies or a non-catalogue definition; reviewed rebuild required')
    sql=SQL_PATH.read_text();sha=hashlib.sha256(sql.encode()).hexdigest()
    snapshot={'schema':1,'captured_at':datetime.now(timezone.utc).isoformat(),'namespace':args.namespace,'cluster':args.cluster,'backup':args.backup,
              'state':initial,'identity':identity,'databases':databases,'audits':audits,'sql_sha256':sha,'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if args.mode=='audit': result=snapshot
    else:
        plan=json.loads(args.plan.read_text())
        if plan['schema']!=1 or any(plan[k]!=snapshot[k] for k in ['namespace','cluster','backup','state','identity','databases','sql_sha256','driver_sha256']):
            raise ValueError('Reviewed plan identity, database allowlist, SQL or recovery point changed; create a new audit')
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(plan['captured_at'])).total_seconds()
        if not 0<=age<=1800: raise ValueError('Reviewed plan must be less than 30 minutes old')
        if plan['audits']!=audits: raise ValueError('Collation inventory changed since audit; create a new audit')
        progress=[]
        args.output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        progress_path=args.output.with_suffix('.progress.jsonl')
        with progress_path.open('x') as stream:
            for db in targets:
                if state()!=initial: raise ValueError('Cluster/pod/backup identity changed during maintenance')
                require_streaming()
                count=0
                for _ in range((audits[db]['applicable_mismatches']+args.batch_size-1)//args.batch_size+1):
                    batch=query(db,sql,{'expected_database':db,'expected_system_identifier':identity['system_identifier'],'expected_server_version':identity['version'],'batch_size':args.batch_size})
                    stream.write(json.dumps(batch)+'\n');stream.flush();progress.append(batch);count+=batch['refreshed']
                    if batch['refreshed']==0: break
                else: raise ValueError('Unexpected batch count; inventory may be changing')
                after=query(db,AUDIT_SQL)
                if after['applicable_mismatches'] or any(after[k] for k in UNSAFE) or after['application_collations']!=audits[db]['application_collations']:
                    raise ValueError('Post-maintenance collation guard failed')
                if count!=audits[db]['applicable_mismatches']: raise ValueError('Refreshed count differs from reviewed plan')
            if state()!=initial: raise ValueError('Final cluster/pod/recovery-point identity changed')
            require_streaming()
        result={'before':snapshot,'batches':progress,'after':{db:query(db,AUDIT_SQL) for db in targets},'completed_at':datetime.now(timezone.utc).isoformat()}
    args.output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with args.output.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({'mode':args.mode,'databases':len(targets),'applicable_before':sum(v['applicable_mismatches'] for v in audits.values()),'evidence':str(args.output)}))


if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,OSError,subprocess.SubprocessError) as error:
        print('Maintenance stopped: '+str(error),file=sys.stderr);raise SystemExit(1)
