#!/usr/bin/env python3
"""Task-authorized, sequential RWO reattachment; never deletes storage objects."""

import argparse
import json
import subprocess
import time


def kubectl(*args):
    return subprocess.check_output(["kubectl", *args], text=True).strip()


def get(kind, name=None, namespace=None):
    args = (["-n", namespace] if namespace else []) + ["get", kind]
    if name:
        args.append(name)
    return json.loads(kubectl(*args, "-o", "json"))


def wait(check, description, timeout=1200):
    deadline = time.monotonic() + timeout
    next_report = time.monotonic() + 60
    while time.monotonic() < deadline:
        if check():
            print(description + ": passed", flush=True)
            return
        if time.monotonic() >= next_report:
            print(description + ": still waiting; recovery gate remains closed", flush=True)
            next_report = time.monotonic() + 60
        time.sleep(5)
    raise RuntimeError(description + ": timed out; inspect before proceeding")


def healthy():
    volumes = get("volumes.longhorn.io", namespace="longhorn-system")["items"]
    engines = get("engines.longhorn.io", namespace="longhorn-system")["items"]
    return bool(volumes) and len(engines) == len(volumes) and all(
        v["status"].get("state") == "attached"
        and v["status"].get("robustness") == "healthy" for v in volumes
    ) and all(
        e["status"].get("currentState") == "running"
        and len(e["status"].get("replicaModeMap", {})) == 3
        and set(e["status"].get("replicaModeMap", {}).values()) == {"RW"}
        for e in engines
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace")
    parser.add_argument("pod")
    parser.add_argument("--recovery-verified", action="store_true", required=True)
    args = parser.parse_args()
    pod = get("pod", args.pod, args.namespace)
    node_name = pod["spec"]["nodeName"]
    fixed_node = pod["spec"].get("nodeSelector", {}).get("kubernetes.io/hostname") == node_name
    node = get("node", node_name)
    assert not node["spec"].get("unschedulable"), "Node already cordoned; do not take ownership"
    assert not pod["metadata"].get("deletionTimestamp"), "Pod already terminating"
    owners = [o for o in pod["metadata"].get("ownerReferences", []) if o.get("controller")]
    assert len(owners) == 1 and owners[0]["kind"] in ("ReplicaSet", "StatefulSet", "Cluster")
    old_uid, owner_uid = pod["metadata"]["uid"], owners[0]["uid"]
    volumes = []
    for entry in pod["spec"].get("volumes", []):
        if "persistentVolumeClaim" not in entry:
            continue
        pvc = get("pvc", entry["persistentVolumeClaim"]["claimName"], args.namespace)
        pv = get("pv", pvc["spec"]["volumeName"])
        if pv["spec"].get("csi", {}).get("driver") != "driver.longhorn.io":
            continue
        volume = get("volumes.longhorn.io", pv["spec"]["csi"]["volumeHandle"], "longhorn-system")
        assert volume["spec"]["accessMode"] == "rwo", "RWX requires all-client shutdown"
        volumes.append(volume["metadata"]["name"])
    assert volumes, "No Longhorn RWO volumes found"
    # CNPG reacts to a cordoned primary node even when another workload is moved.
    # Require an explicit, verified switchover before affecting that node.
    for database in json.loads(kubectl("get", "clusters.postgresql.cnpg.io", "-A", "-o", "json"))["items"]:
        primary = database.get("status", {}).get("currentPrimary")
        assert primary, "PostgreSQL primary is not established"
        primary_pod = get("pod", primary, database["metadata"]["namespace"])
        assert primary_pod["spec"].get("nodeName") != node_name, "Node hosts a PostgreSQL primary; switch over and verify first"
    if owners[0]["kind"] == "Cluster":
        cluster = get("clusters.postgresql.cnpg.io", owners[0]["name"], args.namespace)
        assert cluster["status"]["currentPrimary"] != args.pod, "Switchover primary first"
        assert cluster["status"]["readyInstances"] == cluster["spec"]["instances"]
    if args.namespace == "valkey":
        replication = kubectl("-n", "valkey", "exec", args.pod, "-c", "valkey", "--", "valkey-cli", "INFO", "replication")
        assert "role:slave" in replication and "master_link_status:up" in replication, "Fail over primary first"
    wait(healthy, "All volumes healthy with three writable replicas", 60)
    kubectl("wait", "nodes", "--all", "--for=condition=Ready", "--timeout=30s")
    print(f"Reattaching {args.namespace}/{args.pod}: {volumes}; temporarily cordon {node_name}", flush=True)
    target = get("settings.longhorn.io", "default-instance-manager-image", "longhorn-system")["value"]
    assert target.endswith(":v1.12.1"), "Review workflow for another Longhorn release"

    def recovered():
        candidates = [p for p in get("pods", namespace=args.namespace)["items"]
                      if p["metadata"]["uid"] != old_uid
                      and not p["metadata"].get("deletionTimestamp")
                      and any(o["uid"] == owner_uid for o in p["metadata"].get("ownerReferences", []))
                      and (owners[0]["kind"] == "ReplicaSet" or p["metadata"]["name"] == args.pod)]
        if not any((fixed_node or p["spec"].get("nodeName") != node_name) and any(
            c["type"] == "Ready" and c["status"] == "True" for c in p.get("status", {}).get("conditions", [])
        ) for p in candidates):
            return False
        engines = [e for e in get("engines.longhorn.io", namespace="longhorn-system")["items"]
                   if e["spec"]["volumeName"] in volumes]
        managers = {m["metadata"]["name"]: m for m in get("instancemanagers.longhorn.io", namespace="longhorn-system")["items"]}
        return len(engines) == len(volumes) and all(
            managers.get(e["status"].get("instanceManagerName"), {}).get("spec", {}).get("image") == target
            for e in engines
        ) and healthy()

    try:
        kubectl("cordon", node_name)
        kubectl("-n", args.namespace, "delete", "pod", args.pod, "--wait=true", "--timeout=180s")
        if fixed_node:
            wait(lambda: all(get("volumes.longhorn.io", v, "longhorn-system")["status"].get("state") == "detached"
                             for v in volumes), "Fixed-node volumes fully detached")
            kubectl("uncordon", node_name)
        wait(recovered, "Replacement Ready and engines on new instance managers")
        if owners[0]["kind"] == "Cluster":
            def postgres_recovered():
                current = get("clusters.postgresql.cnpg.io", owners[0]["name"], args.namespace)
                return current["status"].get("readyInstances") == current["spec"]["instances"] and kubectl(
                    "-n", args.namespace, "exec", current["status"]["currentPrimary"], "-c", "postgres",
                    "--", "psql", "-U", "postgres", "-Atc",
                    "SELECT count(*) FROM pg_stat_replication WHERE state='streaming';"
                ) == str(current["spec"]["instances"] - 1)
            wait(postgres_recovered, "PostgreSQL replicas streaming")
        if args.namespace == "valkey":
            def valkey_recovered():
                states = [kubectl("-n", "valkey", "exec", f"valkey-node-{i}", "-c", "valkey", "--",
                                  "valkey-cli", "INFO", "replication") for i in range(3)]
                return sum("role:master" in s and "connected_slaves:2" in s for s in states) == 1 and sum(
                    "role:slave" in s and "master_link_status:up" in s for s in states) == 2
            wait(valkey_recovered, "Valkey primary and replica links aligned")
    finally:
        kubectl("uncordon", node_name)
        print(f"Restored scheduling on {node_name}", flush=True)


if __name__ == "__main__":
    main()
