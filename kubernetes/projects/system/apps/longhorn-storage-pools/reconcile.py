"""Enforce Longhorn storage pools and guard default storage class retirement."""

import json
import os
from pathlib import Path
import signal
import ssl
import threading
import time
import urllib.request
import urllib.error


LABEL = "home-lab.io/storage-pool"
LH = "/apis/longhorn.io/v1beta2/namespaces/longhorn-system"
CORE = "/api/v1"
STORAGE = "/apis/storage.k8s.io/v1/storageclasses"
CHART_CONFIG = "/apis/helm.cattle.io/v1/namespaces/kube-system/helmchartconfigs/longhorn"
DEFAULT_CLASS = "storageclass.kubernetes.io/is-default-class"
STOP = threading.Event()


def log(event, **fields):
    print(json.dumps({"event": event, **fields}), flush=True)


class API:
    def __init__(self):
        self.base = "https://" + os.environ["KUBERNETES_SERVICE_HOST"] + ":" + os.environ["KUBERNETES_SERVICE_PORT"]
        self.account = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        self.context = ssl.create_default_context(cafile=str(self.account / "ca.crt"))

    def request(self, path, method="GET", body=None):
        # Projected service-account tokens rotate; reopen for each request.
        headers = {"Authorization": "Bearer " + (self.account / "token").read_text().strip()}
        if body is not None:
            headers["Content-Type"] = "application/json-patch+json" if method == "PATCH" else "application/json"
        request = urllib.request.Request(self.base + path, method=method, headers=headers,
                                         data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(request, context=self.context, timeout=15) as response:
            return json.load(response)

    def items(self, path):
        return self.request(path)["items"]

    def patch(self, path, obj, operations):
        return self.request(path, "PATCH", [
            {"op": "test", "path": "/metadata/resourceVersion", "value": obj["metadata"]["resourceVersion"]},
            *operations,
        ])


def configuration(directory=Path("/etc/pools")):
    return {p.name: p.read_text().strip() for p in directory.iterdir() if p.is_file() and not p.name.startswith(".")}


def optional(api, path):
    try:
        return api.request(path)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        error.close()
        return None


def class_references(api, name):
    # Include Pending, Released and terminating objects, not only Bound claims.
    return {
        kind: [x for x in api.items(CORE + "/" + kind) if x["spec"].get("storageClassName") == name]
        for kind in ("persistentvolumeclaims", "persistentvolumes")
    }


def retire_storage_class(api, policy):
    """Retire the bootstrap class only after every PVC and PV has moved away."""
    legacy = policy["retireStorageClass"]
    worker = policy["workerStorageClass"]
    if legacy != "longhorn" or worker != "longhorn-workers":
        raise RuntimeError("Unexpected storage class retirement policy")
    references = class_references(api, legacy)
    if any(references.values()):
        log("storage-class-retirement-blocked", storage_class=legacy,
            claims=len(references["persistentvolumeclaims"]), volumes=len(references["persistentvolumes"]))
        return "waiting-for-storage-class-references"

    classes = {x["metadata"]["name"]: x for x in api.items(STORAGE)}
    for name, tag in ((worker, policy["workerTag"]),
                      (policy["controlPlaneStorageClass"], policy["controlPlaneTag"])):
        obj = classes.get(name, {})
        if obj.get("provisioner") != "driver.longhorn.io" or obj.get("parameters", {}).get("nodeSelector") != tag:
            raise RuntimeError("Storage pool class is missing or has unexpected placement: " + name)
    defaults = {name for name, obj in classes.items()
                if obj["metadata"].get("annotations", {}).get(DEFAULT_CLASS) == "true"}
    if defaults - {legacy, worker}:
        raise RuntimeError("Another storage class is default: " + ",".join(sorted(defaults)))
    old = classes.get(legacy)
    if old and old.get("provisioner") != "driver.longhorn.io":
        raise RuntimeError("Refusing to retire a class with an unexpected provisioner")

    # Fleet owns the otherwise empty HelmChartConfig. This controller owns only
    # values.persistence; do not edit Ansible's HelmChart or its other settings.
    config = api.request(CHART_CONFIG)
    values = config.get("spec", {}).get("values", {})
    persistence = values.get("persistence", {})
    if persistence.get("createStorageClass") is not False or persistence.get("defaultClass") is not False:
        api.patch(CHART_CONFIG, config, [{
            "op": "add", "path": "/spec/values", "value": {
                **values, "persistence": {**persistence, "createStorageClass": False, "defaultClass": False},
            },
        }])
        return "storage-class-source-disable-requested"
    # Longhorn recreates `longhorn` from this ConfigMap. Wait for Helm to
    # remove that source before changing defaults or deleting the class.
    if optional(api, CORE + "/namespaces/longhorn-system/configmaps/longhorn-storageclass") is not None:
        return "waiting-for-storage-class-source-removal"

    target = classes[worker]
    if target["metadata"].get("annotations", {}).get(DEFAULT_CLASS) != "true":
        api.patch(STORAGE + "/" + worker, target, [{
            "op": "add", "path": "/metadata/annotations", "value": {
                **target["metadata"].get("annotations", {}), DEFAULT_CLASS: "true",
            },
        }])
        return "worker-default-selected"
    if old:
        # Recheck immediately before deletion. Never remove PVCs, PVs or data.
        if any(class_references(api, legacy).values()):
            return "waiting-for-storage-class-references"
        api.request(STORAGE + "/" + legacy, "DELETE", {
            "apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {
                "uid": old["metadata"]["uid"], "resourceVersion": old["metadata"]["resourceVersion"],
            },
        })
        log("storage-class-retired", storage_class=legacy, default=worker)
        return "storage-class-retired"
    return "storage-class-retirement-completed"


def control_plane(node):
    return "node-role.kubernetes.io/control-plane" in node["metadata"].get("labels", {})


def ready(node):
    return not node["spec"].get("unschedulable", False) and any(
        c["type"] == "Ready" and c["status"] == "True" for c in node.get("status", {}).get("conditions", [])
    ) and not any(c["status"] == "True" and c["type"] in {"MemoryPressure", "DiskPressure", "PIDPressure"}
                  for c in node.get("status", {}).get("conditions", []))


def claim_pool(claim, policy):
    return "control-plane" if claim["metadata"]["namespace"] in policy["controlPlaneNamespaces"].split(",") else "worker"


def tag_for(pool, policy):
    return policy["controlPlaneTag"] if pool == "control-plane" else policy["workerTag"]


def selectors(existing, desired, policy):
    owned = {policy["controlPlaneTag"], policy["workerTag"]}
    return sorted((set(existing) - owned) | {desired})


def retained(replica):
    return not replica["metadata"].get("deletionTimestamp") and not replica["spec"].get("failedAt") and bool(
        replica["spec"].get("healthyAt")
    ) and replica["spec"].get("active", False)


def run_once(api, policy):
    nodes = api.items(CORE + "/nodes")
    pools = {n["metadata"]["name"]: "control-plane" if control_plane(n) else "worker" for n in nodes}
    longhorn_nodes = api.items(LH + "/nodes")
    for n in nodes:
        name = n["metadata"]["name"]
        labels = n["metadata"].get("labels", {})
        if labels.get(LABEL) != pools[name]:
            api.patch(CORE + "/nodes/" + name, n, [
                {"op": "add", "path": "/metadata/labels", "value": {**labels, LABEL: pools[name]}},
            ])
            log("node-labelled", node=name, pool=pools[name])
    for n in longhorn_nodes:
        name = n["metadata"]["name"]
        if name not in pools:
            raise RuntimeError("Longhorn node has no Kubernetes node: " + name)
        tags = selectors(n["spec"].get("tags", []), tag_for(pools[name], policy), policy)
        if n["spec"].get("tags", []) != tags:
            api.patch(LH + "/nodes/" + name, n, [{"op": "add", "path": "/spec/tags", "value": tags}])
            log("node-tagged", node=name, tags=tags)

    claims = {p["spec"]["volumeName"]: p for p in api.items(CORE + "/persistentvolumeclaims")
              if p["spec"].get("volumeName")}
    volumes = api.items(LH + "/volumes")
    managed = [v for v in volumes if v["metadata"]["name"] in claims]
    policy_changed = False
    for v in managed:
        name = v["metadata"]["name"]
        wanted = claim_pool(claims[name], policy)
        selector = selectors(v["spec"].get("nodeSelector", []), tag_for(wanted, policy), policy)
        if v["spec"].get("nodeSelector", []) != selector:
            api.patch(LH + "/volumes/" + name, v, [{"op": "add", "path": "/spec/nodeSelector", "value": selector}])
            log("volume-selected", volume=name, pool=wanted)
            policy_changed = True
    if policy_changed:
        return "volume-policy-updated"

    if not all(ready(n) for n in nodes):
        return "waiting-for-healthy-nodes"
    replicas = api.items(LH + "/replicas")
    remaining = sum(pools.get(r["spec"]["nodeID"]) != claim_pool(claims[r["spec"]["volumeName"]], policy)
                    for r in replicas if retained(r) and r["spec"]["volumeName"] in claims)
    misplaced_engines = sum(v["spec"]["accessMode"] == "rwx" and v["status"].get("state") == "attached"
                            and pools.get(v["status"].get("currentNodeID")) != claim_pool(claims[v["metadata"]["name"]], policy)
                            for v in managed)
    log("placement-status", misplaced_replicas=remaining, misplaced_share_managers=misplaced_engines, volumes=len(managed))
    if any(v["status"].get("state") != "detached" and
           (v["status"].get("state") != "attached" or v["status"].get("robustness") != "healthy") for v in managed):
        return "waiting-for-healthy-volumes"
    return "converged" if remaining == 0 and misplaced_engines == 0 else "blocked"


def main():
    api = API()
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    while not STOP.is_set():
        interval = 30
        try:
            policy = configuration()
            interval = max(10, int(policy["intervalSeconds"]))
            state = run_once(api, policy)
            if state == "converged" and policy.get("retireStorageClass"):
                state = retire_storage_class(api, policy)
            Path("/tmp/ready").touch()
            log("reconcile-completed", state=state)
        except urllib.error.HTTPError as error:
            log("reconcile-failed", error_type=type(error).__name__, status=error.code,
                error=error.read(4096).decode(errors="replace"))
        except Exception as error:
            log("reconcile-failed", error_type=type(error).__name__, error=str(error))
        STOP.wait(interval)


if __name__ == "__main__":
    main()
