"""Keep the native health check cheap and reject invalid heartbeat states."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

APP = Path(__file__).resolve().parents[1]


class HealthTests(unittest.TestCase):
    def run_probe(self, path):
        env = {**os.environ, "MEDIA_SCHEDULE_STATUS_PATH": str(path)}
        return subprocess.run(["sh", str(APP / "health.sh")], env=env,
                              capture_output=True, timeout=3).returncode

    def test_fresh_healthy_heartbeat_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "status.json"
            path.write_text(json.dumps({"healthy": True}, separators=(",", ":")))
            self.assertEqual(self.run_probe(path), 0)

    def test_missing_empty_and_unhealthy_heartbeat_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "status.json"
            self.assertNotEqual(self.run_probe(path), 0)
            path.touch()
            self.assertNotEqual(self.run_probe(path), 0)
            path.write_text('{"healthy":false}')
            self.assertNotEqual(self.run_probe(path), 0)

    def test_stale_and_future_heartbeat_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "status.json"
            path.write_text('{"healthy":true}')
            for stamp in [time.time() - 91, time.time() + 60]:
                os.utime(path, (stamp, stamp))
                self.assertNotEqual(self.run_probe(path), 0)

    def test_manifests_and_generator_use_native_probe(self):
        import yaml
        manifest = yaml.safe_load((APP / "deployment.yaml").read_text())
        container = manifest["spec"]["template"]["spec"]["containers"][0]
        for name in ("startupProbe", "readinessProbe", "livenessProbe"):
            self.assertEqual(container[name]["exec"]["command"], ["sh", "/policy/health.sh"])
        generators = yaml.safe_load((APP / "kustomization.yaml").read_text())["configMapGenerator"]
        self.assertIn("health.sh", generators[0]["files"])
