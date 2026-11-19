"""Create a consistent, private rollback point before Jellyfin 12 migrations."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tarfile

from prepare import wait_for_quiescence


def main():
    os.umask(0o077)
    target = Path('/data/pre-upgrade-12.4')
    receipt = target / 'receipt.json'
    if receipt.exists():
        report = json.loads(receipt.read_text())
        if report['target_version'] != '12.4' or report['integrity'] != 'ok':
            raise RuntimeError('Unrecognized upgrade backup receipt')
        with (target / 'jellyfin.db').open('rb') as database:
            if hashlib.file_digest(database, 'sha256').hexdigest() != report['database_sha256']:
                raise RuntimeError('Upgrade backup checksum differs')
        print('Existing verified pre-upgrade backup retained')
        return
    wait_for_quiescence()
    target.mkdir(exist_ok=True)
    with sqlite3.connect('file:/data/data/jellyfin.db?mode=ro', uri=True) as source:
        # ProductVersion is EF Core's version, not Jellyfin's version. Compare
        # the complete history against the qualified 10.11.8 SQLite schema.
        query = 'SELECT MigrationId, ProductVersion FROM __EFMigrationsHistory ORDER BY MigrationId'
        with sqlite3.connect(':memory:') as expected:
            expected.executescript(Path('/app/schema-10.11.8.sql').read_text())
            if source.execute(query).fetchall() != expected.execute(query).fetchall():
                raise RuntimeError('Refuse a pre-upgrade backup from an unqualified or already upgraded schema')
        partial = target / 'jellyfin.partial.db'
        partial.unlink(missing_ok=True)
        with sqlite3.connect(partial) as destination:
            source.backup(destination)
            if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Pre-upgrade backup integrity failure')
            if destination.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise RuntimeError('Pre-upgrade backup foreign-key failure')
            counts = {table: destination.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0]
                      for table in ('Users', 'BaseItems', 'UserData')}
        partial.replace(target / 'jellyfin.db')
    # Do not follow VFS symlinks into actual media. Preserve plugin settings and
    # library/collection/playlist/VFS definitions alongside the application DB.
    with tarfile.open(target / 'configuration.partial.tar.gz', 'w:gz', dereference=False) as archive:
        for path in ('/config', '/data/plugins/configurations', '/data/data/device.txt',
                     '/shared-data/root', '/shared-data/Shokofin',
                     '/shared-data/data/collections', '/shared-data/data/playlists'):
            if Path(path).exists():
                archive.add(path, arcname=path.lstrip('/'))
    (target / 'configuration.partial.tar.gz').replace(target / 'configuration.tar.gz')
    with (target / 'jellyfin.db').open('rb') as database:
        checksum = hashlib.file_digest(database, 'sha256').hexdigest()
    report = {'source_version': '10.11.8', 'target_version': '12.4',
              'integrity': 'ok', 'counts': counts, 'database_sha256': checksum}
    pending = target / 'receipt.partial.json'
    pending.write_text(json.dumps(report, indent=2) + '\n')
    pending.replace(receipt)
    print(json.dumps({key: value for key, value in report.items() if key != 'database_sha256'}))


if __name__ == '__main__':
    main()
