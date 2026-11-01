#!/usr/bin/env python3
"""Historical replay must reject incomplete evidence and preserve native records."""

from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "prepare-os-log-backfill.py"
SPEC = importlib.util.spec_from_file_location("os_log_backfill", SOURCE)
assert SPEC is not None and SPEC.loader is not None
BACKFILL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKFILL)


class BackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="os-log-backfill-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle, self.output = self.root / "bundle", self.root / "prepared"
        self.bundle.mkdir(mode=0o700)

    def record(self, cursor: str, *, unit: str = "k3s.service", transport: str = "stdout", hostname: str = "k8s-rpi3") -> bytes:
        # Deliberately noncompact JSON: output must preserve bytes, not reencode.
        return (json.dumps({
            "__CURSOR": cursor, "__REALTIME_TIMESTAMP": "1793000000000000",
            "__MONOTONIC_TIMESTAMP": "123456", "_BOOT_ID": "boot-identity",
            "_HOSTNAME": hostname, "_SYSTEMD_UNIT": unit, "_TRANSPORT": transport,
            "MESSAGE": "private original with spaces and embedded \\n separator",
        }, ensure_ascii=False) + "\n").encode()

    def capture(self, raw: bytes, **overrides: object) -> None:
        with gzip.open(self.bundle / "k8s-rpi3-journal.json.gz", "wb") as handle:
            handle.write(raw)
        capture = {"returncode": 0, "bytes": len(raw), "truncated": False, "timed_out": False,
                   "file": "k8s-rpi3-journal.json.gz", **overrides}
        (self.bundle / "manifest.json").write_text(json.dumps({
            "captured_at_utc": "20261026T144842Z", "nodes": {"k8s-rpi3": {"journal": capture}},
        }))

    def test_filter_preserves_complete_native_bytes_identity_and_private_permissions(self) -> None:
        server = self.record("server")
        kernel = self.record("kernel", unit="k3s.service", transport="kernel")
        agent = self.record("agent", unit="k3s-agent.service")
        other = self.record("other", unit="sshd.service")
        self.capture(server + other + kernel + agent)
        report = BACKFILL.prepare(self.bundle, self.output)
        item = report["nodes"]["k8s-rpi3"]
        self.assertEqual((self.output / item["file"]).read_bytes(), server + kernel + agent)
        self.assertEqual(item["records"], 3)
        self.assertEqual(item["source_records"], 4)
        self.assertEqual(item["unique_source_cursors"], 3)
        self.assertEqual(item["boot_ids"], ["boot-identity"])
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.output / item["file"]).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.output / "manifest.json").stat().st_mode), 0o600)
        verified = BACKFILL.verify(self.output, "k8s-rpi3")
        self.assertEqual(verified["sha256"], item["sha256"])

    def test_failed_truncated_or_timeout_capture_is_rejected_without_partial_output(self) -> None:
        for override in ({"returncode": 1}, {"truncated": True}, {"timed_out": True}):
            with self.subTest(override=override):
                self.capture(self.record("one"), **override)
                with self.assertRaisesRegex(ValueError, "capture failed"):
                    BACKFILL.prepare(self.bundle, self.output)
                self.assertFalse(self.output.exists())

    def test_malformed_json_is_rejected_even_when_capture_succeeded(self) -> None:
        self.capture(self.record("one") + b'{"MESSAGE":bad}\n')
        with self.assertRaisesRegex(ValueError, "native journal JSON"):
            BACKFILL.prepare(self.bundle, self.output)
        self.assertFalse(self.output.exists())

    def test_manifest_byte_mismatch_is_rejected(self) -> None:
        self.capture(self.record("one"), bytes=1)
        with self.assertRaisesRegex(ValueError, "bytes exceed"):
            BACKFILL.prepare(self.bundle, self.output)

    def test_source_identity_mismatch_is_rejected(self) -> None:
        self.capture(self.record("one", hostname="k8s-rpi2"))
        with self.assertRaisesRegex(ValueError, "source hostname"):
            BACKFILL.prepare(self.bundle, self.output)

    def test_duplicate_native_cursor_is_rejected(self) -> None:
        self.capture(self.record("same") + self.record("same"))
        with self.assertRaisesRegex(ValueError, "duplicate native cursor"):
            BACKFILL.prepare(self.bundle, self.output)

    def test_size_guard_is_enforced_before_a_replay_can_be_staged(self) -> None:
        self.capture(self.record("one"))
        with patch.object(BACKFILL, "MAX_OUTPUT_BYTES", 32):
            with self.assertRaisesRegex(ValueError, "256 MiB"):
                BACKFILL.prepare(self.bundle, self.output)
        self.assertFalse(self.output.exists())

    def test_verified_replay_rejects_tampering_and_wrong_node_selection(self) -> None:
        self.capture(self.record("one"))
        report = BACKFILL.prepare(self.bundle, self.output)
        with self.assertRaisesRegex(ValueError, "checksum"):
            BACKFILL.verify(self.output, "k8s-rpi2")
        item = report["nodes"]["k8s-rpi3"]
        with (self.output / item["file"]).open("ab") as handle:
            handle.write(b"tamper\n")
        with self.assertRaisesRegex(ValueError, "size or checksum"):
            BACKFILL.verify(self.output, "k8s-rpi3")

    def test_existing_output_is_never_replaced(self) -> None:
        self.capture(self.record("one"))
        BACKFILL.prepare(self.bundle, self.output)
        before = (self.output / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            BACKFILL.prepare(self.bundle, self.output)
        self.assertEqual((self.output / "manifest.json").read_bytes(), before)

    def test_private_records_cannot_be_written_inside_the_repository(self) -> None:
        self.capture(self.record("one"))
        with self.assertRaisesRegex(ValueError, "outside this repository"):
            BACKFILL.prepare(self.bundle, BACKFILL.ROOT / "private-backfill-must-not-exist")

    def test_truncated_gzip_is_rejected_even_with_successful_capture_metadata(self) -> None:
        self.capture(self.record("one"))
        source = self.bundle / "k8s-rpi3-journal.json.gz"
        source.write_bytes(source.read_bytes()[:-5])
        with self.assertRaises((EOFError, OSError)):
            BACKFILL.prepare(self.bundle, self.output)
        self.assertFalse(self.output.exists())

    def test_malformed_manifest_shape_is_rejected(self) -> None:
        (self.bundle / "manifest.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "manifest must be an object"):
            BACKFILL.prepare(self.bundle, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
