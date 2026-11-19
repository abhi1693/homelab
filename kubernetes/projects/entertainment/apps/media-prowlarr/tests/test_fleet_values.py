"""Guard Fleet's flat generator inputs and Helm-values classification."""
from pathlib import Path, PurePosixPath
import re
import unittest

import yaml


APP = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[6]


class FleetValuesTests(unittest.TestCase):
    def test_generator_inputs_are_flat_bundle_files(self):
        kustomize = yaml.safe_load((APP / "kustomization.yaml").read_text())
        inputs = [name for item in kustomize["configMapGenerator"] for name in item.get("files", [])]
        self.assertTrue(inputs)
        for name in inputs:
            with self.subTest(name=name):
                self.assertNotIn("=", name, "Fleet's virtual-root generator inputs must be direct files")
                self.assertEqual(PurePosixPath(name).name, name, "Fleet cannot load nested generator inputs")
                self.assertTrue((APP / name).is_file())

    def test_custom_values_are_yaml_checked_and_not_kubernetes_objects(self):
        config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
        hooks = {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}
        custom = str((APP / "custom-definitions-values.yaml").relative_to(ROOT))
        self.assertRegex(custom, hooks["validate-yaml"]["files"])
        exclude = re.compile(hooks["validate-kubernetes"]["exclude"])
        self.assertRegex(custom, exclude)
        for filename in ["configmap.yaml", "custom-definitions-configmap.yaml", "deployment.yaml"]:
            with self.subTest(filename=filename):
                self.assertIsNone(exclude.search(str((APP / filename).relative_to(ROOT))))


if __name__ == "__main__":
    unittest.main()
