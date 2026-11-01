import copy
import json
import unittest
import urllib.error

import reconcile as r


POLICY = {
    "controlPlaneNamespaces": "cattle-monitoring-system,cups",
    "controlPlaneTag": "storage-control-plane",
    "workerTag": "storage-worker",
}


def fixture():
    nodes, lh_nodes = [], []
    for i in range(1, 9):
        pool = "control-plane" if i <= 3 else "worker"
        labels = {r.LABEL: pool}
        if i <= 3:
            labels["node-role.kubernetes.io/control-plane"] = "true"
        name = f"n{i}"
        nodes.append({"metadata": {"name": name, "labels": labels, "resourceVersion": "1"},
                      "spec": {}, "status": {"conditions": [{"type": "Ready", "status": "True"}]}})
        lh_nodes.append({"metadata": {"name": name, "resourceVersion": "1"},
                         "spec": {"tags": [r.tag_for(pool, POLICY)]}})
    volume = {"metadata": {"name": "v", "resourceVersion": "1"},
              "spec": {"nodeSelector": ["storage-worker"], "size": "4096", "numberOfReplicas": 3, "accessMode": "rwo"},
              "status": {"state": "attached", "robustness": "healthy", "currentNodeID": "n4"}}
    replicas = [{"metadata": {"name": f"r{i}", "uid": f"uid-{i}", "resourceVersion": "1"},
                 "spec": {"volumeName": "v", "nodeID": node, "active": True, "healthyAt": "now", "failedAt": ""},
                 "status": {"currentState": "running"}} for i, node in enumerate(["n1", "n4", "n5"])]
    return {r.CORE + "/nodes": nodes, r.LH + "/nodes": lh_nodes,
            r.CORE + "/persistentvolumeclaims": [{"metadata": {"namespace": "devfeed"}, "spec": {"volumeName": "v"}}],
            r.LH + "/volumes": [volume], r.LH + "/replicas": replicas}


class FakeAPI:
    def __init__(self, data):
        self.data, self.patches = data, []

    def items(self, path):
        return copy.deepcopy(self.data[path])

    def patch(self, path, obj, operations):
        self.patches.append((path, operations))



class PoolPolicyTests(unittest.TestCase):
    def test_misplaced_replicas_are_reported_without_storage_operations(self):
        api = FakeAPI(fixture())
        self.assertEqual(r.run_once(api, POLICY), "blocked")
        self.assertEqual(api.patches, [])

    def test_custom_tags_preserved_and_opposite_pool_removed(self):
        self.assertEqual(r.selectors(["ssd", "storage-control-plane"], "storage-worker", POLICY), ["ssd", "storage-worker"])

    def test_home_assistant_consumer_is_worker(self):
        self.assertEqual(r.claim_pool({"metadata": {"namespace": "home-assistant"}}, POLICY), "worker")
        self.assertEqual(r.claim_pool({"metadata": {"namespace": "cattle-monitoring-system"}}, POLICY), "control-plane")

    def test_optimistic_patch_uses_resource_version_precondition(self):
        api = object.__new__(r.API)
        calls = []
        api.request = lambda *args: calls.append(args)
        api.patch("/resource", {"metadata": {"resourceVersion": "42"}}, [{"op": "add", "path": "/value", "value": "x"}])
        self.assertEqual(calls[0][2][0], {"op": "test", "path": "/metadata/resourceVersion", "value": "42"})


class RetirementAPI:
    def __init__(self):
        self.references = {r.CORE + "/persistentvolumeclaims": [], r.CORE + "/persistentvolumes": []}
        self.classes = [
            {"metadata": {"name": name, "uid": name + "-uid", "resourceVersion": "7", "annotations": {}},
             "provisioner": "driver.longhorn.io", "parameters": {"nodeSelector": tag}}
            for name, tag in [("longhorn", ""), ("longhorn-workers", "storage-worker"),
                              ("longhorn-control-plane", "storage-control-plane")]
        ]
        self.classes[0]["metadata"]["annotations"][r.DEFAULT_CLASS] = "true"
        self.config = {"metadata": {"resourceVersion": "8"}, "spec": {
            "failurePolicy": "abort", "values": {"persistence": {"createStorageClass": False, "defaultClass": False}},
        }}
        self.source = None
        self.mutations = []

    def items(self, path):
        if path == r.STORAGE:
            return copy.deepcopy(self.classes)
        return copy.deepcopy(self.references[path])

    def request(self, path, method="GET", body=None):
        if method == "DELETE":
            self.mutations.append((path, method, body))
            return {}
        if path == r.CHART_CONFIG:
            return copy.deepcopy(self.config)
        if self.source is not None:
            return self.source
        raise urllib.error.HTTPError(path, 404, "Not found", {}, None)

    def patch(self, path, obj, operations):
        self.mutations.append((path, "PATCH", operations))


RETIREMENT_POLICY = {**POLICY, "retireStorageClass": "longhorn", "workerStorageClass": "longhorn-workers",
                     "controlPlaneStorageClass": "longhorn-control-plane"}


class RetirementTests(unittest.TestCase):
    def test_every_pvc_and_pv_reference_blocks_all_mutations(self):
        for kind in ("persistentvolumeclaims", "persistentvolumes"):
            for phase in ("Pending", "Bound", "Released", "Failed"):
                with self.subTest(kind=kind, phase=phase):
                    api = RetirementAPI()
                    api.references[r.CORE + "/" + kind] = [{"metadata": {"deletionTimestamp": "now"},
                        "spec": {"storageClassName": "longhorn"}, "status": {"phase": phase}}]
                    self.assertEqual(r.retire_storage_class(api, RETIREMENT_POLICY), "waiting-for-storage-class-references")
                    self.assertEqual(api.mutations, [])

    def test_disables_source_only_after_references_are_gone(self):
        api = RetirementAPI()
        api.config["spec"].pop("values")
        self.assertEqual(r.retire_storage_class(api, RETIREMENT_POLICY), "storage-class-source-disable-requested")
        self.assertEqual(api.mutations, [(r.CHART_CONFIG, "PATCH", [{"op": "add", "path": "/spec/values",
            "value": {"persistence": {"createStorageClass": False, "defaultClass": False}}}])])

    def test_existing_source_blocks_default_change_and_deletion(self):
        api = RetirementAPI()
        api.source = {"data": {"storageclass.yaml": "source"}}
        self.assertEqual(r.retire_storage_class(api, RETIREMENT_POLICY), "waiting-for-storage-class-source-removal")
        self.assertEqual(api.mutations, [])

    def test_selects_worker_default_before_deleting_old_class(self):
        api = RetirementAPI()
        self.assertEqual(r.retire_storage_class(api, RETIREMENT_POLICY), "worker-default-selected")
        self.assertEqual(len(api.mutations), 1)
        self.assertEqual(api.mutations[0][0:2], (r.STORAGE + "/longhorn-workers", "PATCH"))
        self.assertEqual(api.mutations[0][2][0]["value"][r.DEFAULT_CLASS], "true")

    def test_restart_after_default_switch_uses_uid_and_version_for_retirement(self):
        api = RetirementAPI()
        api.classes[1]["metadata"]["annotations"][r.DEFAULT_CLASS] = "true"
        self.assertEqual(r.retire_storage_class(api, RETIREMENT_POLICY), "storage-class-retired")
        self.assertEqual(api.mutations, [(r.STORAGE + "/longhorn", "DELETE", {
            "apiVersion": "v1", "kind": "DeleteOptions",
            "preconditions": {"uid": "longhorn-uid", "resourceVersion": "7"},
        })])

    def test_rechecks_references_immediately_before_delete(self):
        api = RetirementAPI()
        api.classes[1]["metadata"]["annotations"][r.DEFAULT_CLASS] = "true"
        original = api.items
        calls = 0
        def items(path):
            nonlocal calls
            if path == r.CORE + "/persistentvolumeclaims":
                calls += 1
                if calls == 2:
                    return [{"spec": {"storageClassName": "longhorn"}}]
            return original(path)
        api.items = items
        self.assertEqual(r.retire_storage_class(api, RETIREMENT_POLICY), "waiting-for-storage-class-references")
        self.assertEqual(api.mutations, [])

    def test_completed_retirement_is_idempotent(self):
        api = RetirementAPI()
        api.classes.pop(0)
        api.classes[0]["metadata"]["annotations"][r.DEFAULT_CLASS] = "true"
        self.assertEqual(r.retire_storage_class(api, RETIREMENT_POLICY), "storage-class-retirement-completed")
        self.assertEqual(api.mutations, [])

    def test_wrong_pool_or_unrelated_default_fails_closed(self):
        for change in ("pool", "default"):
            with self.subTest(change=change):
                api = RetirementAPI()
                if change == "pool":
                    api.classes[1]["parameters"]["nodeSelector"] = "storage-control-plane"
                else:
                    api.classes[2]["metadata"]["annotations"][r.DEFAULT_CLASS] = "true"
                with self.assertRaises(RuntimeError):
                    r.retire_storage_class(api, RETIREMENT_POLICY)
                self.assertEqual(api.mutations, [])


if __name__ == "__main__":
    unittest.main()
