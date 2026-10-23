"""Exercise each real environment-hash block without runtime credentials."""

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parents[1]
MANIFESTS = (
    "next-builder-job.yaml",
    "deployment.yaml",
    "next-build-cleanup-cronjob.yaml",
)
PREFIXES = (
    "CLERK_", "CLOUDFLARE_", "DODO_", "GA_", "GOOGLE_", "IMGPROXY_",
    "MONTHLY_WINNER_", "NEXT_PUBLIC_", "R2_",
)
EXACT_NAMES = (
    "APP_VERSION", "NODE_VERSION", "CACHE_ENV_PREFIX",
    "NEXT_STATIC_GENERATION_MAX_CONCURRENCY", "NEXT_STATIC_GENERATION_RETRY_COUNT",
    "NEXT_STATIC_PAGE_GENERATION_TIMEOUT", "POSTGRES_DB", "PRODUCT_PRERENDER_LIMIT",
    "USE_CASE_PRERENDER_LIMIT",
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
        self.env = {
            "PATH": "/usr/bin:/bin",
            **{name: "synthetic-one" for name in EXACT_NAMES},
            **{prefix + "SYNTHETIC_CONFIG": "synthetic-one" for prefix in PREFIXES},
            "PRIVATE_RUNTIME_TOKEN": "synthetic-private-one",
        }
        self.blocks = []
        for name in MANIFESTS:
            candidates = [text for doc in yaml.safe_load_all((APP / name).read_text())
                          for text in strings(doc) if 'env_key="$(' in text]
            self.assertEqual(len(candidates), 1)
            script = candidates[0]
            self.assertEqual(re.findall(r"(?m)^cache_version=([^\n]+)$", script),
                             ["next-build-v12"])
            start = script.index('env_key="$(')
            stop = script.index('\nbuild_key=', start)
            self.blocks.append(script[start:stop])
        self.assertEqual(len(set(self.blocks)), 1,
                         "Builder, restore, and cleanup environment-hash blocks diverged")

    def key_for_env(self, env):
        keys = []
        for block in self.blocks:
            result = subprocess.run(
                ["sh", "-ec", block + '\nprintf "%s\\n" "$env_key"\n'],
                cwd=self.temp.name, env=env, capture_output=True, text=True, timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, "Environment-hash command failed")
            self.assertEqual(result.stderr, "", "Environment-hash command emitted diagnostics")
            self.assertRegex(result.stdout, r"^[a-f0-9]{64}\n$")
            keys.append(result.stdout.strip())
        self.assertEqual(len(set(keys)), 1, "Environment hashes differ across manifests")
        return keys[0]

    def key(self, **changes):
        return self.key_for_env(self.env | changes)

    def test_each_build_prefix_change_invalidates_all_three_keys(self):
        baseline = self.key()
        for prefix in PREFIXES:
            with self.subTest(prefix=prefix):
                self.assertNotEqual(self.key(**{prefix + "SYNTHETIC_CONFIG": "synthetic-two"}),
                                    baseline)
                self.assertNotEqual(self.key(**{prefix + "NEW_OPTION": "synthetic-new"}),
                                    baseline)

    def test_each_exact_build_control_invalidates_all_three_keys(self):
        baseline = self.key()
        for name in EXACT_NAMES:
            with self.subTest(name=name):
                self.assertNotEqual(self.key(**{name: "synthetic-two"}), baseline)

    def test_unrelated_private_and_similar_names_are_ignored(self):
        baseline = self.key()
        for name in ("PRIVATE_RUNTIME_TOKEN", "PRODUCTS_API_TOKEN", "DATABASE_URL",
                     "CLERKISH_TOKEN", "NEXT_PUBLICX_TOKEN", "R2X_TOKEN", "APP_VERSION_EXTRA",
                     *PREFIXES):
            with self.subTest(name=name):
                self.assertEqual(self.key(**{name: "synthetic-two"}), baseline)

    def test_empty_prefixed_value_is_still_part_of_the_key(self):
        self.assertNotEqual(self.key(NEXT_PUBLIC_NEW_OPTION=""), self.key())

    def test_environment_order_does_not_change_any_key(self):
        self.assertEqual(self.key_for_env(dict(reversed(list(self.env.items())))), self.key())

    def test_values_are_not_executed_or_printed(self):
        marker = Path(self.temp.name) / "must-not-exist"
        self.assertNotEqual(self.key(NEXT_PUBLIC_SYNTHETIC_CONFIG="$(touch must-not-exist); '$HOME' spaces"),
                            self.key())
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
