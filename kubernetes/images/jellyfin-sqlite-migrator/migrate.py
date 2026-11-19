"""Convert a read-only Jellyfin PostgreSQL snapshot to a validated SQLite file."""
import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
MODULUS = 1 << 256


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


def portable(value, kind):
    if value is None:
        return None
    if kind == 'uuid':
        return str(uuid.UUID(value)).upper()
    if kind == 'boolean':
        if not isinstance(value, bool):
            raise ValueError('Non-boolean source value')
        return int(value)
    if kind == 'bytea':
        if not value.startswith('\\x'):
            raise ValueError('Unknown binary encoding')
        return bytes.fromhex(value[2:])
    if kind.startswith('timestamp'):
        # Npgsql encodes DateTime.MinValue/MaxValue as PostgreSQL infinities.
        if value == '-infinity':
            return '0001-01-01 00:00:00'
        if value == 'infinity':
            return '9999-12-31 23:59:59.9999999'
        parsed = datetime.datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return parsed.isoformat(sep=' ')
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(',', ':'))
    return value


def row_hash(row):
    # SQLite REAL affinity converts integral JSON numbers to floats.
    values = [
        {'binary': base64.b64encode(v).decode()} if isinstance(v, bytes)
        else int(v) if isinstance(v, float) and v.is_integer()
        else v for v in row
    ]
    data = json.dumps(values, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    return int.from_bytes(hashlib.sha256(data).digest(), 'big')


def export_sql(tables):
    queries = ['BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;']
    queries.append("SELECT json_build_object('kind','metadata','columns',json_agg(row_to_json(c))) FROM (SELECT table_name,column_name,data_type,udt_name,is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name IN (SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE') ORDER BY table_name,ordinal_position)c;")
    for name in tables:
        queries.append("SELECT json_build_object('kind','row','table','" + name.replace("'", "''") + "','row',row_to_json(t)) FROM " + identifier(name) + ' t;')
    queries.append("SELECT json_build_object('kind','sequences','values',coalesce(json_agg(row_to_json(s)), '[]'::json)) FROM (SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='public')s;")
    queries.append('COMMIT;')
    return '\n'.join(queries)


def convert(lines, destination, *, schema=ROOT / 'schema-10.11.8.sql', expected=ROOT / 'source-schema-10.11.8.json'):
    expected_columns = json.loads(expected.read_text())
    tables = {}
    for col in expected_columns:
        if col['table_name'] != '__EFMigrationsHistory':
            tables.setdefault(col['table_name'], []).append(col)
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Refuse to overwrite an existing database')
    db = sqlite3.connect(destination)
    counts = {name: 0 for name in tables}
    hashes = {name: 0 for name in tables}
    try:
        db.executescript(schema.read_text())
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('BEGIN IMMEDIATE')
        for name in tables:
            actual = {r[1] for r in db.execute('PRAGMA table_info(' + identifier(name) + ')')}
            if actual != {c['column_name'] for c in tables[name]}:
                raise ValueError('SQLite schema mismatch: ' + name)
            db.execute('DELETE FROM ' + identifier(name))
        metadata_seen = False
        sequences_seen = False
        for line in lines:
            if not line.strip():
                continue
            record = json.loads(line)
            if record['kind'] == 'metadata':
                if metadata_seen or record['columns'] != expected_columns:
                    raise ValueError('Source schema differs from qualified 10.11.8 schema')
                metadata_seen = True
            elif record['kind'] == 'row':
                if not metadata_seen or sequences_seen:
                    raise ValueError('Invalid snapshot record order')
                name = record['table']
                columns = tables[name]
                row = record['row']
                if set(row) != {c['column_name'] for c in columns}:
                    raise ValueError('Row schema mismatch')
                values = [portable(row[c['column_name']], c['data_type']) for c in columns]
                db.execute('INSERT INTO ' + identifier(name) + '(' + ','.join(identifier(c['column_name']) for c in columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', values)
                counts[name] += 1
                hashes[name] = (hashes[name] + row_hash(values)) % MODULUS
            elif record['kind'] == 'sequences':
                if not metadata_seen or sequences_seen:
                    raise ValueError('Invalid sequence record')
                sequences_seen = True
                for name in tables:
                    for column in tables[name]:
                        sequence_name = name + '_' + column['column_name'] + '_seq'
                        value = next((s['last_value'] for s in record['values'] if s['sequencename'] == sequence_name), None)
                        if value is not None:
                            db.execute('UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name=?', (value, name))
            else:
                raise ValueError('Unknown snapshot record')
        if not metadata_seen or not sequences_seen:
            raise ValueError('Incomplete source snapshot')
        for name, columns in tables.items():
            count, checksum = 0, 0
            for row in db.execute('SELECT ' + ','.join(identifier(c['column_name']) for c in columns) + ' FROM ' + identifier(name)):
                count += 1
                checksum = (checksum + row_hash(row)) % MODULUS
            if count != counts[name] or checksum != hashes[name]:
                raise ValueError('Row validation failed: ' + name)
        if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise ValueError('Foreign key violations')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity failure')
        db.commit()
        db.execute('PRAGMA foreign_keys=ON')
        return {'counts': counts, 'row_checksums': {k: format(v, '064x') for k, v in hashes.items()}, 'integrity': 'ok'}
    except BaseException:
        db.rollback()
        db.close()
        destination.unlink(missing_ok=True)
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    os.umask(0o077)
    spec = json.loads((ROOT / 'source-schema-10.11.8.json').read_text())
    tables = sorted({c['table_name'] for c in spec} - {'__EFMigrationsHistory'})
    env = dict(os.environ)
    env['PGOPTIONS'] = '-c default_transaction_read_only=on'
    with tempfile.TemporaryDirectory(prefix='jellyfin-export-') as tmp:
        sql = Path(tmp) / 'export.sql'
        sql.write_text(export_sql(tables))
        command = ['psql', '-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-f', str(sql)]
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env) as proc:
            try:
                report = convert(proc.stdout, args.output)
                if proc.wait() != 0:
                    args.output.unlink(missing_ok=True)
                    raise RuntimeError('Read-only PostgreSQL snapshot export failed')
            except BaseException:
                proc.terminate()
                raise
    args.output.with_suffix('.receipt.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'tables': len(report['counts']), 'rows': sum(report['counts'].values()), 'integrity': report['integrity']}))


if __name__ == '__main__':
    main()
