import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import migrate


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / 'converted.db'
        self.schema = self.root / 'schema.sql'
        self.schema.write_text('''CREATE TABLE "__EFMigrationsHistory" (MigrationId TEXT PRIMARY KEY);
INSERT INTO "__EFMigrationsHistory" VALUES ('sqlite-migration');
CREATE TABLE "Users" (Id TEXT PRIMARY KEY, Active INTEGER, Created TEXT, Data BLOB, Rating REAL);
CREATE TABLE "Child" (Id INTEGER PRIMARY KEY AUTOINCREMENT, UserId TEXT REFERENCES Users(Id));''')
        self.columns = [
            {'table_name': 'Users', 'column_name': name, 'data_type': kind}
            for name, kind in [('Id', 'uuid'), ('Active', 'boolean'), ('Created', 'timestamp with time zone'), ('Data', 'bytea'), ('Rating', 'double precision')]
        ] + [{'table_name': 'Child', 'column_name': name, 'data_type': kind}
             for name, kind in [('Id', 'integer'), ('UserId', 'uuid')]]
        self.expected = self.root / 'expected.json'
        self.expected.write_text(json.dumps(self.columns))
        self.records = [
            {'kind': 'metadata', 'columns': self.columns},
            {'kind': 'row', 'table': 'Users', 'row': {'Id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', 'Active': True, 'Created': '-infinity', 'Data': '\\x0001ff', 'Rating': 0}},
            {'kind': 'row', 'table': 'Child', 'row': {'Id': 7, 'UserId': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'}},
            {'kind': 'sequences', 'values': [{'sequencename': 'Child_Id_seq', 'last_value': 123}]},
        ]

    def convert(self):
        return migrate.convert(map(json.dumps, self.records), self.destination, schema=self.schema, expected=self.expected)

    def test_preserve_types_references_history_and_sequence(self):
        report = self.convert()
        self.assertEqual(report['integrity'], 'ok')
        with sqlite3.connect(self.destination) as db:
            self.assertEqual(db.execute('SELECT * FROM Users').fetchone(), ('AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE', 1, '0001-01-01 00:00:00', b'\x00\x01\xff', 0.0))
            self.assertEqual(db.execute('SELECT * FROM __EFMigrationsHistory').fetchone(), ('sqlite-migration',))
            self.assertEqual(db.execute('SELECT seq FROM sqlite_sequence WHERE name="Child"').fetchone(), (123,))
        with self.assertRaises(ValueError):
            self.convert()

    def test_incomplete_export_removed(self):
        self.records.pop()
        with self.assertRaises(ValueError):
            self.convert()
        self.assertFalse(self.destination.exists())

    def test_dangling_reference_removed(self):
        self.records[2]['row']['UserId'] = '11111111-2222-3333-4444-555555555555'
        with self.assertRaisesRegex(ValueError, 'Foreign key'):
            self.convert()
        self.assertFalse(self.destination.exists())

    def test_unqualified_source_schema_rejected(self):
        self.records[0]['columns'] = []
        with self.assertRaisesRegex(ValueError, 'Source schema'):
            self.convert()
        self.assertFalse(self.destination.exists())

    def test_timezones_and_maximum_date(self):
        self.assertEqual(migrate.portable('2026-11-02T12:00:00+05:30', 'timestamp with time zone'), '2026-11-02 06:30:00')
        self.assertEqual(migrate.portable('infinity', 'timestamp with time zone'), '9999-12-31 23:59:59.9999999')


if __name__ == '__main__':
    unittest.main()
