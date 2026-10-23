"""Run the production BTF gate with actual Ansible and synthetic stat results."""

import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1]
GUARD = ROLE / "tasks/kernel_btf.yml"


class KernelBtfTests(unittest.TestCase):
    def test_bootstrap_and_validation_share_the_kernel_gate(self):
        for entrypoint in ("main", "validation"):
            with self.subTest(entrypoint=entrypoint):
                tasks = yaml.safe_load((ROLE / f"tasks/{entrypoint}.yml").read_text())
                imports = [task for task in tasks
                           if task.get("ansible.builtin.import_tasks") == GUARD.name]
                self.assertEqual(len(imports), 1)
                self.assertNotIn("when", imports[0])

    def test_actual_ansible_version_and_all_node_boundaries(self):
        executable = shutil.which("ansible-playbook")
        self.assertIsNotNone(executable, "Install the repository's Ansible validation dependencies")
        source = yaml.safe_load(GUARD.read_text())
        self.assertEqual(len(source), 1)
        block = source[0]["block"]
        probes = [task for task in block if "ansible.builtin.stat" in task]
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0]["ansible.builtin.stat"]["path"], "/sys/kernel/btf/vmlinux")
        self.assertEqual(probes[0]["delegate_to"], "{{ item }}")
        self.assertEqual(probes[0]["loop"], "{{ groups['k3s_nodes'] }}")
        self.assertTrue(all("ansible.builtin.stat" in task or "ansible.builtin.assert" in task
                            for task in block))
        fixtures = [
            ("1.9.99", False, True, False),
            ("1.19.99", False, True, False),
            ("1.20.1", False, True, False),
            ("1.20.1", True, True, False),
            ("1.20.2", False, False, True),
            ("1.20.3", False, False, True),
            ("1.20.10", False, False, True),
            ("1.21", False, False, True),
            ("1.21.0", False, False, True),
            ("1.20.2", True, True, True),
            ("1.20.3", True, True, True),
            ("1.21.0", True, True, True),
        ]
        for version, every_node_has_btf, accepted, probe_expected in fixtures:
            with self.subTest(version=version, every_node_has_btf=every_node_has_btf):
                tasks = copy.deepcopy(source)
                # Replace only external filesystem/SSH I/O. Keep the production
                # block condition, version test, loop and assert module unchanged.
                index = next(i for i, task in enumerate(tasks[0]["block"])
                             if "ansible.builtin.stat" in task)
                tasks[0]["block"][index] = {
                    "name": "Provide synthetic per-node kernel stat results",
                    "ansible.builtin.set_fact": {
                        "fixture_kernel_probe_ran": True,
                        "cilium_node_btf": {"results": [
                            {"item": "fixture-node-a", "stat": {"exists": True}},
                            {"item": "fixture-node-b", "stat": {"exists": every_node_has_btf}},
                        ]},
                    },
                }
                tasks.append({
                    "name": "Check that the production condition selected the kernel probe",
                    "ansible.builtin.assert": {
                        "that": ["fixture_kernel_probe_ran == fixture_probe_expected"],
                        "fail_msg": "The version boundary did not select the expected probe",
                    },
                })
                play = [{
                    "name": "Exercise the Cilium kernel gate without hosts or cluster access",
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": {
                        "cilium": {"version": version},
                        "fixture_kernel_probe_ran": False,
                        "fixture_probe_expected": probe_expected,
                        "cilium_node_btf": {"results": []},
                    },
                    "tasks": tasks,
                }]
                with tempfile.TemporaryDirectory(prefix="cilium-kernel-btf-") as directory:
                    temporary = Path(directory)
                    config = temporary / "ansible.cfg"
                    config.write_text("[defaults]\nvars_plugins_enabled=host_group_vars\n")
                    playbook = temporary / "fixture.yml"
                    playbook.write_text(yaml.safe_dump(play, sort_keys=False))
                    environment = {**os.environ, "ANSIBLE_CONFIG": str(config),
                                   "ANSIBLE_VARS_ENABLED": "host_group_vars",
                                   "ANSIBLE_NOCOLOR": "1"}
                    result = subprocess.run(
                        [executable, "-i", "localhost,", "-c", "local", str(playbook)],
                        cwd=temporary, env=environment, capture_output=True, text=True,
                        timeout=30, check=False,
                    )
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0 if accepted else 2, output)
                if not accepted:
                    self.assertIn(
                        f"Cilium {version} requires kernel BTF on fixture-node-b", output,
                    )
                    self.assertIn("/sys/kernel/btf/vmlinux", output)


if __name__ == "__main__":
    unittest.main()
