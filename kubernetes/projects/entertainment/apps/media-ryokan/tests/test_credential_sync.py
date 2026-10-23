"""Replay the actual Fleet credential script only against disposable SQLite fixtures."""
import ast
from contextlib import closing, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import textwrap
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
MANIFEST = Path(os.environ.get("CREDENTIAL_SYNC_MANIFEST", APP / "deployment.yaml"))
METADATA = Path(os.environ.get("CREDENTIAL_SYNC_IMAGE_METADATA", APP.parent / "media-state-backups/public-helper-image.json"))
SCRIPT_SHA256 = "61ef73e6053b26105f501c96f3fb0478b73e7db232680ce8ad6846fee7d5be36"
ENV = {"QBT_USER": "fixture-user", "QBT_PASSWORD": "fixture-password", "PROWLARR_API_KEY": "fixture-prowlarr"}
URL = "http://prowlarr.media.svc.cluster.local:9696/31/api"


def script_and_stanza():
    source = MANIFEST.read_text()
    stanza = source.split("\n        - name: sync-qbittorrent-credentials\n", 1)[1].split("\n      containers:", 1)[0]
    literal = re.search(r"\n            - \|\n(.*?)\n          env:\n", stanza, re.S)
    if literal is None:
        raise AssertionError("Credential script literal was not found in its reviewed container")
    return textwrap.dedent(literal[1]) + "\n", stanza


class CredentialSyncTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("CREDENTIAL_SYNC_EXACT_TMPFS") == "1":
            self.assertEqual((os.getuid(), os.getgid()), (568, 568))
            self.assertTrue(os.statvfs("/").f_flag & os.ST_RDONLY)
            capabilities = next(line.split()[1] for line in Path("/proc/self/status").read_text().splitlines() if line.startswith("CapEff:"))
            self.assertEqual(int(capabilities, 16), 0)
            # Native-image invocation mounts a new private Docker tmpfs here.
            self.assertTrue(any(" /data " in line and " - tmpfs " in line
                                for line in Path("/proc/self/mountinfo").read_text().splitlines()))
            self.database = Path("/data/ryokan.db")
            self.assertFalse(self.database.exists(), "Refuse to use existing state as a fixture")
            self.addCleanup(lambda: [Path(str(self.database)+suffix).unlink(missing_ok=True)
                                     for suffix in ["", "-wal", "-shm", "-journal"]])
        else:
            directory = tempfile.TemporaryDirectory(prefix="credential-sync-fixture-")
            self.addCleanup(directory.cleanup)
            self.database = Path(directory.name) / "ryokan.db"
        self.script, self.stanza = script_and_stanza()

    def run_sync(self, missing=False):
        # Only relocate the one absolute database path; execute every SQL/branch byte unchanged.
        self.assertEqual(self.script.count('Path("/data/ryokan.db")'), 1)
        code = self.script if self.database == Path("/data/ryokan.db") else self.script.replace(
            'Path("/data/ryokan.db")', f"Path({str(self.database)!r})")
        environment = ENV if not missing else {k: v for k, v in ENV.items() if k != "PROWLARR_API_KEY"}
        output = io.StringIO()
        with patch.dict(os.environ, environment, clear=True), patch("time.time", return_value=1800000000), redirect_stdout(output):
            try:
                exec(compile(code, "actual-fleet-credential-sync", "exec"), {"__name__": "fixture"})
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        return output.getvalue()

    def seed(self, existing=False, category=False, missing_redaction=False):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.executescript("""
                CREATE TABLE config(id INTEGER PRIMARY KEY,qbit_user TEXT,qbit_pass TEXT,
                    post_processing_mode TEXT,recycle_bin_path TEXT,recycle_bin_age_days INTEGER);
                INSERT INTO config VALUES(1,'old-user','old-password','move','old-recycle',1);
                CREATE TABLE download_clients(id INTEGER PRIMARY KEY,kind TEXT,username TEXT,
                    password TEXT,updated_at INTEGER,enabled INTEGER,is_default INTEGER);
                INSERT INTO download_clients VALUES(6,'qbittorrent','old-six','old-six',0,1,1);
                INSERT INTO download_clients VALUES(2,'qbittorrent','old-two','old-two',0,0,0);
                INSERT INTO download_clients VALUES(3,'transmission','keep-user','keep-password',0,1,0);
                CREATE TABLE indexers(id INTEGER PRIMARY KEY,name TEXT,kind TEXT,url TEXT,api_key TEXT,
                    priority INTEGER,enabled INTEGER,is_private_tracker INTEGER,min_seeders INTEGER,
                    download_client_id INTEGER,rss_enabled INTEGER,updated_at INTEGER DEFAULT 0);
            """)
            if category:
                connection.execute("ALTER TABLE indexers ADD COLUMN category_ids TEXT NOT NULL DEFAULT '5070'")
            if not missing_redaction:
                connection.execute("ALTER TABLE indexers ADD COLUMN rss_last_poll_error TEXT NOT NULL DEFAULT ''")
            connection.executemany("INSERT INTO indexers(id,name,url,api_key) VALUES(?,?,?,?)", [
                (10,"other-prowlarr","http://prowlarr.media.svc.cluster.local:9696/10/api","old-prowlarr"),
                (11,"unrelated","https://fixture.invalid/api","keep-key"),
            ])
            if existing:
                connection.execute("INSERT INTO indexers(id,name,url,api_key) VALUES(31,'old-name',?,'old-target')", (URL,))
            if not missing_redaction:
                connection.execute("UPDATE indexers SET rss_last_poll_error='fixture apikey=old-fixture' WHERE id=10")
                connection.execute("UPDATE indexers SET rss_last_poll_error='ordinary upstream timeout' WHERE id=11")

    def dump(self):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            return list(connection.iterdump())

    def business_rows(self):
        # updated_at is intentionally refreshed by the existing script, including
        # the first update after an insert; idempotency concerns rows/policy/keys.
        with closing(sqlite3.connect(self.database)) as connection, connection:
            result = {}
            for table in ["config", "download_clients", "indexers"]:
                columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})") if row[1] != "updated_at"]
                selected = ",".join('"' + column.replace('"', '""') + '"' for column in columns)
                result[table] = connection.execute(f"SELECT {selected} FROM {table} ORDER BY id").fetchall()
            return result

    def assert_result(self):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            self.assertEqual(connection.execute("SELECT qbit_user,qbit_pass,post_processing_mode,recycle_bin_path,recycle_bin_age_days FROM config WHERE id=1").fetchone(),
                             ("fixture-user","fixture-password","copy","/media/anime/.recycle",14))
            self.assertEqual(connection.execute("SELECT username,password,updated_at FROM download_clients WHERE kind='qbittorrent' ORDER BY id").fetchall(),
                             [("fixture-user","fixture-password",1800000000)] * 2)
            self.assertEqual(connection.execute("SELECT username,password FROM download_clients WHERE kind='transmission'").fetchone(), ("keep-user","keep-password"))
            row = connection.execute("SELECT name,kind,api_key,category_ids,priority,enabled,is_private_tracker,min_seeders,download_client_id,rss_enabled FROM indexers WHERE url=?", (URL,)).fetchone()
            self.assertEqual(row, ("Sukebei Nyaa Anime","torznab","fixture-prowlarr","6000",16,1,0,1,6,1))
            self.assertEqual(connection.execute("SELECT count(*) FROM indexers WHERE url=?", (URL,)).fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT api_key,rss_last_poll_error FROM indexers WHERE id=10").fetchone(), ("fixture-prowlarr",""))
            self.assertEqual(connection.execute("SELECT api_key,rss_last_poll_error FROM indexers WHERE id=11").fetchone(), ("keep-key","ordinary upstream timeout"))

    def test_reviewed_image_interpreter_and_script_bytes(self):
        metadata = json.loads(METADATA.read_text())
        self.assertIn("          image: " + metadata["image"] + "\n", self.stanza)
        self.assertIn("          command:\n            - /usr/bin/python\n            - -c\n", self.stanza)
        self.assertEqual(hashlib.sha256(self.script.encode()).hexdigest(), SCRIPT_SHA256)
        imports = set()
        for node in ast.walk(ast.parse(self.script)):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {"os","sqlite3","time","pathlib"})

    def test_absent_database_skips_without_creating_state(self):
        output = self.run_sync()
        self.assertIn("database does not exist yet", output)
        self.assertFalse(self.database.exists())

    def test_legacy_column_migration_and_insert_are_idempotent(self):
        self.seed()
        self.run_sync()
        self.assert_result()
        before = self.business_rows()
        self.run_sync()
        self.assert_result()
        self.assertEqual(self.business_rows(), before)
        normalized = self.dump()
        self.run_sync()
        self.assertEqual(self.dump(), normalized)

    def test_existing_column_and_indexer_update_are_idempotent(self):
        self.seed(existing=True, category=True)
        self.run_sync()
        self.assert_result()
        before = self.dump()
        self.run_sync()
        self.assertEqual(self.dump(), before)

    def test_error_rolls_back_all_rows_and_additive_schema_change(self):
        self.seed(missing_redaction=True)
        before = self.dump()
        with self.assertRaises(sqlite3.OperationalError):
            self.run_sync()
        self.assertEqual(self.dump(), before)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            self.assertNotIn("category_ids", {row[1] for row in connection.execute("PRAGMA table_info(indexers)")})

    def test_missing_required_input_fails_before_any_write(self):
        self.seed()
        before = self.dump()
        with self.assertRaises(KeyError):
            self.run_sync(missing=True)
        self.assertEqual(self.dump(), before)


if __name__ == "__main__":
    unittest.main()
