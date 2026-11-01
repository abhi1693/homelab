#!/usr/bin/env python3
"""Guarded application-state recovery; dry-run unless --apply is supplied.

Run in the existing Ryokan reconciler container only after its current Pod's
pre-start backup has exited successfully. Pass an operator-reviewed JSON plan
on stdin. This does not change Kubernetes resources or copy/delete media.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time

BATCH = 5000
MIB = 1024**2


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def receipts(db):
    rows = db.execute(
        "SELECT grab_id,source_path,destination_path,file_size,completed_at "
        "FROM grabbed_torrent_import_receipts ORDER BY grab_id,source_path"
    ).fetchall()
    return len(rows), hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def validate(db, plan):
    backup = plan.get("backup", {})
    require(backup.get("status") == "verified", "verified pre-start backup required")
    require(re.fullmatch(r"[0-9a-f]{64}", backup.get("archive_sha256", "")), "invalid backup digest")
    require(backup.get("archive_bytes", 0) > 0, "backup archive is empty")
    require(re.fullmatch(r"point-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}", backup.get("point", "")), "invalid backup point")
    require(receipts(db)[0] == plan["expected_receipts"], "receipt count changed; refresh the plan")
    cfg = db.execute("SELECT post_processing_mode,recycle_bin_path FROM config WHERE id=1").fetchone()
    require(cfg and cfg[0].lower() == "copy" and cfg[1], "copy mode and recycle protection required")
    seen = set()
    for item in plan.get("adoptions", []):
        h = item["hash"]
        require(re.fullmatch(r"[0-9a-f]{40}", h) and h not in seen, "invalid or duplicate torrent hash")
        seen.add(h)
        require(item["progress"] == 1 and item["amount_left"] == 0, "torrent is incomplete")
        row = db.execute("SELECT title FROM series WHERE id=?", (item["series_id"],)).fetchone()
        require(row and row[0] == item["series_title"], "series identity mismatch")
        client = db.execute("SELECT name,enabled FROM download_clients WHERE id=?", (item["client_id"],)).fetchone()
        require(client and client[0] == item["client_name"] and client[1], "download client mismatch")
        src = Path(item["source"])
        root = Path(plan["downloads_root"])
        require(src.is_absolute() and src.is_relative_to(root) and ".." not in src.parts, "unsafe source path")
        if src.exists() or src.is_symlink():
            require(not src.is_symlink() and src.resolve().is_relative_to(root.resolve()), "unsafe source path")
            require(src.is_file() and src.stat().st_size == item["size"] > 0, "source file is absent or changed")
        else:
            # The existing verifier mounts the DB and library, while Sonarr
            # mounts the same downloads PVC. An operator can supply fresh stat
            # results from that existing Pod, avoiding another RWO rollout.
            proof = plan.get("source_verification", {})
            require(-30 <= time.time() - proof.get("verified_at", 0) <= 300, "source verification is missing or expired")
            require(re.fullmatch(r"[0-9a-f-]{36}", proof.get("pod_uid", "")), "source Pod identity required")
            checks = [x for x in proof.get("files", []) if x.get("source") == str(src)]
            require(len(checks) == 1, "source verification is incomplete")
            check = checks[0]
            require(check.get("is_file") is True and check.get("is_symlink") is False and
                    check.get("resolved_source") == str(src) and check.get("size") == item["size"] > 0,
                    "source file is absent, unsafe or changed")
        require(item["title_token"].casefold() in src.name.casefold(), "source title does not match series")
        ep = re.search(r" - 0*([0-9]+)(?=[ ._\[])", src.name)
        require(ep and int(ep[1]) == item["episode"] > 0, "source episode mismatch")
        existing = db.execute("SELECT series_id,episode_numbers FROM grabbed_torrents WHERE lower(hash)=?", (h,)).fetchall()
        require(not existing, "hash already tracked; use the existing grab instead")


def prune(db, predicate, cutoff):
    if cutoff is None:
        return 0
    removed = 0
    database = Path(db.execute("PRAGMA database_list").fetchone()[2])
    while True:
        require(shutil.disk_usage(database.parent).free > 256 * MIB, "insufficient WAL headroom; stop and retry after storage recovery")
        # Each transaction is small enough for normal WAL checkpointing and
        # releases the writer lock between batches.
        n = db.execute(
            f"DELETE FROM logs WHERE id IN (SELECT id FROM logs WHERE {predicate} "
            "AND id < ? ORDER BY id LIMIT ?)", (cutoff, BATCH)
        ).rowcount
        db.commit()
        removed += n
        if removed and removed % 100000 == 0:
            print(json.dumps({"log_rows_removed": removed}), file=sys.stderr, flush=True)
        if not n:
            return removed
        db.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        wal = Path(str(database) + "-wal")
        if wal.exists() and wal.stat().st_size > 128 * MIB:
            checkpoint = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            require(checkpoint[0] == 0, "active readers prevent a bounded WAL; retry when idle")


def recover(database, plan, apply=False):
    mode = "rw" if apply else "ro"
    # SQLite can cache its temporary directory before VACUUM. Select the
    # writable PVC before opening it; the verifier root filesystem is readonly.
    if apply:
        os.environ["SQLITE_TMPDIR"] = str(Path(database).resolve().parent)
    db = sqlite3.connect(f"file:{Path(database)}?mode={mode}", uri=True, timeout=30)
    try:
        db.execute("PRAGMA busy_timeout=30000")
        validate(db, plan)
        before = receipts(db)
        result = {"apply": apply, "adoptions": len(plan.get("adoptions", [])), "receipts_before": before[0]}
        if not apply:
            return result
        limits = (("level != 'error'", 100000), ("level = 'error'", 10000))
        removed = 0
        for predicate, keep in limits:
            cutoff = db.execute(
                f"SELECT id FROM logs NOT INDEXED WHERE {predicate} ORDER BY id DESC LIMIT 1 OFFSET ?", (keep - 1,)
            ).fetchone()
            require(shutil.disk_usage(Path(database).parent).free > 256 * MIB, "insufficient WAL headroom")
            removed += prune(db, predicate, cutoff[0] if cutoff else None)
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        page = db.execute("PRAGMA page_size").fetchone()[0]
        used = (db.execute("PRAGMA page_count").fetchone()[0] - db.execute("PRAGMA freelist_count").fetchone()[0]) * page
        require(shutil.disk_usage(Path(database).parent).free > used * 2 + 256 * MIB, "insufficient vacuum headroom; logs pruned, compaction deferred")
        temp_dir = str(Path(database).resolve().parent).replace("'", "''")
        db.execute(f"PRAGMA temp_store_directory='{temp_dir}'")
        db.execute("VACUUM")
        require(db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0,
                "compaction committed; active readers defer physical truncation")
        require(db.execute("PRAGMA quick_check").fetchall() == [("ok",)], "database check failed")
        require(receipts(db) == before, "existing import receipts changed")
        db.execute("BEGIN IMMEDIATE")
        # Recheck identities under the writer lock before creating new grabs.
        validate(db, plan)
        ids = []
        for item in plan.get("adoptions", []):
            cur = db.execute(
                "INSERT INTO grabbed_torrents(hash,torrent_name,series_id,episode_numbers,state,is_batch,client_type,client_content_path,download_client_id) "
                "VALUES(?,?,?,?, 'pending',0,'qbittorrent',?,?)",
                (item["hash"], item["name"], item["series_id"], json.dumps([item["episode"]]), item["content_path"], item["client_id"])
            )
            ids.append(cur.lastrowid)
        db.commit()
        require(receipts(db) == before, "existing import receipts changed during adoption")
        result.update(log_rows_removed=removed, database_bytes=Path(database).stat().st_size, created_grab_ids=ids, receipts_after=before[0])
        return result
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(recover(args.database, json.load(sys.stdin), args.apply), sort_keys=True))


if __name__ == "__main__":
    main()
