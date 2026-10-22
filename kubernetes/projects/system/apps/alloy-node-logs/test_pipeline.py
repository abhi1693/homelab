#!/usr/bin/env python3
"""Exercise the rendered, pinned Alloy pipeline in local Docker only."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone

import yaml


APP = Path(__file__).resolve().parent
IMAGE = "grafana/alloy:v1.20.1"


def run(*args: str, **kwargs: object) -> str:
    return subprocess.check_output(args, text=True, **kwargs)


def render(enabled: bool) -> str:
    manifests = run(
        "helm", "template", "alloy-node-logs", "alloy",
        "--repo", "https://grafana.github.io/helm-charts", "--version", "1.13.1",
        "--namespace", "cattle-monitoring-system", "-f", str(APP / "values.yaml"),
        "--set", f"nodeLogs.podLogsEnabled={str(enabled).lower()}",
    )
    for resource in yaml.safe_load_all(manifests):
        if resource["kind"] == "ConfigMap" and "config.alloy" in resource.get("data", {}):
            return resource["data"]["config.alloy"]
    raise AssertionError("rendered chart has no Alloy configuration")


def fixture_config(config: str) -> str:
    # Replace API discovery with one realistic metadata target; keep the actual
    # relabel rules, file source/component ID, and all pod processing unchanged.
    config = config[config.index('discovery.relabel "pods"'):]
    config = config.replace(
        "discovery.kubernetes.pods.targets",
        '[{__meta_kubernetes_namespace="devfeed", __meta_kubernetes_pod_name="fixture", '
        '__meta_kubernetes_pod_container_name="api", __meta_kubernetes_pod_node_name="fixture-node", '
        '__meta_kubernetes_pod_uid="fixture-uid", '
        '__meta_kubernetes_pod_label_app_kubernetes_io_name="devfeed", '
        '__meta_kubernetes_pod_label_app_kubernetes_io_part_of="devfeed", '
        '__meta_kubernetes_pod_label_app_kubernetes_io_component="api"}]',
    )
    config = config[:config.index('loki.source.journal "k3s_server"')]
    return (
        'logging { format = "json" }\n'
        + config.replace("loki.write.local.receiver", "loki.echo.capture.receiver")
        + '\nloki.echo "capture" {}\n'
    )


def wait_for(check, label: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.25)
    raise AssertionError(f"timed out waiting for {label}")


def main() -> None:
    configs = {enabled: render(enabled) for enabled in (False, True)}
    containers: list[str] = []
    with tempfile.TemporaryDirectory(prefix="alloy-node-pipeline-") as temp:
        root = Path(temp)
        root.chmod(0o755)
        state = root / "state"
        state.mkdir()
        podlogs = root / "podlogs"
        logfile = podlogs / "devfeed_fixture_fixture-uid/api/0.log"
        logfile.parent.mkdir(parents=True)
        now = datetime.now(timezone.utc).replace(microsecond=0)

        def cri(text: str, *, timestamp=now, flag="F") -> str:
            return f"{timestamp.isoformat().replace('+00:00', 'Z')} stdout {flag} {text}\n"

        def entries(container: str) -> list[dict]:
            result = []
            for line in run("docker", "logs", container, stderr=subprocess.STDOUT).splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("msg") == "received log entry":
                    result.append(entry)
            return result

        def start(config: str) -> str:
            path = root / f"config-{len(containers)}.alloy"
            path.write_text(fixture_config(config))
            container = run(
                "docker", "run", "--detach", "--network", "none", "--read-only",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--user", f"{os.getuid()}:{os.getgid()}",
                "--mount", f"type=bind,src={path},dst=/etc/alloy/config.alloy,readonly",
                "--mount", f"type=bind,src={podlogs},dst=/var/log/pods,readonly",
                "--mount", f"type=bind,src={state},dst=/var/lib/alloy-node-logs",
                IMAGE, "run", "/etc/alloy/config.alloy", "--disable-reporting",
                "--storage.path=/var/lib/alloy-node-logs",
            ).strip()
            containers.append(container)
            return container

        def offset() -> int:
            positions = state / "loki.source.file.pods/positions.yml"
            if not positions.exists():
                return -1
            text = positions.read_text()
            matches = re.findall(r'offset:\s*["\']?(\d+)', text)
            if not matches:
                # Alloy's positions format maps the complete file+labels key to
                # an offset string; tolerate both released YAML encodings.
                matches = re.findall(r':\s*["\'](\d+)["\']', text)
            return max(map(int, matches), default=-1)

        try:
            for enabled, config in configs.items():
                path = root / f"validate-{enabled}.alloy"
                path.write_text(config)
                run(
                    "docker", "run", "--rm", "--network", "none",
                    "--mount", f"type=bind,src={path},dst=/etc/alloy/config.alloy,readonly",
                    IMAGE, "validate", "/etc/alloy/config.alloy",
                )
            logfile.write_text("".join(cri(f"historic-before-priming-{i}") for i in range(20)))
            first = start(configs[False])
            wait_for(lambda: offset() > 0, "initial quiet-file checkpoint")
            # A quick multiline read checkpoints its first line, then can go
            # quiet before the next checkpoint interval. The required rolling
            # replacement must flush the complete offset before forwarding.
            time.sleep(1)
            assert offset() < logfile.stat().st_size, "fixture did not exercise a stale quiet-file checkpoint"
            assert entries(first) == [], "priming must not write pod logs"
            run("docker", "stop", "--time", "10", first)
            assert offset() == logfile.stat().st_size, "graceful shutdown must flush historical offsets"

            # Write while Alloy is stopped: the enabled phase must resume saved
            # offsets, rather than seek past this record or replay older lines.
            with logfile.open("a") as handle:
                handle.write(cri('{"level":"ERROR","service":"web","message":"resumed-after-handover"}'))
            second = start(configs[True])
            wait_for(lambda: len(entries(second)) >= 1, "resumed record")
            with logfile.open("a") as handle:
                handle.write(cri('{"level":"INFO","service":"worker","message":"partial-', flag="P"))
                handle.write(cri('joined"}', flag="F"))
                handle.write(cri("expired-marker", timestamp=now - timedelta(days=15)))
            wait_for(lambda: len(entries(second)) >= 2, "CRI partial-line joining")
            time.sleep(1)
            output = entries(second)
            assert len(output) == 2, output
            assert "resumed-after-handover" in output[0]["entry"], output
            assert "partial-joined" in output[1]["entry"], output
            for entry in output:
                labels = entry["labels"]
                for expected in ('namespace="devfeed"', 'node="fixture-node"', 'job="devfeed/api"', 'cluster="local"'):
                    assert expected in labels, labels
                assert 'filename=' not in labels and 'stream=' not in labels, labels
                assert entry["entry_timestamp"].startswith(now.isoformat().replace("+00:00", "")), entry
            assert 'severity="ERROR"' in output[0]["labels"], output
            assert 'service="web"' in output[0]["labels"], output
            assert 'severity="INFO"' in output[1]["labels"], output
            assert 'service="worker"' in output[1]["labels"], output
            with logfile.open("a") as old_inode:
                logfile.rename(logfile.with_name("0.log.20261019-rotation"))
                old_inode.write(cri("renamed-inode-marker"))
                old_inode.flush()
                logfile.write_text(cri("new-active-file-marker"))
            wait_for(lambda: len(entries(second)) >= 4, "live renamed inode and replacement file")
            output = entries(second)
            assert sum(e["entry"] == "renamed-inode-marker" for e in output) == 1, output
            assert sum(e["entry"] == "new-active-file-marker" for e in output) == 1, output
            print("Passed: both rendered stages validate; quiet multiline priming/graceful checkpoint flush, persisted handover offsets, CRI timestamps/partial lines, live rotation, labels and 14-day filtering.")
        except Exception:
            for container in containers:
                print(run("docker", "logs", container, stderr=subprocess.STDOUT))
            for path in state.rglob("positions.yml"):
                print(path, path.read_text())
            raise
        finally:
            for container in containers:
                subprocess.run(["docker", "rm", "--force", container], capture_output=True, check=False)


if __name__ == "__main__":
    main()
