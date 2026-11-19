"""Online SQLite/configuration recovery points on the retained private NAS."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tarfile
import tempfile


def private(path, directory=False):
    info = path.stat()
    expected = (int(os.environ.get('BACKUP_UID', '977')), int(os.environ.get('BACKUP_GID', '988')))
    mode = stat.S_IMODE(info.st_mode)
    if (info.st_uid, info.st_gid) != expected or mode != (0o770 if directory else 0o660):
        raise RuntimeError('NAS backup ownership or private mode differs from the declared contract')


def main():
    os.umask(0o007)
    root = Path('/backups/sqlite-backups')
    if root.is_symlink():
        raise RuntimeError('Refuse a symlink backup destination')
    root.mkdir(mode=0o770, exist_ok=True)
    private(root, directory=True)
    pending = Path(tempfile.mkdtemp(prefix='.pending-', dir=root))
    pending.chmod(0o770)
    try:
        database = pending / 'jellyfin.db'
        database.touch(mode=0o660)
        with sqlite3.connect('file:/data/data/jellyfin.db?mode=ro', uri=True, timeout=60) as source:
            with sqlite3.connect(database) as destination:
                source.backup(destination, pages=1024, sleep=0.05)
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('SQLite backup integrity failure')
                if destination.execute('PRAGMA foreign_key_check').fetchone() is not None:
                    raise RuntimeError('SQLite backup foreign-key failure')
                counts = {table: destination.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0]
                          for table in ('Users', 'BaseItems', 'UserData')}
        archive = pending / 'configuration.tar.gz'
        with tarfile.open(archive, 'w:gz', dereference=False) as output:
            for path in ('/config', '/data/plugins/configurations', '/data/data/device.txt',
                         '/data/data/splashscreen.png', '/data/sqlite-migration.receipt.json'):
                if Path(path).exists():
                    output.add(path, arcname=path.lstrip('/'))
        checksums = {}
        for path in (database, archive):
            path.chmod(0o660)
            private(path)
            with path.open('rb') as source:
                checksums[path.name] = hashlib.file_digest(source, 'sha256').hexdigest()
                os.fsync(source.fileno())
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        receipt = pending / 'receipt.json'
        receipt.write_text(json.dumps({'created_at': stamp, 'integrity': 'ok', 'counts': counts, 'sha256': checksums}, indent=2) + '\n')
        receipt.chmod(0o660)
        private(receipt)
        with receipt.open('rb') as source:
            os.fsync(source.fileno())
        private(pending, directory=True)
        pending.rename(root / stamp)
        complete = sorted(path for path in root.iterdir()
                          if re.fullmatch(r'\d{8}T\d{6}Z', path.name)
                          and not path.is_symlink() and (path / 'receipt.json').is_file())
        for old in complete[:-7]:
            private(old, directory=True)
            shutil.rmtree(old)
        print(json.dumps({'status': 'backed-up', 'created_at': stamp, 'integrity': 'ok', 'counts': counts, 'retention': 7}))
    finally:
        if pending.exists():
            shutil.rmtree(pending)


if __name__ == '__main__':
    main()
