"""Exercise requirement updates against actual installed-package metadata."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CHECKER = Path(__file__).resolve().parents[1] / "verify_plugins.py"
PACKAGE = "codex-netbox-plugin-fixture"


class VerifyPluginsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.requirements = self.root / "required-plugins.txt"
        self.metadata = self.root / "codex_netbox_plugin_fixture.dist-info"

    def install_metadata(self, installed):
        self.metadata.mkdir(exist_ok=True)
        (self.metadata / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {PACKAGE}\nVersion: {installed}\n")

    def run_checker(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.root)
        return subprocess.run([sys.executable, str(CHECKER), str(self.requirements)],
                              env=env, text=True, capture_output=True, timeout=10)

    def test_requirement_update_requires_new_installed_version_without_checker_edits(self):
        self.requirements.write_text(f"# Image plugin pins\n\n{PACKAGE}==1.0.0 # release pin\n")
        self.install_metadata("1.0.0")
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)

        self.requirements.write_text(f"{PACKAGE}==1.0.1\n")
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected 1.0.1, installed 1.0.0", result.stderr)

        self.install_metadata("1.0.1")
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_plugin_fails(self):
        self.requirements.write_text(f"{PACKAGE}==1.0.0\n")
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(PACKAGE, result.stderr)

    def test_unpinned_and_empty_requirements_fail(self):
        self.install_metadata("1.0.0")
        for requirement in (f"{PACKAGE}>=1.0.0\n", "# no plugins\n"):
            with self.subTest(requirement=requirement):
                self.requirements.write_text(requirement)
                result = self.run_checker()
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
