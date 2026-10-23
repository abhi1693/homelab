"""Exercise the actual builder/restore/cleanup cache keys with synthetic config."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


APP = Path(__file__).resolve().parents[1]
MANIFESTS = (
    "next-builder-job.yaml",
    "deployment-frontend.yaml",
    "next-build-cleanup-cronjob.yaml",
)


def strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


class BuildCacheKeyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.frontend = root / "hub/frontend"
        self.frontend.mkdir(parents=True)
        for name in (
            "app/page.tsx", "public/logo.svg", "next.config.ts", "package.json",
            "docker-build-next.sh", "scripts/prepare-faro-sourcemaps.mjs",
            "../../package.json", "../../package-lock.json", "../../packages/braces/index.js",
        ):
            path = self.frontend / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic-source\n")
        binary = root / "bin"
        binary.mkdir()
        node = binary / "node"
        node.write_text('#!/bin/sh\nprintf "%s\\n" "$SYNTHETIC_NODE_VERSION"\n')
        node.chmod(0o755)
        self.env = {
            "PATH": str(binary) + os.pathsep + "/usr/bin:/bin",
            "APP_VERSION": "0.2.182",
            "SYNTHETIC_NODE_VERSION": "v26.12.1",
            "NEXT_PUBLIC_SITE_URL": "https://public.invalid",
            "WARDN_HUB_API_INTERNAL_BASE_URL": "http://backend.invalid",
            "PRIVATE_API_TOKEN": "synthetic-private-one",
        }
        self.scripts = []
        for name in MANIFESTS:
            candidates = [text for doc in yaml.safe_load_all((APP / name).read_text())
                          for text in strings(doc) if 'source_key="$(' in text]
            self.assertEqual(len(candidates), 1)
            script = candidates[0]
            version = re.search(r"(?m)^cache_version=([^\n]+)$", script).group(0)
            start = script.index('source_key="$(')
            stop = script.index('\nartifact=', start)
            self.scripts.append(version + "\n" + script[start:stop] + '\nprintf "%s\\n" "$build_key"\n')

    def keys(self, **changes):
        env = self.env | changes
        keys = []
        for script in self.scripts:
            result = subprocess.run(["sh", "-ec", script], cwd=self.frontend,
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, "Cache-key command failed")
            self.assertRegex(result.stdout.strip(), r"^[a-f0-9]{64}$")
            keys.append(result.stdout.strip())
        self.assertEqual(len(set(keys)), 1, "Builder, restore, and cleanup keys diverged")
        return keys[0]

    def test_public_and_internal_configuration_invalidate_all_keys(self):
        baseline = self.keys()
        for change in (
            {"NEXT_PUBLIC_SITE_URL": "https://changed.invalid"},
            {"NEXT_PUBLIC_NEW_FEATURE": "enabled"},
            {"WARDN_HUB_API_INTERNAL_BASE_URL": "http://changed.invalid"},
        ):
            with self.subTest(keys=sorted(change)):
                self.assertNotEqual(self.keys(**change), baseline)

    def test_private_configuration_does_not_enter_public_build_key(self):
        self.assertEqual(self.keys(PRIVATE_API_TOKEN="synthetic-private-two"), self.keys())

    def test_application_and_node_versions_invalidate_all_keys(self):
        baseline = self.keys()
        self.assertNotEqual(self.keys(APP_VERSION="0.2.183"), baseline)
        self.assertNotEqual(self.keys(SYNTHETIC_NODE_VERSION="v26.12.2"), baseline)

    def test_build_helpers_and_workspace_lock_invalidate_all_keys(self):
        baseline = self.keys()
        for name in ("docker-build-next.sh", "scripts/prepare-faro-sourcemaps.mjs",
                     "../../package.json", "../../package-lock.json", "../../packages/braces/index.js"):
            with self.subTest(path=name):
                path = self.frontend / name
                original = path.read_bytes()
                path.write_bytes(original + b"synthetic-change\n")
                self.assertNotEqual(self.keys(), baseline)
                path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
