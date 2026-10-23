"""Execute publisher probes against the verbatim released runtime-file helper.

The helper fixture is from DevFeed 4bedaeb9a6419f25f59d46eeb45b9242071f1aa2,
packages/core/src/runtime_files.py. Only package metadata is omitted from the
isolated subprocess; marker and probe behavior use their actual source bytes.
"""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import yaml


APP = Path(__file__).resolve().parents[1]
HELPER = Path(__file__).resolve().parent / "fixtures/runtime_files.py"
HELPER_SHA256 = "f2c7f53df7b669e85c034471fcd373402ecc58e2ad07e62b958c9e5dd4ee10fc"
IMPORT_GUARD = """
import importlib.abc
import sys

class RejectPublisherDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'sqlalchemy' or fullname.startswith('sqlalchemy.') or (
            fullname == 'devfeed_core.analysis'
            or fullname.startswith('devfeed_core.analysis.')
            or fullname == 'devfeed_admin_api'
            or fullname.startswith('devfeed_admin_api.')
        ):
            raise ImportError('Health probes must not load publisher dependencies')

sys.meta_path.insert(0, RejectPublisherDependencies())
"""


def probes():
    for role in ("pipeline", "reports"):
        document = yaml.safe_load((APP / f"deployment-read-model-{role}.yaml").read_text())
        container = document["spec"]["template"]["spec"]["containers"][0]
        for name in ("startupProbe", "readinessProbe", "livenessProbe"):
            yield role, name, container[name]["exec"]["command"]


class ReadModelProbeTest(unittest.TestCase):
    def setUp(self):
        self.assertEqual(hashlib.sha256(HELPER.read_bytes()).hexdigest(), HELPER_SHA256)

    def check(self, prepare, expected):
        for role, name, command in probes():
            with self.subTest(role=role, probe=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                modules = root / "modules"
                package = modules / "devfeed_core"
                package.mkdir(parents=True)
                (package / "__init__.py").write_text("")
                shutil.copyfile(HELPER, package / "runtime_files.py")
                (modules / "sitecustomize.py").write_text(IMPORT_GUARD)
                runtime = root / f"devfeed-runtime-{os.geteuid()}"
                prepare(root, runtime, role)
                self.assertEqual(command[:2], ["python", "-c"])
                result = subprocess.run(
                    [sys.executable, *command[1:]],
                    env={
                        "PATH": os.defpath,
                        "PYTHONPATH": str(modules),
                        "PYTHONNOUSERSITE": "1",
                        "TMPDIR": str(root),
                    },
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.stdout, "")

    @staticmethod
    def marker(runtime, role, age):
        runtime.mkdir(mode=0o700)
        marker = runtime / f"{role}-heartbeat"
        marker.write_text("actual heartbeat")
        marker.chmod(0o600)
        timestamp = time.time() - age
        os.utime(marker, (timestamp, timestamp))

    def test_fresh_markers_pass_without_loading_analysis_or_sqlalchemy(self):
        self.check(lambda root, runtime, role: self.marker(runtime, role, 0), 0)

    def test_marker_within_the_original_180_second_window_passes(self):
        self.check(lambda root, runtime, role: self.marker(runtime, role, 170), 0)

    def test_markers_older_than_180_seconds_fail(self):
        self.check(lambda root, runtime, role: self.marker(runtime, role, 181), 1)

    def test_future_timestamp_preserves_the_existing_age_check(self):
        self.check(lambda root, runtime, role: self.marker(runtime, role, -60), 0)

    def test_missing_marker_fails_in_an_owned_private_directory(self):
        self.check(lambda root, runtime, role: runtime.mkdir(mode=0o700), 1)

    def test_missing_runtime_directory_cannot_report_healthy(self):
        self.check(lambda root, runtime, role: None, 1)

    def test_a_fresh_marker_in_a_nonprivate_directory_fails(self):
        def prepare(root, runtime, role):
            self.marker(runtime, role, 0)
            runtime.chmod(0o755)

        self.check(prepare, 1)

    def test_a_symlinked_runtime_directory_is_rejected_even_with_a_private_target(self):
        def prepare(root, runtime, role):
            target = root / "private-target"
            self.marker(target, role, 0)
            runtime.symlink_to(target, target_is_directory=True)

        self.check(prepare, 1)

    def test_a_runtime_directory_replaced_by_a_regular_file_fails(self):
        self.check(lambda root, runtime, role: runtime.write_text("not a directory"), 1)


if __name__ == "__main__":
    unittest.main()
