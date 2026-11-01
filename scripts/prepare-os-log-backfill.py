#!/usr/bin/env python3
"""Prepare immutable, private K3s/kernel JSONL replay files from an OS evidence bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil


ROOT = Path(__file__).resolve().parents[1]
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_INPUT_BYTES = 1024 * 1024 * 1024
MAX_RECORD_BYTES = 16 * 1024 * 1024
NODE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


def fail(message: str) -> None:
    raise ValueError(message)


def private_file(path: Path):
    return open(path, "xb", opener=lambda name, flags: os.open(name, flags, 0o600))


def digest_file(path: Path, algorithm: str = "sha256") -> str:
    result = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def utc(microseconds: int) -> str:
    return datetime.fromtimestamp(microseconds / 1_000_000, timezone.utc).isoformat()


def parse_record(raw: bytes, node: str, line: int) -> dict:
    # Never include raw records or exception excerpts in diagnostic output.
    if len(raw) > MAX_RECORD_BYTES or not raw.endswith(b"\n"):
        fail(f"{node}: record {line} exceeds the line bound or lacks its terminating newline")
    try:
        record = json.loads(raw.decode("utf-8"), parse_constant=lambda _: fail("non-JSON number"))
    except (ValueError, UnicodeDecodeError):
        fail(f"{node}: record {line} is not valid native journal JSON")
    if not isinstance(record, dict) or record.get("_HOSTNAME") != node:
        fail(f"{node}: record {line} has a missing or different source hostname")
    for field in ("__CURSOR", "_BOOT_ID", "__REALTIME_TIMESTAMP", "__MONOTONIC_TIMESTAMP"):
        if not isinstance(record.get(field), str) or not record[field]:
            fail(f"{node}: record {line} has no native {field}")
    for field in ("__REALTIME_TIMESTAMP", "__MONOTONIC_TIMESTAMP"):
        if not record[field].isdigit():
            fail(f"{node}: record {line} has an invalid {field}")
    try:
        utc(int(record["__REALTIME_TIMESTAMP"]))
    except (OverflowError, OSError, ValueError):
        fail(f"{node}: record {line} has an out-of-range realtime timestamp")
    return record


def selected(record: dict) -> bool:
    return record.get("_TRANSPORT") == "kernel" or record.get("_SYSTEMD_UNIT") in ("k3s.service", "k3s-agent.service")


def prepare(bundle: Path, output: Path, nodes: list[str] | None = None) -> dict:
    bundle, output = bundle.resolve(), output.resolve()
    if output == ROOT or ROOT in output.parents:
        fail("choose a private output directory outside this repository")
    source_manifest = bundle / "manifest.json"
    if source_manifest.is_symlink():
        fail("the input manifest must not be a symlink")
    manifest_bytes = source_manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        fail("the evidence manifest must be an object")
    captured = manifest.get("captured_at_utc", "")
    if not isinstance(captured, str) or not re.fullmatch(r"\d{8}T\d{6}Z", captured):
        fail("the evidence manifest has no valid capture timestamp")
    if not isinstance(manifest.get("nodes"), dict) or not manifest["nodes"]:
        fail("the evidence manifest has no nodes")
    selected_nodes = sorted(nodes or manifest["nodes"])
    if len(set(selected_nodes)) != len(selected_nodes):
        fail("duplicate selected node")
    snapshot = captured + "-" + hashlib.sha256(manifest_bytes).hexdigest()[:12]
    report = {
        "format_version": 1, "snapshot": snapshot, "captured_at_utc": captured,
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "selection": "_TRANSPORT=kernel OR _SYSTEMD_UNIT in [k3s.service,k3s-agent.service]",
        "interpretation": "Historical replay of retained records; previously delivered records may be duplicated. Counts are replay counts, not proven lost or unique central records.",
        "nodes": {},
    }
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        for node in selected_nodes:
            if not isinstance(node, str) or not NODE.fullmatch(node) or node not in manifest["nodes"]:
                fail("the selected node is invalid or absent from the evidence manifest")
            node_capture = manifest["nodes"][node]
            if not isinstance(node_capture, dict) or not isinstance(node_capture.get("journal"), dict):
                fail(f"{node}: missing journal capture metadata")
            capture = node_capture["journal"]
            if type(capture.get("returncode")) is not int or capture["returncode"] != 0 or capture.get("truncated") is not False or capture.get("timed_out") is not False:
                fail(f"{node}: journal capture failed, timed out, or was truncated")
            if type(capture.get("bytes")) is not int or not 0 < capture["bytes"] <= MAX_INPUT_BYTES:
                fail(f"{node}: journal capture size is invalid or exceeds the input bound")
            if capture.get("file") != f"{node}-journal.json.gz":
                fail(f"{node}: unexpected journal capture filename")
            source = bundle / capture["file"]
            if source.is_symlink() or not source.is_file():
                fail(f"{node}: journal capture is missing or is a symlink")
            destination = output / f".{node}.jsonl"
            total = records = kept = size = 0
            earliest = latest = None
            boots: set[str] = set()
            cursors: set[str] = set()
            with gzip.open(source, "rb") as original, private_file(destination) as replay:
                while raw := original.readline(MAX_RECORD_BYTES + 1):
                    total += len(raw)
                    records += 1
                    if total > capture["bytes"]:
                        fail(f"{node}: decompressed bytes exceed the capture manifest")
                    record = parse_record(raw, node, records)
                    if not selected(record):
                        continue
                    if record["__CURSOR"] in cursors:
                        fail(f"{node}: duplicate native cursor in source capture")
                    cursors.add(record["__CURSOR"])
                    size += len(raw)
                    if size > MAX_OUTPUT_BYTES:
                        fail(f"{node}: selected replay exceeds the 256 MiB node limit")
                    replay.write(raw)
                    kept += 1
                    timestamp = int(record["__REALTIME_TIMESTAMP"])
                    earliest = timestamp if earliest is None else min(earliest, timestamp)
                    latest = timestamp if latest is None else max(latest, timestamp)
                    boots.add(record["_BOOT_ID"])
                replay.flush()
                os.fsync(replay.fileno())
            if total != capture["bytes"] or not kept:
                fail(f"{node}: capture byte count differs or no selected records exist")
            checksum = digest_file(destination)
            filename = f"{snapshot}-{node}-{checksum[:12]}.jsonl"
            destination.rename(output / filename)
            report["nodes"][node] = {
                "hostname": node, "file": filename, "sha256": checksum,
                "sha1": digest_file(output / filename, "sha1"), "bytes": size,
                "records": kept, "source_records": records, "source_bytes": total,
                "source_file_sha256": digest_file(source), "boot_ids": sorted(boots),
                "earliest_realtime_us": str(earliest), "latest_realtime_us": str(latest),
                "earliest_realtime_utc": utc(earliest), "latest_realtime_utc": utc(latest),
                "unique_source_cursors": len(cursors),
            }
        with private_file(output / "manifest.json") as handle:
            handle.write((json.dumps(report, indent=2) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        shutil.rmtree(output)
        raise
    return report


def verify(directory: Path, node: str) -> dict:
    directory = directory.resolve()
    manifest = json.loads((directory / "manifest.json").read_bytes())
    if not isinstance(manifest, dict) or not NODE.fullmatch(node) or manifest.get("format_version") != 1:
        fail("invalid replay manifest format or selected node")
    snapshot = manifest.get("snapshot", "")
    if not isinstance(snapshot, str) or not re.fullmatch(r"\d{8}T\d{6}Z-[a-f0-9]{12}", snapshot):
        fail("invalid replay snapshot identity")
    if not isinstance(manifest.get("nodes"), dict):
        fail("the replay manifest has no node mapping")
    entry = manifest["nodes"].get(node, {})
    if not isinstance(entry, dict):
        fail(f"{node}: invalid replay node metadata")
    checksum = entry.get("sha256", "")
    if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
        fail(f"{node}: invalid replay checksum")
    expected = f"{snapshot}-{node}-{checksum[:12]}.jsonl"
    if entry.get("hostname") != node or entry.get("file") != expected:
        fail(f"{node}: replay hostname or filename does not match its manifest identity")
    source = directory / expected
    if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= MAX_OUTPUT_BYTES:
        fail(f"{node}: replay is missing, a symlink, empty, or exceeds 256 MiB")
    if source.stat().st_size != entry.get("bytes") or digest_file(source) != checksum or digest_file(source, "sha1") != entry.get("sha1"):
        fail(f"{node}: replay file size or checksum differs from the manifest")
    count = 0
    cursors: set[str] = set()
    with source.open("rb") as handle:
        while raw := handle.readline(MAX_RECORD_BYTES + 1):
            count += 1
            record = parse_record(raw, node, count)
            if not selected(record):
                fail(f"{node}: replay includes a record outside the selected sources")
            if record["__CURSOR"] in cursors:
                fail(f"{node}: duplicate native cursor in prepared replay")
            cursors.add(record["__CURSOR"])
    if count != entry.get("records") or len(cursors) != entry.get("unique_source_cursors"):
        fail(f"{node}: replay record count differs from the manifest")
    return {"snapshot": snapshot, **entry}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--bundle", type=Path, help="private collect-os-incident.py directory")
    source.add_argument("--verify", type=Path, help="verify one prepared node replay without changes")
    parser.add_argument("--output", type=Path, help="new private directory outside Git")
    parser.add_argument("--node", action="append", help="source hostname; repeat to select nodes")
    options = parser.parse_args()
    try:
        if options.verify:
            if options.output or not options.node or len(options.node) != 1:
                parser.error("--verify requires exactly one --node and no --output")
            print(json.dumps(verify(options.verify, options.node[0])))
        else:
            if not options.output:
                parser.error("--bundle requires --output")
            report = prepare(options.bundle, options.output, options.node)
            print(json.dumps({"directory": str(options.output.resolve()), "snapshot": report["snapshot"], "nodes": report["nodes"]}, indent=2))
    except (OSError, ValueError, TypeError, KeyError, EOFError) as error:
        parser.exit(1, f"Backfill preparation/verification failed: {error}\n")


if __name__ == "__main__":
    main()
