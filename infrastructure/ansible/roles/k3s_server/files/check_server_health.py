#!/usr/bin/env python3
"""Read-only, bounded rolling-server barrier. Executed via stdin on a peer.

No third-party Python dependencies. Do not print resource bodies or etcd values.
All subprocesses are argument arrays; only Kubernetes reads and etcd reads run.
"""

import datetime as dt
import json
import subprocess
import sys
import time


class Unhealthy(Exception):
    """A gate failed and can be retried within the recovery deadline."""


def require(condition, message):
    if not condition:
        raise Unhealthy(message)


def condition(obj, kind):
    return next((c.get("status") for c in obj.get("status", {}).get("conditions", [])
                 if c.get("type") == kind), None)


def recent_lease(lease, max_age=40):
    renewed = lease.get("spec", {}).get("renewTime", "")
    require(bool(renewed), "Lease has no renewal timestamp")
    age = (dt.datetime.now(dt.timezone.utc) -
           dt.datetime.fromisoformat(renewed.replace("Z", "+00:00"))).total_seconds()
    require(-5 <= age <= max_age, f"Lease is stale or clock skewed (age {age:.1f}s)")
    return renewed


def membership_signature(members):
    return sorted([str(m["ID"]), m["name"], sorted(m["peerURLs"])] for m in members)


def validate_etcd(statuses, memberships, nodes, servers, max_lag, baseline):
    """Compare independently queried endpoints, not one load-balanced response."""
    require(len(statuses) == len(nodes) == len(memberships) == 3,
            "Expected all three etcd endpoints")
    reference = memberships[0]["members"]
    signature = membership_signature(reference)
    require(len(reference) == 3 and len({m["ID"] for m in reference}) == 3,
            "Expected exactly three distinct etcd members")
    if baseline:
        require(signature == baseline, "etcd membership changed since preflight")
    for node, ip in zip(nodes, servers):
        matches = [m for m in reference if m.get("peerURLs") == [f"https://{ip}:2380"]]
        require(len(matches) == 1, f"Missing/duplicate etcd peer for {node}")
        member = matches[0]
        # K3s appends a persistent random suffix to the node name.
        require(member["name"] == node or member["name"].startswith(node + "-"),
                f"Unexpected etcd member name for {node}")
        require(not member.get("isLearner", False), f"{node} is still an etcd learner")
        require(f"https://{ip}:2379" in member.get("clientURLs", []),
                f"Unexpected etcd client address for {node}")
    cluster_ids = {s["header"]["cluster_id"] for s in statuses}
    terms = {s["raftTerm"] for s in statuses}
    leaders = {s["leader"] for s in statuses}
    require(len(cluster_ids) == 1 and 0 not in cluster_ids, "etcd cluster IDs disagree")
    require(len(terms) == 1 and 0 not in terms, "etcd Raft terms disagree")
    require(len(leaders) == 1 and 0 not in leaders, "etcd leader IDs disagree or are empty")
    ids = {s["header"]["member_id"] for s in statuses}
    require(ids == {m["ID"] for m in reference}, "Endpoint IDs differ from membership")
    leader = next(iter(leaders))
    require(sum(s["header"]["member_id"] == leader for s in statuses) == 1,
            "Expected exactly one responding etcd leader")
    for status, membership, ip in zip(statuses, memberships, servers):
        require(membership_signature(membership["members"]) == signature,
                f"Membership differs at {ip}")
        require(membership["header"]["cluster_id"] in cluster_ids,
                f"Member-list cluster ID differs at {ip}")
        member = next(m for m in reference if m["ID"] == status["header"]["member_id"])
        require(member["peerURLs"] == [f"https://{ip}:2380"], f"Wrong member answered at {ip}")
        require(not status.get("errors") and not status.get("isLearner", False),
                f"etcd endpoint reports errors or learner state at {ip}")
        require(0 <= status["raftIndex"] - status["raftAppliedIndex"] <= max_lag,
                f"etcd apply lag exceeds {max_lag} at {ip}")
    lag = max(s["raftIndex"] for s in statuses) - min(s["raftAppliedIndex"] for s in statuses)
    require(lag <= max_lag, f"etcd cross-member index lag {lag} exceeds {max_lag}")
    return signature, (str(next(iter(cluster_ids))), str(leader), next(iter(terms)))


def validate_controller(obj):
    name = obj["metadata"]["namespace"] + "/" + obj["metadata"]["name"]
    status = obj.get("status", {})
    require(not obj["metadata"].get("deletionTimestamp"), f"{name} is terminating")
    require(status.get("observedGeneration", 0) >= obj["metadata"]["generation"],
            f"{name} has not observed its desired generation")
    if obj["kind"] == "Deployment":
        desired = obj["spec"].get("replicas", 1)
        keys = ("readyReplicas", "availableReplicas", "updatedReplicas")
    else:
        desired = status.get("desiredNumberScheduled", 0)
        keys = ("numberReady", "numberAvailable", "updatedNumberScheduled")
    require(desired > 0 and all(status.get(k, 0) == desired for k in keys),
            f"{name} has not recovered desired replicas ({desired})")


def validate_gitrepo(repo):
    name = repo["metadata"]["name"]
    status = repo.get("status", {})
    desired = status.get("desiredReadyClusters", 0)
    require(desired > 0 and status.get("readyClusters", 0) == desired,
            f"Fleet {name} has unready clusters")
    require(condition(repo, "Ready") == "True" and condition(repo, "Stalled") != "True",
            f"Fleet {name} is not Ready or is Stalled")
    require(status.get("observedGeneration", 0) >= repo["metadata"]["generation"],
            f"Fleet {name} has not observed desired generation")
    counts = status.get("resourceCounts", {})
    require(counts.get("desiredReady", 0) > 0 and
            counts.get("ready", 0) == counts["desiredReady"] and
            not any(counts.get(k, 0) for k in ("missing", "modified", "notReady", "unknown", "waitApplied")),
            f"Fleet {name} has unreconciled resources")
    bundles = status.get("display", {}).get("readyBundleDeployments", "").split("/")
    require(len(bundles) == 2 and bundles[0].isdigit() and int(bundles[0]) > 0 and
            bundles[0] == bundles[1], f"Fleet {name} has unready bundle deployments")


class Checker:
    def __init__(self, config):
        self.c = config
        self.deadline = time.monotonic() + config["timeout"]
        self.initial_lease = None
        self.identities = config.get("baseline_members", [])
        self.last_summary = {}

    def run(self, args, as_json=True):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "Recovery deadline exceeded")
        try:
            result = subprocess.run(args, capture_output=True, text=True,
                                    timeout=min(15, remaining), check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Unhealthy(f"{args[0]} failed: {exc}") from exc
        # Never dump payloads, key values, environment, or credential file contents.
        require(result.returncode == 0,
                f"Command failed ({result.returncode}): {' '.join(args[:5])}; "
                f"{result.stderr[-400:].strip()}")
        return json.loads(result.stdout) if as_json else result.stdout.strip()

    def kube(self, *args, server=None, as_json=True):
        cmd = ["/usr/local/bin/k3s", "kubectl", "--kubeconfig=/etc/rancher/k3s/k3s.yaml",
               "--request-timeout=10s", f"--server=https://{server or '127.0.0.1'}:6443"]
        return self.run(cmd + list(args) + (["-o", "json"] if as_json else []), as_json)

    def etcd(self, ip, *args):
        tls = "/var/lib/rancher/k3s/server/tls/etcd/"
        return self.run([self.c["etcdctl"], f"--endpoints=https://{ip}:2379",
                         "--dial-timeout=3s", "--command-timeout=10s", "--write-out=json",
                         f"--cacert={tls}server-ca.crt", f"--cert={tls}client.crt",
                         f"--key={tls}client.key", *args])

    def sample(self):
        c = self.c
        # Every server's API, and the VIP, must pass authenticated readiness checks.
        for ip in c["servers"] + [c["vip"]]:
            result = self.kube("get", "--raw=/readyz?verbose", server=ip, as_json=False)
            require("readyz check passed" in result, f"API readiness failed at {ip}")
        nodes = self.kube("get", "nodes")["items"]
        by_name = {n["metadata"]["name"]: n for n in nodes}
        require(set(c["nodes"]) <= by_name.keys(), "Expected server Node is missing")
        for node in nodes:
            name = node["metadata"]["name"]
            require(condition(node, "Ready") == "True", f"Node {name} is not Ready")
            require(not node["spec"].get("unschedulable", False), f"Node {name} is cordoned")
            require(not any(condition(node, k) == "True" for k in
                            ("MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable")),
                    f"Node {name} reports pressure or network failure")
        if c["phase"] != "preflight":
            require(by_name[c["target"]]["status"]["nodeInfo"]["kubeletVersion"] == c["version"],
                    "Target kubelet version has not converged")
        for name in c["nodes"]:
            lease = self.kube("get", "lease", name, "-n", "kube-node-lease")
            renewed = recent_lease(lease)
            if name == c["target"] and c["phase"] == "recovery":
                if self.initial_lease is None:
                    self.initial_lease = renewed
                require(renewed > self.initial_lease, "Waiting for target lease renewal after handlers")

        statuses, memberships = [], []
        for ip in c["servers"]:
            status = self.etcd(ip, "endpoint", "status")
            require(len(status) == 1, f"Missing endpoint status for {ip}")
            statuses.append(status[0]["Status"])
            memberships.append(self.etcd(ip, "member", "list"))
            alarms = self.etcd(ip, "alarm", "list")
            require(not alarms.get("alarms"), f"etcd has active alarms at {ip}")
            # Empty/nonexistent key is fine; successful linearizable reads prove
            # consensus without creating a key. Only the header is inspected.
            read = self.etcd(ip, "get", "/__k3s_rollout_readiness__", "--consistency=l", "--keys-only")
            require(read["header"]["cluster_id"] == statuses[-1]["header"]["cluster_id"],
                    f"Linearizable read cluster ID mismatch at {ip}")
        members, consensus = validate_etcd(statuses, memberships, c["nodes"], c["servers"],
                                           c["max_index_lag"], self.identities)
        self.identities = members
        vip_lease = self.kube("get", "lease", "plndr-cp-lock", "-n", "kube-system")
        recent_lease(vip_lease, vip_lease["spec"]["leaseDurationSeconds"])
        require(vip_lease["spec"].get("holderIdentity") in c["nodes"],
                "kube-vip lease holder is not an expected Ready server")

        for kind, configured in (("deployment", c["deployments"]), ("daemonset", c["daemonsets"])):
            for item in configured:
                namespace, name = item.split("/", 1)
                validate_controller(self.kube("get", kind, name, "-n", namespace))

        # Explicit node-local DaemonSet coverage prevents an empty selector from passing.
        pods = self.kube("get", "pods", "-A")["items"]
        target_pods = [p for p in pods if p.get("spec", {}).get("nodeName") == c["target"]]
        for item in c["daemonsets"]:
            namespace, name = item.split("/", 1)
            matches = [p for p in target_pods if p["metadata"]["namespace"] == namespace and
                       any(o["kind"] == "DaemonSet" and o["name"] == name
                           for o in p["metadata"].get("ownerReferences", []))]
            require(any(condition(p, "Ready") == "True" and
                        not p["metadata"].get("deletionTimestamp") for p in matches),
                    f"Missing Ready {item} pod on {c['target']}")
        # Watch critical pods for restart/UID changes between successful samples.
        namespaces = {item.split("/")[0] for item in c["deployments"] + c["daemonsets"]}
        restarts = sorted((p["metadata"]["uid"], s["name"], s.get("restartCount", 0))
                          for p in pods if p["metadata"]["namespace"] in namespaces
                          and p["status"].get("phase") not in ("Succeeded", "Failed")
                          for s in p["status"].get("containerStatuses", []))
        volumes = self.kube("get", "volumes.longhorn.io", "-n", "longhorn-system")["items"]
        require(bool(volumes), "No Longhorn volumes found")
        for volume in volumes:
            require(volume.get("status", {}).get("robustness") == "healthy",
                    f"Longhorn volume {volume['metadata']['name']} is not healthy")
        clusters = self.kube("get", "clusters.postgresql.cnpg.io", "-n", "postgresql")["items"]
        require(bool(clusters), "No PostgreSQL clusters found")
        for cluster in clusters:
            status = cluster.get("status", {})
            require(cluster["spec"]["instances"] >= 3 and
                    status.get("readyInstances", 0) == cluster["spec"]["instances"] and
                    status.get("phase") == "Cluster in healthy state",
                    f"PostgreSQL {cluster['metadata']['name']} has not recovered")
        repos = self.kube("get", "gitrepos.fleet.cattle.io", "-n", "fleet-local")["items"]
        require(set(c["gitrepos"]) <= {r["metadata"]["name"] for r in repos},
                "Expected Fleet GitRepo is missing")
        for repo in repos:
            if repo["metadata"]["name"].startswith("home-lab-"):
                validate_gitrepo(repo)
        self.last_summary = {"target": c["target"], "phase": c["phase"], "members": members,
                             "cluster_id": consensus[0], "leader_id": consensus[1],
                             "raft_term": consensus[2], "nodes_ready": len(nodes),
                             "critical_deployments": len(c["deployments"]),
                             "critical_daemonsets": len(c["daemonsets"]), "gitrepos": len(repos)}
        return consensus, restarts

    def wait(self):
        version = self.run([self.c["etcdctl"], "version"], as_json=False)
        require(f"etcdctl version: {self.c['etcdctl_version']}" in version.splitlines(),
                "Pinned etcdctl missing/mismatched; run playbooks/k3s_server_tools.yml before maintenance")
        stable, previous, last_error = 0, None, "No successful sample"
        while time.monotonic() < self.deadline:
            try:
                current = self.sample()
                stable = stable + 1 if current == previous else 1
                previous = current
                last_error = f"Waiting for stability ({stable}/{self.c['samples']} samples)"
                if stable >= self.c["samples"]:
                    return dict(self.last_summary, stable_samples=stable)
            except (Unhealthy, KeyError, ValueError, TypeError) as exc:
                stable, previous = 0, None
                last_error = str(exc)
            print(last_error, file=sys.stderr, flush=True)
            time.sleep(max(0, min(self.c["interval"], self.deadline - time.monotonic())))
        raise Unhealthy(f"Recovery timed out: {last_error}")


def main():
    try:
        config = json.loads(sys.argv[1])
        require(config["phase"] in ("preflight", "recovery", "validation"), "Invalid health phase")
        require(config["samples"] >= 2 and config["interval"] >= 15 and config["timeout"] >= 60,
                "Health gate requires bounded, consecutive stability samples")
        result = Checker(config).wait()
        print(json.dumps(result))
        return 0
    except (Unhealthy, KeyError, ValueError, TypeError, IndexError) as exc:
        print(json.dumps({"error": str(exc), "action": "Stop; keep remaining servers untouched."}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
