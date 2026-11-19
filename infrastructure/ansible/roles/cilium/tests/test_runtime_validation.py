"""Exercise runtime validation without a host CLI, bootstrap files or a cluster."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1]


def agent(name, node, ready=True, terminating=False):
    pod = {"metadata": {"name": name}, "spec": {"nodeName": node},
           "status": {"phase": "Running", "conditions": [
               {"type": "Ready", "status": "True" if ready else "False"}]}}
    if terminating:
        pod["metadata"]["deletionTimestamp"] = "2026-01-01T00:00:00Z"
    return pod


class RuntimeValidationTests(unittest.TestCase):
    def test_entrypoint_uses_runtime_checks_without_bootstrap_prerequisites(self):
        tasks = yaml.safe_load((ROLE / "tasks/validation.yml").read_text())
        self.assertTrue(any(t.get("ansible.builtin.import_tasks") == "validation_agents.yml"
                            for t in tasks))
        source = (ROLE / "tasks/validation.yml").read_text()
        self.assertNotIn("/usr/local/bin/cilium", source)
        self.assertNotIn("/var/lib/rancher/k3s/server/manifests/traefik-config.yaml", source)
        self.assertNotIn("ansible.builtin.stat", source)
        self.assertIn("Check bundled Traefik HelmChartConfig", source)

    def test_actual_ansible_node_coverage_readiness_and_agent_health(self):
        executable = shutil.which("ansible-playbook")
        self.assertIsNotNone(executable)
        healthy = [agent("agent-a", "node-a"), agent("agent-b", "node-b")]
        cases = [
            ("healthy_without_bootstrap_files", healthy, "OK", True),
            ("terminating_old_agent_ignored", healthy + [agent("old", "node-a", terminating=True)], "OK", True),
            ("no_agents", [], "OK", False),
            ("missing_node", healthy[:1], "OK", False),
            ("duplicate_node", [agent("a", "node-a"), agent("b", "node-a")], "OK", False),
            ("not_ready", [healthy[0], agent("b", "node-b", ready=False)], "OK", False),
            ("terminating_only_agent", [healthy[0], agent("b", "node-b", terminating=True)], "OK", False),
            ("ready_pod_unhealthy_agent", healthy, "Warning", False),
        ]
        for name, pods, health, accepted in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="cilium-runtime-") as directory:
                temporary = Path(directory)
                fake = temporary / "k3s"
                fake.write_text(
                    "#!/usr/bin/env python3\nimport sys\n"
                    "assert sys.argv[1:5] == ['kubectl', '-n', 'kube-system', 'exec']\n"
                    "assert sys.argv[5] in ['agent-a', 'agent-b']\n"
                    "assert sys.argv[6:] == ['-c', 'cilium-agent', '--', 'cilium-dbg', 'status', '--brief']\n"
                    f"print({health!r})\n"
                )
                fake.chmod(0o700)
                tasks = copy.deepcopy(yaml.safe_load((ROLE / "tasks/validation_agents.yml").read_text()))
                for task in tasks:
                    if "ansible.builtin.command" in task:
                        task["ansible.builtin.command"]["argv"][0] = str(fake)
                        task["retries"] = 1
                        task["delay"] = 0
                play = [{"name": name, "hosts": "localhost", "gather_facts": False,
                         "vars": {"cilium_validation_nodes": {"stdout": json.dumps({"items": [
                             {"metadata": {"name": "node-a"}}, {"metadata": {"name": "node-b"}}]})},
                                  "cilium_validation_agents": {"stdout": json.dumps({"items": pods})}},
                         "tasks": tasks}]
                config = temporary / "ansible.cfg"
                config.write_text("[defaults]\nvars_plugins_enabled=host_group_vars\n")
                path = temporary / "fixture.yml"
                path.write_text(yaml.safe_dump(play, sort_keys=False))
                result = subprocess.run(
                    [executable, "-i", "localhost,", "-c", "local", str(path)],
                    cwd=temporary,
                    env={**os.environ, "ANSIBLE_CONFIG": str(config),
                         "ANSIBLE_VARS_ENABLED": "host_group_vars", "ANSIBLE_NOCOLOR": "1"},
                    capture_output=True, text=True, timeout=30, check=False,
                )
                self.assertEqual(result.returncode, 0 if accepted else 2, result.stdout + result.stderr)
                self.assertIn("changed=0", result.stdout)
                if not accepted:
                    self.assertNotIn("has no attribute", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
