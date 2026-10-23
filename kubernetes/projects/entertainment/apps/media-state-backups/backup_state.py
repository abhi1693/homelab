#!/usr/bin/env python3
"""Pre-start, offline per-pod restore points. Stdlib only; never writes source.

Caller MUST stop every writer first (single-replica Recreate Deployment) and
mount source read-only. This is not an online multi-file backup facility.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import sqlite3
import stat
import tarfile
import tempfile
import time
import uuid

VERSION = 1
GIB = 1024**3
POINT = re.compile(r"point-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\Z")
OWNER = {"controller": "qbittorrent-smart-queues", "ryokan": "ryokan",
         "recommender": "k8s-recommendation-engine", "rack": "rack-ops"}
SQLITE_FILE = {"ryokan": "ryokan.db", "recommender": "shipyard.db"}
RACK_STALE = {".rack-ops.json.g_i0_wtz.tmp": (320, 1787930032)}
CONTROLLER_REQUIRED = {"torrent-health.json", "udm-usage-corrections.json"}
RYOKAN_EXCLUDE = {"backups", "ryokan.db", "ryokan.db-wal", "ryokan.db-shm",
                  "ryokan.db.pre-jellyfin-key-20260812T165425Z.bak",
                  "naruto-shippuden-1760-20260925T173754Z.db",
                  "ryokan-shippuden-pre-fix.db", "ryokan-shippuden-pre-offset-fix.db",
                  "recovery/naruto-shippuden-final-20260817T165000Z/ryokan-before-final-recovery.db",
                  "recovery/naruto-shippuden-final-20260817T165000Z/ryokan-before-receipt-v2.db"}
FORBIDDEN = {".reset-auth", ".ryokan-restore-pending"}

class BackupError(Exception):
    """Static, non-sensitive message safe for the termination log."""

def require(ok, message):
    if not ok:
        raise BackupError(message)

def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def signature(path):
    s = path.lstat()
    return (s.st_mode, s.st_size, s.st_mtime_ns, s.st_ino)

def private_dir(path):
    path.mkdir(mode=0o700, parents=False, exist_ok=True)
    s = path.lstat()
    require(stat.S_ISDIR(s.st_mode) and not path.is_symlink(), "unsafe private directory")
    os.chmod(path, 0o700)
    require(stat.S_IMODE(path.stat().st_mode) == 0o700, "private directory permissions unavailable")

def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def write_json(path, value):
    with path.open("x", encoding="utf-8") as f:
        os.chmod(path, 0o600)
        json.dump(value, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())

def json_valid(path, require_object=False):
    # Duplicate keys / NaN are invalid state, not silently normalized backups.
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, "duplicate JSON state key")
            result[k] = v
        return result
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f, object_pairs_hook=pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(BackupError("invalid JSON state")))
        require(not require_object or isinstance(value, dict), "JSON state root must be an object")
    except (ValueError, UnicodeError):
        raise BackupError("invalid JSON state") from None

def inventory(source, app):
    require(source.is_dir() and not source.is_symlink(), "source directory unavailable")
    files, dirs = [], []
    def unreadable(_error):
        raise BackupError("source directory cannot be inventoried")
    for root, dirnames, filenames in os.walk(source, followlinks=False, onerror=unreadable):
        base = Path(root)
        for name in sorted(dirnames + filenames):
            path = base / name
            rel = path.relative_to(source).as_posix()
            require(name not in FORBIDDEN, "pending restore or auth-reset marker")
            require(rel != "manifest.json", "reserved backup manifest filename")
            require(len(rel) <= 1024, "source filename exceeds bound")
            require(not path.is_symlink(), "source symlink is not supported")
            if app == "rack" and rel in RACK_STALE:
                stale = path.stat()
                require(stat.S_ISREG(stale.st_mode) and
                        (stale.st_size, int(stale.st_mtime)) == RACK_STALE[rel],
                        "known stale state artifact changed unexpectedly")
                continue
            db_name = SQLITE_FILE.get(app)
            sqlite_parts = {db_name, str(db_name) + "-wal", str(db_name) + "-shm"}
            if (app == "ryokan" and rel in RYOKAN_EXCLUDE) or (db_name and rel in sqlite_parts):
                if name in dirnames:
                    dirnames.remove(name)
                continue
            s = path.lstat()
            if stat.S_ISDIR(s.st_mode):
                dirs.append(rel)
            else:
                require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1, "source must contain only regular unlinked files")
                require(not rel.endswith((".db", "-wal", "-shm", ".tmp", ".partial")), "unexpected database or incomplete state")
                files.append(rel)
    if app == "controller":
        require(CONTROLLER_REQUIRED <= set(files), "required controller state is missing")
    elif app == "rack":
        require("rack-ops.json" in files, "required rack restore state is missing")
    if app == "ryokan":
        key = source / ".ryokan-key"
        require(".ryokan-key" in files and key.stat().st_size == 32, "required private key is missing or invalid")
        require(stat.S_IMODE(key.stat().st_mode) & 0o007 == 0, "private key is world accessible")
    require(len(files) + len(dirs) <= 20000, "source file inventory exceeds bound")
    for rel in files:
        if rel.endswith(".json"):
            require((source / rel).stat().st_size <= 64 * 1024**2, "JSON state exceeds validation bound")
            json_valid(source / rel, require_object=app in {"controller", "rack"})
    if app == "rack":
        state = json.loads((source / "rack-ops.json").read_text())
        require({"active_stage", "active_stage_since", "line_power_since", "observed", "targets", "fleet_refs"} <= set(state),
                "rack restore state fields are incomplete")
        require(isinstance(state["active_stage"], str) and bool(state["active_stage"]) and
                all(isinstance(state[k], dict) for k in ["observed", "targets", "fleet_refs"]),
                "rack restore state field types are invalid")
    return sorted(files), sorted(dirs)

def database_fingerprint(connection, require_migrations=True):
    require(connection.execute("PRAGMA quick_check").fetchall() == [("ok",)], "SQLite quick check failed")
    require(connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "SQLite integrity check failed")
    rows = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name,tbl_name").fetchall()
    ledger_exists = any(r[0] == "table" and r[1] == "schema_migrations" for r in rows)
    require(ledger_exists or not require_migrations, "required migration ledger is missing")
    ids = [r[0] for r in connection.execute("SELECT id FROM schema_migrations ORDER BY id").fetchall()] if ledger_exists else []
    require(all(isinstance(x, str) for x in ids), "migration ledger must contain TEXT IDs")
    counts = {}
    for kind, name, _, _ in rows:
        if kind == "table":
            quoted = '"' + name.replace('"', '""') + '"'
            counts[name] = connection.execute("SELECT COUNT(*) FROM " + quoted).fetchone()[0]
    return {"schema_sha256": hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest(),
            "migration_ids": ids, "migration_ledger": "schema_migrations" if ledger_exists else None,
            "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "application_id": connection.execute("PRAGMA application_id").fetchone()[0], "table_row_counts": counts}

def sqlite_backup(source, scratch, output, app="ryokan"):
    """Stage quiescent DB+WAL, recover only staged copy, then SQLite Backup API.

    Copying both while all writers are stopped avoids read-only SHM limitations.
    immutable=1 is deliberately forbidden: committed WAL must be included.
    """
    name = SQLITE_FILE[app]
    db = source / name
    require(db.is_file() and not db.is_symlink(), "required SQLite database is missing")
    stage = scratch / "sqlite-stage"
    stage.mkdir(mode=0o700)
    watch = {}
    try:
        for suffix in ("", "-wal"):
            path = source / (name + suffix)
            if path.exists():
                require(stat.S_ISREG(path.lstat().st_mode) and path.lstat().st_nlink == 1 and not path.is_symlink(), "unsafe SQLite source file")
                watch[path] = signature(path)
                shutil.copyfile(path, stage / path.name)
                os.chmod(stage / path.name, 0o600)
        # Captures WAL existence as well as identities. Source SHM is not needed.
        wal_existed = (source / (name + "-wal")).exists()
        with closing(sqlite3.connect(stage / name, timeout=30)) as original:
            original.execute("PRAGMA busy_timeout=30000")
            before = database_fingerprint(original, require_migrations=app == "ryokan")
            with closing(sqlite3.connect(output)) as snapshot:
                original.backup(snapshot, pages=1024, sleep=0.05)
                require(snapshot.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete", "backup must be a standalone database")
                require(database_fingerprint(snapshot, require_migrations=app == "ryokan") == before, "SQLite backup schema or migration mismatch")
        os.chmod(output, 0o600)
        require(all(signature(p) == sig for p, sig in watch.items()) and
                (source / (name + "-wal")).exists() == wal_existed,
                "SQLite source changed while writers must be stopped")
        return before
    finally:
        shutil.rmtree(stage)

def file_record(path):
    s = path.stat()
    return {"bytes": s.st_size, "sha256": digest(path),
            "mode": stat.S_IMODE(s.st_mode), "uid": s.st_uid, "gid": s.st_gid}

def make_archive(path, payload, manifest, max_bytes):
    with path.open("xb") as f:
        os.chmod(path, 0o600)
        class BoundedWriter:
            def __init__(self): self.written = 0
            def write(self, block):
                self.written += len(block)
                require(self.written <= max_bytes, "archive exceeds configured bound")
                return f.write(block)
        with tarfile.open(fileobj=BoundedWriter(), mode="w|") as tar:
            for rel in ["manifest.json", *manifest["directories"], *manifest["files"]]:
                p = payload / rel
                info = tar.gettarinfo(str(p), arcname=rel)
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                # Archive is private. Preserve original modes/UIDs inside manifest
                # for explicit offline restoration, not by privileged extraction.
                info.mode = 0o700 if info.isdir() else 0o600
                if info.isfile():
                    with p.open("rb") as src:
                        tar.addfile(info, src)
                else:
                    tar.addfile(info)
        f.flush()
        os.fsync(f.fileno())

def restore_verify(archive, target, expected):
    """Read back the actual NFS tar and restore only checked regular members."""
    target.mkdir(mode=0o700)
    names = set()
    expected_names = {"manifest.json", *expected["files"], *expected["directories"]}
    with tarfile.open(archive, mode="r|") as tar:
        for member in tar:
            rel = member.name
            require(rel not in names and rel in expected_names and
                    not PurePosixPath(rel).is_absolute() and ".." not in PurePosixPath(rel).parts,
                    "unsafe or unexpected archive member")
            names.add(rel)
            dest = target / rel
            if member.isdir():
                require(rel in expected["directories"], "archive member type mismatch")
                dest.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            require(member.isfile() and rel not in expected["directories"], "archive link or device is forbidden")
            dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            bound = (8 * 1024 * 1024 if rel == "manifest.json" else expected["files"][rel]["bytes"])
            require(member.size == bound or (rel == "manifest.json" and member.size <= bound), "archive size mismatch")
            with tar.extractfile(member) as src, dest.open("xb") as out:
                os.chmod(dest, 0o600)
                shutil.copyfileobj(src, out, 1024 * 1024)
    require(names == expected_names, "archive is incomplete")
    require(json.loads((target / "manifest.json").read_text()) == expected, "archive manifest mismatch")
    for rel, record in expected["files"].items():
        require((target / rel).stat().st_size == record["bytes"] and digest(target / rel) == record["sha256"], "restored file checksum mismatch")
        if rel.endswith(".json"):
            json_valid(target / rel, require_object=expected["app"] in {"controller", "rack"})
    if expected["app"] in SQLITE_FILE:
        name = SQLITE_FILE[expected["app"]]
        with closing(sqlite3.connect(f"file:{target / name}?mode=ro", uri=True)) as db:
            require(database_fingerprint(db, require_migrations=expected["app"] == "ryokan") == expected["database"], "restored database fingerprint mismatch")
    if expected["app"] == "ryokan":
        require((target / ".ryokan-key").stat().st_size == 32, "restored private key is missing")

def completed_points(root, app):
    result = []
    for p in root.iterdir():
        if not POINT.fullmatch(p.name):
            continue
        require(p.is_dir() and not p.is_symlink(), "unsafe completed point directory")
        receipt_path = p / "receipt.json"
        require(receipt_path.is_file() and not receipt_path.is_symlink(), "completed point receipt unavailable")
        require(receipt_path.stat().st_size <= 8192, "completed point receipt exceeds bound")
        r = json.loads(receipt_path.read_text())
        require(r.get("format") == VERSION and r.get("owner") == OWNER[app] and r.get("point") == p.name,
                "completed point ownership mismatch")
        require(r.get("restored_verified") is True, "completed point was not restore verified")
        require(set(x.name for x in p.iterdir()) == {"state.tar", "receipt.json"}, "unexpected completed point files")
        archive = p / "state.tar"
        require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size == r["archive_bytes"] and
                digest(archive) == r["archive_sha256"], "completed point checksum mismatch")
        require(isinstance(r.get("created_ns"), int), "completed point timestamp missing")
        result.append((r["created_ns"], p))
    return [p for _, p in sorted(result, key=lambda item: (item[0], item[1].name))]

def run_backup(app, source, destination, work, pod_uid, cohort, *, retention=3,
               max_source=8 * GIB, max_work=24 * GIB, max_archive=10 * GIB,
               destination_reserve=GIB, scratch_reserve=512 * 1024**2,
               source_pvc="", source_pvc_uid=""):
    require(app in OWNER and 2 <= retention <= 7, "invalid app or retention policy")
    require(re.fullmatch(r"[A-Za-z0-9._-]{1,100}", pod_uid or "") and
            re.fullmatch(r"[A-Za-z0-9._-]{1,100}", cohort or ""), "invalid backup identity")
    for path in (source, destination, work):
        require(path.is_dir() and not path.is_symlink(), "mount directory unavailable")
    roots = [p.resolve() for p in (source, destination, work)]
    require(all(not a.is_relative_to(b) and not b.is_relative_to(a) for i, a in enumerate(roots) for b in roots[i+1:]),
            "source and writable roots must be disjoint")
    require(not any(p in FORBIDDEN for p in [x.name for x in source.iterdir()]), "pending restore or auth-reset marker")
    files, dirs = inventory(source, app)
    watched = {source / rel: signature(source / rel) for rel in files}
    name = SQLITE_FILE.get(app)
    for suffix in [name, name + "-wal"] if name else []:
        p = source / suffix
        if p.exists(): watched[p] = signature(p)
    source_bytes = sum(sig[1] for sig in watched.values())
    require(source_bytes <= max_source, "source exceeds configured backup bound")
    needed_work = 2 * source_bytes + scratch_reserve
    require(needed_work <= max_work and shutil.disk_usage(work).free >= needed_work,
            "insufficient bounded node scratch space")
    require(shutil.disk_usage(destination).free >= source_bytes + 32 * 1024**2 + destination_reserve,
            "insufficient backup destination space")
    root = destination / OWNER[app]
    private_dir(root)
    # Refuse suspicious existing completed points before publishing or pruning.
    completed_points(root, app)
    now = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    point = "point-" + now + "-" + uuid.uuid4().hex
    partial = root / (".partial-" + uuid.uuid4().hex)
    private_dir(partial)
    published = None
    try:
        with tempfile.TemporaryDirectory(prefix="restore-point-", dir=work) as temp:
            scratch = Path(temp)
            payload = scratch / "payload"
            payload.mkdir(mode=0o700)
            for rel in dirs:
                (payload / rel).mkdir(mode=0o700, parents=True, exist_ok=True)
            records = {}
            for rel in files:
                origin = source / rel
                records[rel] = file_record(origin)
                dest = payload / rel
                dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copyfile(origin, dest)
                os.chmod(dest, 0o600)
                require(digest(dest) == records[rel]["sha256"], "source copy checksum mismatch")
            database = None
            if name:
                database = sqlite_backup(source, scratch, payload / name, app=app)
                records[name] = file_record(payload / name)
                # Original ownership/mode needed for operator-reviewed restore.
                original = (source / name).stat()
                records[name].update(mode=stat.S_IMODE(original.st_mode), uid=original.st_uid, gid=original.st_gid)
            require(all(signature(p) == sig for p, sig in watched.items()) and inventory(source, app) == (files, dirs),
                    "source changed while writers must be stopped")
            manifest = {"format": VERSION, "app": app, "directories": dirs, "files": records, "database": database}
            write_json(payload / "manifest.json", manifest)
            archive = partial / "state.tar"
            require((payload / "manifest.json").stat().st_size <= 8 * 1024**2, "manifest exceeds bound")
            make_archive(archive, payload, manifest, max_archive)
            require(archive.stat().st_size <= max_archive, "archive exceeds configured bound")
            archive_hash = digest(archive)  # actual readback from destination
            restore_verify(archive, scratch / "restored", manifest)
            require(digest(archive) == archive_hash, "backup changed during restore verification")
            receipt = {"format": VERSION, "owner": OWNER[app], "point": point, "created_utc": now,
                       "created_ns": time.time_ns(), "pod_uid": pod_uid, "cohort": cohort, "source_pvc": source_pvc,
                       "expected_source_pvc_uid": source_pvc_uid, "archive_sha256": archive_hash,
                       "archive_bytes": archive.stat().st_size, "file_count": len(records),
                       "restored_verified": True,
                       "database_schema_sha256": database["schema_sha256"] if database else None,
                       "migration_count": len(database["migration_ids"]) if database else None}
            write_json(partial / "receipt.json", receipt)
            sync_dir(partial)
            published = root / point
            os.rename(partial, published)
            sync_dir(root)
        points = completed_points(root, app)
        # Prune only validated complete points owned by this one app, never partials.
        previous = [p for p in points if p != published]
        for old in previous[:-(retention - 1)]:
            shutil.rmtree(old)
        sync_dir(root)
        return receipt
    finally:
        if partial.exists():
            shutil.rmtree(partial)

def validate_destination(app, destination, pod_uid):
    """No source mounts: prove the real private NFS write/commit/read contract."""
    require(app in OWNER and re.fullmatch(r"[A-Za-z0-9._-]{1,100}", pod_uid or ""), "invalid storage validation identity")
    require(destination.is_dir() and not destination.is_symlink(), "backup destination mount unavailable")
    root = destination / OWNER[app]
    private_dir(root)
    partial = root / (".validate-partial-" + uuid.uuid4().hex)
    final = root / (".validate-complete-" + uuid.uuid4().hex)
    private_dir(partial)
    marker = b"media-prestart-backup-storage-contract-v1\n"
    try:
        probe = partial / "probe.bin"
        with probe.open("xb") as f:
            os.chmod(probe, 0o600)
            f.write(marker)
            f.flush()
            os.fsync(f.fileno())
        require(stat.S_IMODE(probe.stat().st_mode) == 0o600, "private file permissions unavailable")
        require(probe.read_bytes() == marker, "storage write readback failed")
        sync_dir(partial)
        os.rename(partial, final)
        sync_dir(root)
        require(stat.S_IMODE(final.stat().st_mode) == 0o700 and
                stat.S_IMODE((final / "probe.bin").stat().st_mode) == 0o600,
                "private storage permissions changed after rename")
        require((final / "probe.bin").read_bytes() == marker, "atomic storage readback failed")
        # No completed backup, archive, receipt, unknown file, or source is touched.
        shutil.rmtree(final)
        sync_dir(root)
        return {"status": "storage-verified", "owner": OWNER[app], "uid": os.geteuid(),
                "private_directory": True, "private_file": True, "file_fsync": True,
                "directory_fsync": True, "atomic_rename": True, "readback": True}
    finally:
        for owned in (partial, final):
            if owned.exists():
                shutil.rmtree(owned)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--app", choices=OWNER, required=True)
    p.add_argument("--validate-destination", action="store_true")
    for arg in ["source", "destination", "work", "pod-uid", "cohort", "source-pvc", "source-pvc-uid"]:
        p.add_argument("--" + arg, required=arg in {"destination", "pod-uid"})
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--max-source-bytes", type=int, default=8*GIB)
    p.add_argument("--max-work-bytes", type=int, default=24*GIB)
    p.add_argument("--max-archive-bytes", type=int, default=10*GIB)
    p.add_argument("--retention", type=int, default=3)
    p.add_argument("--scratch-reserve-bytes", type=int, default=512 * 1024**2)
    p.add_argument("--termination-log", default="/dev/termination-log")
    args = p.parse_args()
    os.umask(0o077)
    def timeout(_sig, _frame):
        raise BackupError("backup deadline exceeded")
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(min(max(args.timeout, 1), 3600))
    try:
        if args.validate_destination:
            require(not any([args.source, args.work, args.cohort, args.source_pvc, args.source_pvc_uid]), "storage validation must not include source inputs")
            status = validate_destination(args.app, Path(args.destination), args.pod_uid)
            print(json.dumps(status), flush=True)
            Path(args.termination_log).write_text(json.dumps(status) + "\n")
            return 0
        require(all([args.source, args.work, args.cohort, args.source_pvc, args.source_pvc_uid]), "required backup source identity unavailable")
        receipt = run_backup(args.app, Path(args.source), Path(args.destination), Path(args.work),
                             args.pod_uid, args.cohort, retention=args.retention,
                             max_source=args.max_source_bytes, max_work=args.max_work_bytes,
                             max_archive=args.max_archive_bytes, scratch_reserve=args.scratch_reserve_bytes, source_pvc=args.source_pvc,
                             source_pvc_uid=args.source_pvc_uid)
        status = {"status": "verified", "point": receipt["point"], "archive_sha256": receipt["archive_sha256"],
                  "archive_bytes": receipt["archive_bytes"], "file_count": receipt["file_count"]}
    except Exception as exc:
        # Do not expose exception strings, paths, JSON values, SQL or credentials.
        status = {"status": "failed", "reason": str(exc) if isinstance(exc, BackupError) else "backup operation failed"}
        print(json.dumps(status), flush=True)
        Path(args.termination_log).write_text(json.dumps(status) + "\n")
        return 1
    print(json.dumps(status), flush=True)
    Path(args.termination_log).write_text(json.dumps(status) + "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
