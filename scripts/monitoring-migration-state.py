#!/usr/bin/env python3
"""Read-only monitoring inventory and preservation checks for the Fleet migration.

Requires kubectl and access to Grafana's read API. Snapshots contain private
dashboard definitions; keep them outside Git. No Secrets or Helm values are read.
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener


NAMESPACE = "cattle-monitoring-system"
ROOT = Path(__file__).resolve().parents[1]
KINDS = (
    "prometheuses", "alertmanagers", "servicemonitors", "podmonitors",
    "prometheusrules", "scrapeconfigs", "probes", "alertmanagerconfigs",
)


def kubectl(*args):
    result = subprocess.run(
        ["kubectl", "--request-timeout=30s", *args],
        capture_output=True, text=True, timeout=40, check=True,
    )
    return json.loads(result.stdout)


def api(service, path, port=9090):
    return kubectl(
        "get", "--raw",
        f"/api/v1/namespaces/{NAMESPACE}/services/http:{service}:{port}/proxy{path}",
    )


def identity(item):
    meta = item["metadata"]
    return f"{meta.get('namespace', '')}/{meta['name']}"


def inventory(items):
    return {identity(item): {
        "uid": item["metadata"]["uid"],
        "keep": item["metadata"].get("annotations", {}).get("helm.sh/resource-policy"),
        "spec": item.get("spec", {}),
    } for item in items}


def snapshot(grafana_url):
    state = {"schema": 1, "captured_at": datetime.now(timezone.utc).isoformat()}
    state["cluster_uid"] = kubectl("get", "namespace", "kube-system", "-o", "json")["metadata"]["uid"]
    state["namespaces"] = inventory(kubectl(
        "get", "namespace", NAMESPACE, "cattle-dashboards", "-o", "json",
    )["items"])
    state["resources"] = {
        kind: inventory(kubectl("get", kind, "-A", "-o", "json")["items"])
        for kind in KINDS
    }
    state["pvcs"] = inventory(kubectl("get", "pvc", "-n", NAMESPACE, "-o", "json")["items"])
    state["services"] = inventory(kubectl(
        "get", "service", "prometheus-write-0", "prometheus-write-1",
        "-n", NAMESPACE, "-o", "json",
    )["items"])
    state["processor_policy"] = kubectl(
        "get", "networkpolicy", "opentelemetry-processor-boundary", "-n", NAMESPACE, "-o", "json",
    )["spec"]
    state["repositories"] = [x["metadata"]["name"] for x in kubectl("get", "clusterrepo", "-o", "json")["items"]]
    state["workloads"] = [{
        "kind": x["kind"], "name": x["metadata"]["name"],
        "desired": x["spec"].get("replicas", 1),
        "ready": x.get("status", {}).get("readyReplicas", 0),
    } for x in kubectl("get", "deployment,statefulset", "-n", NAMESPACE, "-o", "json")["items"]]
    state["dashboard_configmaps"] = [{
        "name": identity(x), "data": x.get("data", {}),
    } for x in kubectl("get", "configmap", "-A", "-l", "grafana_dashboard=1", "-o", "json")["items"]]

    # Deliberately do not read credentials. The current internal Grafana exposes
    # Viewer access. Fail rather than silently omit dashboards if auth changes.
    def grafana(path):
        opener = build_opener(ProxyHandler({}))
        for attempt in range(3):
            try:
                with opener.open(grafana_url.rstrip("/") + path, timeout=30) as response:
                    return json.load(response)
            except (OSError, URLError) as exc:
                if isinstance(exc, HTTPError) and exc.code < 500:
                    raise OSError(f"Grafana GET {path}: HTTP {exc.code}") from exc
                if attempt == 2:
                    raise OSError(f"Grafana GET {path} failed after three attempts") from exc
                time.sleep(attempt + 1)

    found = []
    page = 1
    while True:
        batch = grafana(f"/api/search?type=dash-db&limit=1000&page={page}")
        found.extend(batch)
        if len(batch) < 1000:
            break
        page += 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        exported = list(pool.map(lambda x: grafana("/api/dashboards/uid/" + quote(x["uid"], safe="")), found))
    state["grafana_dashboards"] = {x["dashboard"]["uid"]: x for x in exported}
    state["datasources"] = {x["uid"]: {
        "name": x["name"], "type": x["type"], "url": x.get("url"),
    } for x in grafana("/api/datasources")}
    state["alertmanager_silences"] = api("rancher-monitoring-alertmanager", "/api/v2/silences", 9093)
    state["prometheus"] = {}
    for ordinal in range(2):
        service = f"prometheus-write-{ordinal}"
        targets = api(service, "/api/v1/targets?state=active")["data"]["activeTargets"]
        rules = api(service, "/api/v1/rules")["data"]["groups"]
        state["prometheus"][service] = {
            "targets_by_job": dict(Counter(x["labels"].get("job", "") for x in targets)),
            "unhealthy_targets": [{"labels": x["labels"], "error": x["lastError"]} for x in targets if x["health"] != "up"],
            "rules": sorted({x["name"] for group in rules for x in group["rules"]}),
            "unhealthy_rules": [x["name"] for group in rules for x in group["rules"] if x["health"] != "ok"],
        }
    return state


def check(before, after, require_prepared):
    errors = []
    if before.get("schema") != 1 or after.get("schema") != 1:
        return ["Unsupported snapshot schema"]
    if before["cluster_uid"] != after["cluster_uid"]:
        return ["Snapshots belong to different clusters"]
    for kind in ("namespaces", "pvcs"):
        for name, old in before[kind].items():
            new = after[kind].get(name)
            if not new or old["uid"] != new["uid"]:
                errors.append(f"{kind}: {name} was removed or recreated")
            elif kind == "pvcs" and old["spec"].get("volumeName") != new["spec"].get("volumeName"):
                errors.append(f"PVC binding changed: {name}")
    for kind, old_items in before["resources"].items():
        new_items = after["resources"][kind]
        for name in old_items.keys() - new_items.keys():
            errors.append(f"Missing {kind}: {name}")
        if kind in ("prometheuses", "alertmanagers"):
            for name in old_items.keys() & new_items.keys():
                if old_items[name]["uid"] != new_items[name]["uid"]:
                    errors.append(f"Recreated {kind}: {name}")
    for key in ("grafana_dashboards", "datasources"):
        for uid in before[key].keys() - after[key].keys():
            errors.append(f"Missing {key} UID: {uid}")
    old_configmaps = {x["name"]: x["data"] for x in before["dashboard_configmaps"]}
    new_configmaps = {x["name"]: x["data"] for x in after["dashboard_configmaps"]}
    for name, documents in old_configmaps.items():
        for key in documents:
            if key not in new_configmaps.get(name, {}):
                errors.append(f"Missing provisioned dashboard document: {name}/{key}")
    for uid in before["datasources"].keys() & after["datasources"].keys():
        if before["datasources"][uid]["type"] != after["datasources"][uid]["type"]:
            errors.append(f"Datasource type changed: {uid}")
    for service, old in before["prometheus"].items():
        new = after["prometheus"].get(service)
        if not new:
            errors.append(f"Missing Prometheus replica: {service}")
            continue
        for job, count in old["targets_by_job"].items():
            if new["targets_by_job"].get(job, 0) < count:
                errors.append(f"{service}: fewer targets for {job}")
        for name in set(old["rules"]) - set(new["rules"]):
            errors.append(f"{service}: missing rule {name}")
        if new["unhealthy_targets"] or new["unhealthy_rules"]:
            errors.append(f"{service}: unhealthy targets or rules; inspect snapshot")
    for workload in after["workloads"]:
        if workload["ready"] < workload["desired"]:
            errors.append(f"Workload not ready: {workload['name']}")
    if require_prepared:
        for kind, name in (("prometheuses", "rancher-monitoring-prometheus"), ("alertmanagers", "rancher-monitoring-alertmanager")):
            item = after["resources"][kind].get(f"{NAMESPACE}/{name}", {})
            if item.get("keep") != "keep":
                errors.append(f"Missing Helm keep annotation: {name}")
        for ordinal in range(2):
            name = f"{NAMESPACE}/prometheus-write-{ordinal}"
            ports = after["services"].get(name, {}).get("spec", {}).get("ports", [])
            if not any(x["port"] == 9090 and x["targetPort"] == "http-web" for x in ports):
                errors.append(f"Write Service does not target native HTTP: {name}")
        allowed = any(
            any(peer.get("podSelector", {}).get("matchLabels", {}).get("prometheus") == "rancher-monitoring-prometheus" for peer in rule.get("to", []))
            and any(port.get("port") == 9090 and port.get("protocol", "TCP") == "TCP" for port in rule.get("ports", []))
            for rule in after["processor_policy"].get("egress", [])
        )
        if not allowed:
            errors.append("Processor policy does not allow native Prometheus port 9090")
        if "prometheus-community" not in after["repositories"]:
            errors.append("Missing prometheus-community ClusterRepo")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("snapshot", help="Read cluster and Grafana state; write a private local JSON file")
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--grafana-url", default="http://grafana.home")
    compare = sub.add_parser("compare", help="Check preservation and readiness; no cluster access")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument("--require-prepared", action="store_true")
    args = parser.parse_args()
    if args.command == "snapshot":
        output = args.output.expanduser().resolve()
        if output.is_relative_to(ROOT):
            parser.error("Store private snapshots outside the repository")
        if output.exists():
            parser.error("Refusing to overwrite an existing snapshot")
        state = snapshot(args.grafana_url)
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            json.dump(state, stream, indent=2)
            stream.write("\n")
        print(f"Saved {output}: {len(state['grafana_dashboards'])} Grafana dashboards, {len(state['datasources'])} datasources, both Prometheus replicas")
    else:
        errors = check(json.loads(args.before.read_text()), json.loads(args.after.read_text()), args.require_prepared)
        for error in errors:
            print(f"FAIL: {error}")
        if errors:
            return 1
        print("PASS: inventory preservation and current readiness" + ("; preparation stage reconciled" if args.require_prepared else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"ERROR: snapshot/check incomplete: {exc}", file=sys.stderr)
        sys.exit(1)
