"""Keep local Fleet agent resources explicit without adopting either Cluster."""
import json
import os
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.request

RESOURCES = {"requests": {"cpu": "150m", "memory": "448Mi"},
             "limits": {"cpu": "1", "memory": "1Gi"}}
PREFIX = "/apis/{group}/v1{alpha}/namespaces/fleet-local/clusters/local"


def operations(obj, provisioning):
    spec = obj["spec"]
    if provisioning:
        current = spec.get("fleetAgentDeploymentCustomization") or {}
        if current.get("overrideResourceRequirements") == RESOURCES:
            return []
        path = "/spec/fleetAgentDeploymentCustomization"
        value = {**current, "overrideResourceRequirements": RESOURCES}
    else:
        if spec.get("agentResources") == RESOURCES:
            return []
        path, value = "/spec/agentResources", RESOURCES
    return [
        {"op": "test", "path": "/metadata/uid", "value": obj["metadata"]["uid"]},
        {"op": "test", "path": "/metadata/resourceVersion", "value": obj["metadata"]["resourceVersion"]},
        {"op": "add", "path": path, "value": value},
    ]


def apply(request, provisioning):
    path = PREFIX.format(group="provisioning.cattle.io" if provisioning else "fleet.cattle.io",
                         alpha="" if provisioning else "alpha1")
    for attempt in range(5):
        obj = request(path)
        patch = operations(obj, provisioning)
        if not patch:
            return False
        try:
            request(path, patch)
            return True
        except urllib.error.HTTPError as error:
            if error.code not in (409, 422) or attempt == 4:
                raise
            time.sleep(1)
    raise RuntimeError("resource policy did not converge")


def main():
    root = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    token = (root / "token").read_text().strip()
    context = ssl.create_default_context(cafile=str(root / "ca.crt"))
    base = "https://" + os.environ["KUBERNETES_SERVICE_HOST"] + ":" + os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")

    def request(path, patch=None):
        headers = {"Authorization": "Bearer " + token}
        if patch is not None:
            headers["Content-Type"] = "application/json-patch+json"
        req = urllib.request.Request(base + path, json.dumps(patch).encode() if patch else None,
                                     headers, method="PATCH" if patch else "GET")
        with urllib.request.urlopen(req, context=context, timeout=20) as response:
            return json.load(response)

    for provisioning in (True, False):
        changed = apply(request, provisioning)
        print(json.dumps({"cluster": "local", "provisioning": provisioning, "changed": changed}), flush=True)


if __name__ == "__main__":
    main()
