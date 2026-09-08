#!/usr/bin/env python3
"""Task-specific break-glass RWX reattachment after all HA clients stop."""

import argparse
from pathlib import Path
import runpy


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--recovery-verified", action="store_true", required=True)
parser.parse_args()
helpers = runpy.run_path(str(Path(__file__).with_name("longhorn-reattach-pod.py")))
get, kubectl, wait, healthy = (helpers[key] for key in ("get", "kubectl", "wait", "healthy"))
namespace, deployment = "home-assistant", "home-assistant"
volume_name = "pvc-e6d8a127-ac59-4ce2-861c-f0c54f069d0e"
volume = get("volumes.longhorn.io", volume_name, "longhorn-system")
assert volume["spec"]["accessMode"] == "rwx"
workload = get("deployment", deployment, namespace)
replicas = workload["spec"]["replicas"]
assert replicas == 1 and workload["status"].get("readyReplicas") == 1
assert "objectset.rio.cattle.io/id" not in workload["metadata"].get("annotations", {}), "Review Fleet pause policy first"
clients = [p for p in get("pods", namespace=namespace)["items"]
           if p.get("status", {}).get("phase") not in ("Succeeded", "Failed")
           and any(v.get("persistentVolumeClaim", {}).get("claimName") == "home-assistant-pvc"
                   for v in p["spec"].get("volumes", []))]
assert len(clients) == 1 and clients[0]["metadata"]["name"].startswith("home-assistant-")
wait(healthy, "All Longhorn volumes healthy before RWX shutdown", 60)

try:
    kubectl("-n", namespace, "scale", "deployment/" + deployment, "--replicas=0")
    wait(lambda: get("volumes.longhorn.io", volume_name, "longhorn-system")["status"].get("state") == "detached",
         "Home Assistant RWX volume fully detached", 300)
finally:
    kubectl("-n", namespace, "scale", "deployment/" + deployment, "--replicas=" + str(replicas))
    print("Restored Home Assistant replica count", flush=True)

kubectl("-n", namespace, "rollout", "status", "deployment/" + deployment, "--timeout=600s")


def recovered():
    engines = [e for e in get("engines.longhorn.io", namespace="longhorn-system")["items"]
               if e["spec"]["volumeName"] == volume_name]
    if len(engines) != 1 or not healthy():
        return False
    manager = get("instancemanagers.longhorn.io", engines[0]["status"]["instanceManagerName"], "longhorn-system")
    share = get("sharemanagers.longhorn.io", volume_name, "longhorn-system")
    return manager["spec"]["image"].endswith(":v1.12.1") and share["status"].get("currentImage", "").endswith(":v1.12.1")


wait(recovered, "RWX share and instance manager upgraded; all volumes healthy")
