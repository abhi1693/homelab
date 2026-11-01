import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("policy", Path(__file__).with_name("policy.py"))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PolicyTests(unittest.TestCase):
    def test_patch_preserves_cluster_identity_scheduling_and_customization(self):
        for provisioning in (True, False):
            obj = {"metadata": {"uid": "uid", "resourceVersion": "7"},
                   "spec": {"clientID": "existing", "kubeConfigSecret": "existing",
                            "agentAffinity": {"nodeAffinity": {"existing": True}},
                            "fleetAgentDeploymentCustomization": {"appendTolerations": [{"key": "existing"}]}}}
            before = copy.deepcopy(obj)
            ops = p.operations(obj, provisioning)
            self.assertEqual(obj, before)
            self.assertEqual(ops[:2], [
                {"op": "test", "path": "/metadata/uid", "value": "uid"},
                {"op": "test", "path": "/metadata/resourceVersion", "value": "7"}])
            self.assertEqual(len(ops), 3)
            if provisioning:
                self.assertEqual(ops[-1]["value"]["appendTolerations"], [{"key": "existing"}])
                obj["spec"]["fleetAgentDeploymentCustomization"] = ops[-1]["value"]
            else:
                obj["spec"]["agentResources"] = ops[-1]["value"]
            self.assertEqual(p.operations(obj, provisioning), [])
            for key in ("clientID", "kubeConfigSecret", "agentAffinity"):
                self.assertEqual(obj["spec"][key], before["spec"][key])

    def test_reads_and_patches_only_the_named_local_cluster(self):
        paths = []
        def request(path, patch=None):
            paths.append((path, patch))
            return {"metadata": {"uid": "uid", "resourceVersion": "1"}, "spec": {}}
        self.assertTrue(p.apply(request, False))
        self.assertEqual([x[0] for x in paths], [
            "/apis/fleet.cattle.io/v1alpha1/namespaces/fleet-local/clusters/local"] * 2)


if __name__ == "__main__":
    unittest.main()
