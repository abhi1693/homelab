import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/recover-import-state.py"
spec = importlib.util.spec_from_file_location("recover_import_state", SCRIPT)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.database = self.root / "ryokan.db"
        self.source = self.root / "Boruto - 077 [BD 1080p].mkv"
        self.source.write_bytes(b"verified-source")
        with sqlite3.connect(self.database) as db:
            db.executescript("""
                CREATE TABLE config(id INTEGER PRIMARY KEY,post_processing_mode TEXT,recycle_bin_path TEXT);
                INSERT INTO config VALUES(1,'copy','/media/anime/.recycle');
                CREATE TABLE series(id INTEGER PRIMARY KEY,title TEXT);
                INSERT INTO series VALUES(195,'Boruto: Naruto Next Generations');
                CREATE TABLE download_clients(id INTEGER PRIMARY KEY,name TEXT,enabled INTEGER);
                INSERT INTO download_clients VALUES(1,'qBittorrent',1);
                CREATE TABLE grabbed_torrents(id INTEGER PRIMARY KEY,hash TEXT,torrent_name TEXT,series_id INTEGER,episode_numbers TEXT,state TEXT,is_batch INTEGER,client_type TEXT,client_content_path TEXT,download_client_id INTEGER);
                CREATE TABLE grabbed_torrent_import_receipts(grab_id INTEGER,source_path TEXT,destination_path TEXT,file_size INTEGER,completed_at TEXT);
                INSERT INTO grabbed_torrent_import_receipts VALUES(1,'original-source','existing-library-file',123,'2026-10-01');
                CREATE TABLE logs(id INTEGER PRIMARY KEY,level TEXT,message TEXT);
            """)
        self.plan = {
            "backup": {"status": "verified", "archive_sha256": "a" * 64,
                       "archive_bytes": 100, "point": "point-20261028T000000Z-" + "a" * 32},
            "expected_receipts": 1, "downloads_root": str(self.root),
            "adoptions": [{"hash": "b" * 40, "name": self.source.name,
                           "series_id": 195, "series_title": "Boruto: Naruto Next Generations",
                           "client_id": 1, "client_name": "qBittorrent", "episode": 77,
                           "progress": 1, "amount_left": 0, "source": str(self.source),
                           "content_path": str(self.source), "size": self.source.stat().st_size,
                           "title_token": "Boruto"}],
        }

    def test_dry_run_preserves_database_and_media(self):
        before = self.database.read_bytes()
        result = recovery.recover(self.database, self.plan)
        self.assertFalse(result["apply"])
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), b"verified-source")

    def test_apply_caps_logs_preserves_old_receipts_and_creates_exact_grab(self):
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO logs(level,message) VALUES('error','old error retained')")
            db.executemany("INSERT INTO logs(level,message) VALUES('warn',?)",
                           ((str(i),) for i in range(100007)))
        result = recovery.recover(self.database, self.plan, apply=True)
        self.assertEqual(result["log_rows_removed"], 7)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM logs").fetchone()[0], 100001)
            self.assertEqual(db.execute("SELECT message FROM logs WHERE level='error'").fetchone()[0], "old error retained")
            self.assertEqual(db.execute("SELECT source_path,destination_path,file_size FROM grabbed_torrent_import_receipts").fetchall(), [("original-source", "existing-library-file", 123)])
            self.assertEqual(db.execute("SELECT hash,series_id,episode_numbers,state FROM grabbed_torrents").fetchall(), [("b" * 40, 195, "[77]", "pending")])
        self.assertEqual(self.source.read_bytes(), b"verified-source")
        with self.assertRaisesRegex(RuntimeError, "already tracked"):
            recovery.recover(self.database, self.plan, apply=True)

    def test_missing_backup_or_wrong_episode_or_incomplete_source_never_writes(self):
        for mutation in (lambda p: p["backup"].update(status="failed"),
                         lambda p: p["adoptions"][0].update(episode=78),
                         lambda p: p["adoptions"][0].update(amount_left=1),
                         lambda p: p["adoptions"][0].update(series_title="Unrelated series")):
            plan = json.loads(json.dumps(self.plan))
            mutation(plan)
            before = self.database.read_bytes()
            with self.assertRaises(RuntimeError):
                recovery.recover(self.database, plan, apply=True)
            self.assertEqual(self.database.read_bytes(), before)

    def remote_plan(self):
        plan = json.loads(json.dumps(self.plan))
        source = "/downloads/" + self.source.name
        plan["downloads_root"] = "/downloads"
        plan["adoptions"][0].update(source=source, content_path=source)
        plan["source_verification"] = {
            "verified_at": time.time(), "pod_uid": "12345678-1234-1234-1234-123456789abc",
            "files": [{"source": source, "resolved_source": source, "is_file": True,
                       "is_symlink": False, "size": self.source.stat().st_size}],
        }
        return plan

    def test_fresh_source_checks_from_existing_download_mount_allow_adoption(self):
        result = recovery.recover(self.database, self.remote_plan(), apply=True)
        self.assertEqual(len(result["created_grab_ids"]), 1)
        self.assertEqual(result["receipts_after"], 1)

    def test_missing_stale_changed_or_unsafe_remote_source_checks_never_write(self):
        for mutation in (lambda p: p.pop("source_verification"),
                         lambda p: p["source_verification"].update(verified_at=time.time() - 301),
                         lambda p: p["source_verification"].update(pod_uid="unknown"),
                         lambda p: p["source_verification"]["files"][0].update(size=999),
                         lambda p: p["source_verification"]["files"][0].update(is_symlink=True)):
            plan = self.remote_plan()
            mutation(plan)
            before = self.database.read_bytes()
            with self.assertRaises(RuntimeError):
                recovery.recover(self.database, plan, apply=True)
            self.assertEqual(self.database.read_bytes(), before)

    def test_symlink_escape_is_rejected(self):
        link = self.root / "alias.mkv"
        link.symlink_to(self.source)
        self.plan["adoptions"][0]["source"] = str(link)
        with self.assertRaisesRegex(RuntimeError, "unsafe source"):
            recovery.recover(self.database, self.plan, apply=True)


if __name__ == "__main__":
    unittest.main()
