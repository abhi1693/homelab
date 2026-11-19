"""Protect the direct kubectl arguments and monthly lifecycle ordering."""
from pathlib import Path
import unittest

import yaml

APP = Path(__file__).resolve().parents[1]


class MonthlyScalerTests(unittest.TestCase):
    def setUp(self):
        self.start, self.stop = list(yaml.safe_load_all((APP / "monthly-scaler.yaml").read_text()))

    def test_jsonpath_wait_arguments_do_not_include_shell_quotes(self):
        waits = []
        for cron in (self.start, self.stop):
            pod = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]
            for container in pod["initContainers"] + pod["containers"]:
                if container["command"] != ["/bin/kubectl"]:
                    continue
                for arg in container["args"]:
                    if arg.startswith("--for=jsonpath="):
                        waits.append(arg)
                        self.assertRegex(arg, r"^--for=jsonpath=\{\.[a-zA-Z0-9.]+\}=[0-9]+$")
        self.assertEqual(waits, ["--for=jsonpath={.spec.replicas}=1"])

    def test_start_waits_for_dependencies_before_enabling_maintenance(self):
        pod = self.start["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        self.assertEqual([c["name"] for c in pod["initContainers"]], [
            "start-pooler", "wait-for-pooler-scale", "wait-for-pooler",
            "start-firefly", "wait-for-firefly", "resume-firefly-cron",
        ])
        self.assertIn("--replicas=1", pod["initContainers"][3]["args"])
        self.assertIn('--patch={"spec":{"suspend":false}}', pod["initContainers"][-1]["args"])

    def test_monthly_window_and_runtime_ownership_remain_explicit(self):
        self.assertEqual(self.start["spec"]["schedule"], "15 2 1 * *")
        self.assertEqual(self.stop["spec"]["schedule"], "17 6 6 * *")
        for cron in (self.start, self.stop):
            self.assertEqual(cron["spec"]["timeZone"], "Asia/Kolkata")
            self.assertEqual(cron["spec"]["concurrencyPolicy"], "Forbid")
        deployment = yaml.safe_load((APP / "deployment.yaml").read_text())
        daily = yaml.safe_load((APP / "cronjob.yaml").read_text())
        self.assertNotIn("replicas", deployment["spec"])
        self.assertNotIn("suspend", daily["spec"])


if __name__ == "__main__":
    unittest.main()
