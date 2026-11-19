"""Initialize persistent Jellyfin state without changing PostgreSQL or Kubernetes."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import ssl
import subprocess
import tarfile
import time
import urllib.request

import migrate

DATA = Path('/data')
CONFIG = Path('/config')
RECEIPT = DATA / 'sqlite-migration.receipt.json'
DATABASE = DATA / 'data/jellyfin.db'


def api(path):
    service = Path('/var/run/secrets/kubernetes.io/serviceaccount')
    request = urllib.request.Request(
        'https://' + os.environ['KUBERNETES_SERVICE_HOST'] + ':' + os.environ.get('KUBERNETES_SERVICE_PORT_HTTPS', '443') + path,
        headers={'Authorization': 'Bearer ' + (service / 'token').read_text().strip()},
    )
    with urllib.request.urlopen(request, context=ssl.create_default_context(cafile=str(service / 'ca.crt')), timeout=10) as response:
        return json.load(response)


def wait_for_quiescence():
    # Recreate stops the old server before this init container. Also wait for the
    # independent qualification deployment to disappear before replacing its DB.
    for _ in range(180):
        pods = api('/api/v1/namespaces/media/pods')['items']
        others = [p for p in pods if p['metadata']['name'] != os.environ['POD_NAME']
                  and p['metadata'].get('labels', {}).get('app.kubernetes.io/instance') in ('jellyfin', 'jellyfin-sqlite-validation')
                  and p['status'].get('phase') not in ('Succeeded', 'Failed')]
        if not others:
            return
        time.sleep(5)
    raise RuntimeError('Other Jellyfin pods have not stopped; refusing cutover')


def restore(archive, target):
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            relative = Path(member.name)
            if relative.is_absolute() or '..' in relative.parts or member.issym() or member.islnk():
                raise ValueError('Unsafe configuration archive member')
            if not (member.isfile() or member.isdir()):
                raise ValueError('Unsupported configuration archive member')
            # The old file contains a PostgreSQL connection string.
            if relative.name.startswith('database.xml'):
                continue
            source.extract(member, target, filter='data')


def main():
    os.umask(0o077)
    mode = os.environ['MIGRATION_MODE']
    if mode not in ('qualification', 'cutover'):
        raise ValueError('Unknown migration mode')
    if RECEIPT.exists():
        receipt = json.loads(RECEIPT.read_text())
        if receipt['mode'] == 'cutover' or receipt['mode'] == mode:
            if not DATABASE.is_file():
                raise RuntimeError('Receipt exists without database')
            with sqlite3.connect('file:' + str(DATABASE) + '?mode=ro', uri=True) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Persisted SQLite database is corrupt')
            print('Existing validated SQLite database retained')
            return
        if receipt['mode'] != 'qualification':
            raise RuntimeError('Unknown existing migration receipt')
    elif DATABASE.exists():
        raise RuntimeError('Unrecognized database exists; refusing to overwrite')
    if mode == 'cutover':
        wait_for_quiescence()
    DATA.mkdir(parents=True, exist_ok=True)
    CONFIG.mkdir(parents=True, exist_ok=True)
    backup = DATA / 'migration-backup'
    backup.mkdir(exist_ok=True)
    if mode == 'cutover':
        # With all servers stopped this backup and the conversion have identical
        # application state. PostgreSQL is never written to by this container.
        with (backup / 'postgres-final.dump.partial').open('wb') as output:
            subprocess.run(['pg_dump', '--format=custom', '--no-owner', '--no-acl'], stdout=output, check=True)
        (backup / 'postgres-final.dump.partial').replace(backup / 'postgres-final.dump')
    for name, target in (('config.tar.gz', CONFIG), ('plugins.tar.gz', DATA / 'plugins/configurations')):
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile('/snapshot/' + name, backup / name)
        restore('/snapshot/' + name, target)
    (CONFIG / 'database.xml').write_text('<?xml version="1.0" encoding="utf-8"?><DatabaseConfigurationOptions><DatabaseType>Jellyfin-SQLite</DatabaseType><LockingBehavior>NoLock</LockingBehavior></DatabaseConfigurationOptions>\n')
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    temporary = DATA / 'data/jellyfin-conversion.partial.db'
    temporary.unlink(missing_ok=True)
    subprocess.run(['python', '/app/migrate.py', '--output', str(temporary)], check=True)
    report = json.loads(temporary.with_suffix('.receipt.json').read_text())
    report.update(mode=mode, source_quiesced=mode == 'cutover', converted_at=time.time())
    if DATABASE.exists():
        DATABASE.replace(backup / 'qualification.db')
    for suffix in ('-wal', '-shm'):
        Path(str(DATABASE) + suffix).unlink(missing_ok=True)
    temporary.replace(DATABASE)
    pending = RECEIPT.with_suffix('.partial.json')
    pending.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    pending.replace(RECEIPT)
    print(json.dumps({'mode': mode, 'tables': len(report['counts']), 'rows': sum(report['counts'].values()), 'integrity': report['integrity']}))


if __name__ == '__main__':
    main()
