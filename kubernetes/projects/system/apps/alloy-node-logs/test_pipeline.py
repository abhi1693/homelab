#!/usr/bin/env python3
"""Exercise the rendered, pinned Alloy pipeline in local Docker only."""

from __future__ import annotations

import json
import os
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yaml


APP = Path(__file__).resolve().parent
IMAGE = "grafana/alloy:v1.20.1"
LOKI_IMAGE = "grafana/loki:3.6.17"
JOURNAL_FIXTURE_IMAGE = "home-lab/alloy-native-journal-fixture:ubuntu-26.04"


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
        + config.replace("loki.write.local.receiver", "loki.echo.capture.receiver").replace(
            "otelcol.receiver.loki.node.receiver", "loki.echo.capture.receiver",
        )
        + '\nloki.echo "capture" {}\n'
    )


def wait_for(check, label: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.25)
    raise AssertionError(f"timed out waiting for {label}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def exercise_native_journal(rendered: str) -> None:
    """Exercise actual sd-journal seeks/filters/cursors, using synthetic binary data."""
    containers: list[str] = []
    with tempfile.TemporaryDirectory(prefix="alloy-native-journal-") as temporary:
        root = Path(temporary)
        root.chmod(0o755)
        journal, state, build = (root / name for name in ("journal", "state", "image"))
        for directory in (journal, state, build):
            directory.mkdir()
        # The generator is an ephemeral container; apt never installs anything on
        # the host. Disable compression/sealing for an interoperable fixture.
        (build / "Dockerfile").write_text(
            "FROM ubuntu:26.04@sha256:c098726dd9b9733f3e885f8de0ef375206a311b0a317eadc40d347b1115fb944\n"
            "RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends systemd-journal-remote "
            "&& rm -rf /var/lib/apt/lists/*\n"
            'ENTRYPOINT ["/usr/lib/systemd/systemd-journal-remote"]\n'
        )
        run("docker", "build", "--quiet", "--tag", JOURNAL_FIXTURE_IMAGE, str(build))
        boot = "1234567890abcdef1234567890abcdef"
        now = int(time.time() * 1_000_000)
        epoch = 86_400 * 1_000_000

        def import_records(records: list[tuple[str, int, str, str, str]], index: int) -> None:
            exported = root / f"native-{index}.export"
            lines = []
            for offset, (message, realtime, unit, transport, identifier) in enumerate(records, index * 100):
                fields = {
                    "__REALTIME_TIMESTAMP": str(realtime), "__MONOTONIC_TIMESTAMP": str(offset + 1),
                    "_BOOT_ID": boot, "_MACHINE_ID": "abcdef1234567890abcdef1234567890",
                    "_HOSTNAME": "native-fixture-node", "_SYSTEMD_UNIT": unit,
                    "_TRANSPORT": transport, "SYSLOG_IDENTIFIER": identifier, "PRIORITY": "6", "MESSAGE": message,
                }
                lines.append("\n".join(f"{key}={value}" for key, value in fields.items()) + "\n\n")
            exported.write_text("".join(lines))
            run(
                "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
                "--mount", f"type=bind,src={exported},dst=/fixture.export,readonly",
                "--mount", f"type=bind,src={journal},dst=/journal",
                JOURNAL_FIXTURE_IMAGE, "--compress=no", "--seal=no", "--split-mode=none",
                "--output=/journal/system.journal", "/fixture.export",
            )

        original = [
            ("native-epoch-canary", epoch, "session-123.scope", "syslog", "home-lab-log-canary"),
            ("native-epoch-k3s", epoch + 1, "k3s.service", "stdout", "k3s"),
            ("native-epoch-kernel", epoch + 2, "kernel", "kernel", "kernel"),
            ("native-current-canary", now, "session-456.scope", "syslog", "home-lab-log-canary"),
            ("native-current-k3s-agent", now + 1, "k3s-agent.service", "stdout", "k3s-agent"),
        ]
        import_records(original, 0)
        assert (journal / "system.journal").read_bytes().startswith(b"LPKSHHRH"), "generator did not create a native journal"
        # Retain the four rendered journal readers and their ownership relabels;
        # change only the directory and final output sink. This intentionally
        # preserves max_age, including its pinned native seek implementation.
        blocks = re.findall(r'(?ms)^([a-z_][a-z0-9_.]* "[^\"]+" \{\n.*?^\}\n)', rendered)
        kept = [block for block in blocks if block.startswith((
            'loki.source.journal "', 'loki.relabel "system_journal"', 'loki.process "journal"', 'loki.process "os_journal"',
        ))]
        assert sum(block.startswith('loki.source.journal "') for block in kept) == 4, "all four actual journal readers must be tested"
        config = 'logging { format = "json" }\n' + "\n".join(kept)
        config = re.sub(r'(?m)^(\s*path\s*=\s*)""', r'\1"/fixtures/journal"', config)
        config = config.replace("otelcol.receiver.loki.node.receiver", "loki.echo.capture.receiver")
        config = config.replace("otelcol.receiver.loki.os.receiver", "loki.echo.capture.receiver")
        config += '\nloki.echo "capture" {}\n'
        config_path = root / "native.alloy"
        config_path.write_text(config)

        def entries(container: str) -> list[dict]:
            result = []
            for line in run("docker", "logs", container, stderr=subprocess.STDOUT).splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if value.get("msg") == "received log entry":
                    value["record"] = json.loads(value["entry"])
                    result.append(value)
            return result

        def start() -> str:
            container = run(
                "docker", "run", "--detach", "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
                "--env", "NODE_NAME=native-fixture-node",
                "--mount", f"type=bind,src={config_path},dst=/etc/alloy/config.alloy,readonly",
                "--mount", f"type=bind,src={journal},dst=/fixtures/journal,readonly",
                "--mount", f"type=bind,src={state},dst=/var/lib/alloy-node-logs",
                IMAGE, "run", "/etc/alloy/config.alloy", "--disable-reporting", "--storage.path=/var/lib/alloy-node-logs",
            ).strip()
            containers.append(container)
            return container

        try:
            first = start()
            wait_for(lambda: len(entries(first)) >= len(original), "native epoch/current journal collection", 30)
            received = entries(first)
            counts = Counter(entry["record"]["MESSAGE"] for entry in received)
            assert counts == Counter(message for message, *_ in original), counts
            for entry in received:
                message = entry["record"]["MESSAGE"]
                assert entry["record"]["_BOOT_ID"] == boot, entry
                assert 'source="journal"' in entry["labels"] and 'node="native-fixture-node"' in entry["labels"], entry
                if "canary" in message:
                    assert 'unit="home-lab-log-canary"' in entry["labels"], entry
                elif message == "native-epoch-kernel":
                    assert 'unit="kernel"' in entry["labels"], entry
                elif message == "native-epoch-k3s":
                    assert 'unit="k3s.service"' in entry["labels"], entry
                elif message == "native-current-k3s-agent":
                    assert 'unit="k3s-agent.service"' in entry["labels"], entry
                if "epoch" in message:
                    assert entry["entry_timestamp"].startswith("1970-01-02"), entry
            run("docker", "stop", "--time", "10", first)
            assert any(state.rglob("positions.yml")), "journal cursor files were not persisted"
            second = start()
            # Resume exact native cursors even when the saved entry is from a
            # bad clock. Then observe a real appended binary journal entry.
            time.sleep(2)
            assert entries(second) == [], "native cursor restart replayed already consumed records"
            import_records([("native-after-restart", int(time.time() * 1_000_000), "session-789.scope", "syslog", "home-lab-log-canary")], 1)
            wait_for(lambda: len(entries(second)) >= 1, "native journal append after cursor restart", 30)
            resumed = entries(second)
            assert len(resumed) == 1 and resumed[0]["record"]["MESSAGE"] == "native-after-restart", resumed
            print("Passed: genuine binary journal with epoch/current canaries, K3s/kernel ownership exactly once, native timestamps and boot ID; persisted native cursor restart and appended record. No host journal was used.")
        except Exception:
            for container in containers:
                print(run("docker", "logs", "--tail", "100", container, stderr=subprocess.STDOUT))
            raise
        finally:
            for container in containers:
                subprocess.run(["docker", "rm", "--force", container], capture_output=True, check=False)


def otlp_fixture_config(config: str, endpoint: str) -> str:
    """Substitute inputs/transport only; exercise the rendered processing graph."""
    config = re.sub(r'(?ms)^discovery\.kubernetes "pods" \{\n.*?^\}\n', "", config)
    targets = []
    for suffix in ("a", "b"):
        targets.append({
            "__meta_kubernetes_namespace": "devfeed",
            "__meta_kubernetes_pod_name": f"fixture-{suffix}",
            "__meta_kubernetes_pod_container_name": "api",
            "__meta_kubernetes_pod_node_name": f"fixture-node-{suffix}",
            "__meta_kubernetes_pod_uid": f"fixture-uid-{suffix}",
            "__meta_kubernetes_pod_label_app_kubernetes_io_name": "devfeed",
            "__meta_kubernetes_pod_label_app_kubernetes_io_part_of": "devfeed",
            "__meta_kubernetes_pod_label_app_kubernetes_io_component": "api",
        })
    # Alloy object keys aren't JSON string literals; values are JSON strings.
    target_text = "[" + ",".join(
        "{" + ",".join(f"{key}={json.dumps(value)}" for key, value in target.items()) + "}"
        for target in targets
    ) + "]"
    config = config.replace("discovery.kubernetes.pods.targets", target_text)
    config = re.sub(r'(?ms)^loki\.source\.journal "[^\"]+" \{\n.*?^\}\n', "", config)
    config = config.replace(
        "http://loki-gateway.cattle-monitoring-system.svc.cluster.local/otlp", endpoint,
    )
    # The CRI fixture supplies the same producer timestamp a real journal reader
    # supplies on its Entry. The journal process and OTel transforms stay intact.
    config += '''
loki.source.file "journal_fixture" {
  targets = [{__path__="/fixtures/journal.log", cluster="local", node="fixture-host", source="journal", unit="systemd-timesyncd.service", job="node/system"}]
  forward_to = [loki.process.journal_fixture_cri.receiver]
  file_match { enabled = true }
}
loki.process "journal_fixture_cri" {
  stage.cri {}
  forward_to = [loki.process.os_journal.receiver]
}
'''
    return config


def exercise_otlp_pipeline(rendered: str) -> None:
    """Real protobuf OTLP, temporary Loki, and a loopback 503 fault boundary."""
    containers: list[str] = []
    statuses: list[int] = []
    requests: list[tuple[str, str]] = []
    alloy_ports: dict[str, int] = {}
    forced_status: list[int | None] = [None]
    backend_available = threading.Event()
    backend_available.set()
    priority_available = threading.Event()
    loki_port = free_port()

    class Proxy(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            payload = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            priority = self.path.startswith("/priority-otlp/")
            path = self.path.replace("/priority-otlp/", "/otlp/", 1)
            requests.append((path, self.headers.get("Content-Type", "")))
            status, body = 503, b"fixture backend unavailable"
            if forced_status[0] is not None:
                status, body = forced_status[0], b"fixture deliberately rejected this request"
            elif backend_available.is_set() or (priority and priority_available.is_set()):
                headers = {key: self.headers[key] for key in ("Content-Type", "Content-Encoding") if key in self.headers}
                request = Request(f"http://127.0.0.1:{loki_port}{path}", payload, headers)
                try:
                    with urlopen(request, timeout=10) as response:
                        status, body = response.status, response.read()
                except HTTPError as error:
                    status, body = error.code, error.read()
                    print(f"Fixture Loki rejected OTLP: {status} {body.decode(errors='replace')}")
            statuses.append(status)
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_args: object) -> None:
            pass

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    with tempfile.TemporaryDirectory(prefix="alloy-otlp-pipeline-") as temporary:
        root = Path(temporary)
        root.chmod(0o755)
        state, podlogs, fixtures, lokidata, auditlogs, oslogs = (root / name for name in ("state", "podlogs", "fixtures", "lokidata", "auditlogs", "oslogs"))
        for directory in (state, podlogs, fixtures, lokidata, auditlogs, oslogs):
            directory.mkdir()
        (state / "otel/payloads").mkdir(parents=True)
        (state / "otel/offsets").mkdir(parents=True)
        paths = {}
        for suffix in ("a", "b"):
            path = podlogs / f"devfeed_fixture-{suffix}_fixture-uid-{suffix}/api/0.log"
            path.parent.mkdir(parents=True)
            path.touch()
            paths[suffix] = path
        journal = fixtures / "journal.log"
        journal.touch()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        bodies: dict[str, str] = {}

        def write_record(path: Path, marker: str, *, timestamp: datetime = now, journal_record: bool = False) -> None:
            value = {"level": "ERROR", "service": "fixture-api", "message": marker}
            if journal_record:
                value = {
                    "MESSAGE": marker, "_BOOT_ID": "fixture-boot-id", "_SYSTEMD_UNIT": "systemd-timesyncd.service",
                    "_TRANSPORT": "journal", "PRIORITY": "4", "__MONOTONIC_TIMESTAMP": "123456789",
                    "_SOURCE_REALTIME_TIMESTAMP": str(int(timestamp.timestamp() * 1_000_000)),
                }
            body = json.dumps(value, separators=(",", ":"))
            bodies[marker] = body
            with path.open("a") as handle:
                handle.write(f"{timestamp.isoformat().replace('+00:00', 'Z')} stdout F {body}\n")

        loki_values = yaml.safe_load((APP.parent / "loki/values.yaml").read_text())["loki"]
        # Keep production schema, index mapping and ingest/replay limits. Only
        # transport/storage/ring addresses are changed for the disposable node.
        loki_config = {
            "auth_enabled": False,
            "server": {"http_listen_address": "127.0.0.1", "http_listen_port": loki_port, "grpc_listen_port": free_port(), "log_level": "warn"},
            "common": {
                "instance_addr": "127.0.0.1", "path_prefix": "/var/loki", "replication_factor": 1,
                "ring": {"kvstore": {"store": "inmemory"}},
                "storage": {"filesystem": {"chunks_directory": "/var/loki/chunks", "rules_directory": "/var/loki/rules"}},
            },
            "schema_config": loki_values["schemaConfig"],
            "limits_config": loki_values["limits_config"],
            "querier": loki_values.get("querier", {}),
            "ingester": {**loki_values.get("ingester", {}), "wal": {"enabled": True, "dir": "/var/loki/wal"}},
            "compactor": {"working_directory": "/var/loki/compactor", "retention_enabled": False},
        }
        loki_path = root / "loki.yaml"
        loki_path.write_text(yaml.safe_dump(loki_config))
        assert loki_config["querier"].get("query_ingesters_within") == "336h", "fixture must use the production replay query window"
        assert loki_config["ingester"].get("query_store_max_look_back_period") == "336h", "filesystem ingester lookback must permit old replay before chunk flush"
        assert loki_config["limits_config"].get("shard_streams", {}).get("time_sharding_enabled"), "fixture must use production time sharding"
        config_path = root / "config.alloy"
        config = otlp_fixture_config(rendered, f"http://127.0.0.1:{proxy.server_port}/otlp")
        # Separate loopback fault boundaries let the OS backend remain healthy
        # while a saturated bulk queue is retrying. Production uses one gateway.
        config, changes = re.subn(
            r'(otelcol.exporter.otlphttp "os" \{\s*client \{\s*endpoint\s*=\s*)"[^"]+"',
            lambda match: match[1] + json.dumps(f"http://127.0.0.1:{proxy.server_port}/priority-otlp"),
            config, count=1,
        )
        assert changes == 1
        config_path.write_text(config)

        def start_alloy() -> str:
            alloy_port = free_port()
            values = yaml.safe_load((APP / "values.yaml").read_text())["alloy"]
            cpu_limit = values["resources"]["limits"]["cpu"]
            cpus = str(float(cpu_limit[:-1]) / 1000) if cpu_limit.endswith("m") else cpu_limit
            runtime_env = [arg for env in values["extraEnv"] if env["name"] in ("GOMAXPROCS", "GOMEMLIMIT")
                           for arg in ("--env", f"{env['name']}={env['value']}")]
            memory = values["resources"]["limits"]["memory"].replace("Mi", "m").replace("Gi", "g")
            container = run(
                "docker", "run", "--detach", "--network", "host", "--read-only",
                "--cpus", cpus, "--memory", memory, "--memory-swap", memory, *runtime_env,
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
                "--env", "NODE_NAME=fixture-host",
                "--mount", f"type=bind,src={config_path},dst=/etc/alloy/config.alloy,readonly",
                "--mount", f"type=bind,src={podlogs},dst=/var/log/pods,readonly",
                "--mount", f"type=bind,src={fixtures},dst=/fixtures,readonly",
                "--mount", f"type=bind,src={auditlogs},dst=/var/log/kubernetes-audit,readonly",
                "--mount", f"type=bind,src={oslogs},dst=/host/var/log,readonly",
                "--mount", f"type=bind,src={state},dst=/var/lib/alloy-node-logs",
                IMAGE, "run", "/etc/alloy/config.alloy", "--disable-reporting", "--stability.level=public-preview",
                "--server.http.listen-addr=127.0.0.1:" + str(alloy_port), "--storage.path=/var/lib/alloy-node-logs",
            ).strip()
            containers.append(container)
            alloy_ports[container] = alloy_port
            return container

        def exporter_metrics(container: str) -> list[str]:
            with urlopen(f"http://127.0.0.1:{alloy_ports[container]}/metrics", timeout=5) as response:
                metrics = response.read().decode()
            return [line for line in metrics.splitlines() if re.match(r"^otelcol_exporter_(?:queue_size|queue_capacity|enqueue_failed_log_records|send_failed_log_records|sent_log_records)(?:_total)?\{", line)]

        def query(selector: str = '{cluster="local"}') -> list[dict]:
            params = urlencode({"query": selector, "start": str(int((now - timedelta(hours=4)).timestamp() * 1e9)), "end": str(time.time_ns()), "limit": "1000", "direction": "forward"})
            with urlopen(f"http://127.0.0.1:{loki_port}/loki/api/v1/query_range?{params}", timeout=10) as response:
                payload = json.load(response)
            result = []
            for stream in payload["data"]["result"]:
                for value in stream["values"]:
                    labels = dict(stream["stream"])
                    if len(value) > 2:
                        labels.update(value[2])
                    result.append({"timestamp": int(value[0]), "body": value[1], "labels": labels})
            return result

        def by_marker() -> dict[str, list[dict]]:
            found: dict[str, list[dict]] = {}
            for record in query():
                try:
                    body = json.loads(record["body"])
                    marker = body.get("message", body.get("MESSAGE"))
                except json.JSONDecodeError:
                    marker = record["body"]
                found.setdefault(marker, []).append(record)
            return found

        try:
            loki_container = run(
                "docker", "run", "--detach", "--network", "host", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
                "--mount", f"type=bind,src={loki_path},dst=/etc/loki/local.yaml,readonly",
                "--mount", f"type=bind,src={lokidata},dst=/var/loki",
                LOKI_IMAGE, "-config.file=/etc/loki/local.yaml",
            ).strip()
            containers.append(loki_container)

            def loki_ready() -> bool:
                try:
                    with urlopen(f"http://127.0.0.1:{loki_port}/ready", timeout=2) as response:
                        return response.status == 200
                except (OSError, HTTPError):
                    return False

            wait_for(loki_ready, "temporary Loki readiness", 60)
            alloy = start_alloy()
            for suffix, path in paths.items():
                write_record(path, f"identity-{suffix}")
            write_record(journal, "journal-current", journal_record=True)
            has_audit = 'otelcol.receiver.filelog "audit"' in rendered
            assert has_audit, "the rendered pipeline must collect API audit files"
            assert 'otelcol.receiver.filelog "os_files"' in rendered, "the rendered pipeline must collect allowlisted OS file logs"
            (oslogs / "dpkg.log").write_text("fixture-package-install-evidence\n")
            if has_audit:
                body = json.dumps({
                    "apiVersion": "audit.k8s.io/v1", "kind": "Event", "level": "Metadata",
                    "auditID": "fixture-audit-id", "stage": "ResponseComplete", "verb": "get",
                    "requestURI": "/api/v1/nodes", "requestReceivedTimestamp": now.isoformat().replace("+00:00", "Z"),
                    "message": "audit-current", "user": {"username": "fixture-reader"},
                }, separators=(",", ":"))
                bodies["audit-current"] = body
                (auditlogs / "audit.log").write_text(body + "\n")
            wait_for(lambda: len(by_marker()) >= 4 + has_audit, "protobuf OTLP delivery from independent source identities", 45)
            initial = by_marker()
            for suffix in paths:
                record = initial[f"identity-{suffix}"][0]
                labels = record["labels"]
                expected = {"cluster": "local", "namespace": "devfeed", "container": "api", "pod": f"fixture-{suffix}", "node": f"fixture-node-{suffix}", "job": "devfeed/api", "service": "fixture-api", "severity": "ERROR"}
                assert all(labels.get(key) == value for key, value in expected.items()), record
                assert record["body"] == bodies[f"identity-{suffix}"], record
                assert record["timestamp"] == int(now.timestamp() * 1e9), record
                assert labels.get("k8s_node_name") == f"fixture-node-{suffix}", record
                assert labels.get("k8s_namespace_name") == "devfeed", record
                assert "observed_timestamp" in labels, record
            journal_entry = initial["journal-current"][0]
            assert journal_entry["body"] == bodies["journal-current"], journal_entry
            assert journal_entry["labels"].get("host_boot_id") == "fixture-boot-id", journal_entry
            assert journal_entry["labels"].get("journal_monotonic_timestamp") == "123456789", journal_entry
            if has_audit:
                audit_entry = initial["audit-current"][0]
                assert audit_entry["body"] == bodies["audit-current"], audit_entry
                assert audit_entry["timestamp"] == int(now.timestamp() * 1e9), audit_entry
                assert audit_entry["labels"].get("source") == "audit", audit_entry
                assert audit_entry["labels"].get("node") == "fixture-host", audit_entry
            os_entry = initial["fixture-package-install-evidence"][0]
            assert os_entry["body"] == "fixture-package-install-evidence", os_entry
            assert os_entry["labels"].get("source") == "os-file", os_entry
            assert os_entry["labels"].get("timestamp_quality") == "observed", os_entry
            assert "source_timestamp_unix_nano" not in os_entry["labels"], os_entry
            print("Fixture exporter metric samples:\n" + "\n".join(exporter_metrics(alloy)), flush=True)

            # Source time is retained even when the host clock is outside Loki's
            # allowed range; corrected observed time makes that evidence visible.
            skewed = {"journal-epoch": datetime(1970, 1, 2, tzinfo=timezone.utc), "journal-old-clock": now - timedelta(days=40), "journal-future-clock": now + timedelta(days=40)}
            for marker, timestamp in skewed.items():
                write_record(journal, marker, timestamp=timestamp, journal_record=True)
            wait_for(lambda: set(skewed) <= by_marker().keys(), "queryable bad-clock journal evidence", 45)
            found = by_marker()
            for marker, timestamp in skewed.items():
                entry = found[marker][0]
                labels = entry["labels"]
                assert entry["body"] == bodies[marker], entry
                assert int(labels["source_timestamp_unix_nano"]) == int(timestamp.timestamp() * 1e9), entry
                assert labels["clock_timestamp_adjusted"] == "true", entry
                reason = "source_more_than_10m_in_future" if timestamp > now else "source_older_than_14d"
                assert labels.get("clock_timestamp_adjustment_reason") == reason, entry
                assert abs(entry["timestamp"] - time.time_ns()) < 120 * 1e9, entry

            # A source older than the usual per-stream ordering window must also
            # survive a normal replay beside recently ingested same-stream data.
            write_record(paths["a"], "replay-three-hours", timestamp=now - timedelta(hours=3))
            wait_for(lambda: "replay-three-hours" in by_marker(), "same-stream old replay with time sharding", 45)
            replay = by_marker()["replay-three-hours"][0]
            assert replay["timestamp"] == int((now - timedelta(hours=3)).timestamp() * 1e9), replay

            # Make a quiet checkpoint durable before killing the process. This
            # isolates payload replay from permissible file-position duplicates.
            backend_available.clear()
            before_failures = statuses.count(503)
            outage_markers = [f"outage-{index:03}" for index in range(400)]
            reduced_capacity = 65536  # The production batch minimum must still fit.
            started = time.monotonic()
            for index, marker in enumerate(outage_markers):
                write_record(paths["ab"[index % 2]], marker)
            wait_for(lambda: statuses.count(503) > before_failures, "OTLP HTTP 503 and persistent queue", 30)
            # Ensure every unique record reached real payload storage before
            # removing its only source. No live backend or production logs are used.
            def all_payloads_stored() -> bool:
                payload = b"".join(path.read_bytes() for path in (state / "otel/payloads").rglob("*") if path.is_file())
                return all(marker.encode() in payload for marker in outage_markers)

            wait_for(all_payloads_stored, "all unique records in durable payload storage", 45)
            # Loki never accepted the failed request. SIGKILL drops process memory
            # while preserving only the mounted cursor and payload directory.
            time.sleep(12)
            assert not set(outage_markers) & by_marker().keys(), "503 proxy must not ingest records"
            assert any(path.is_file() and path.stat().st_size > 0 for path in (state / "otel/payloads").rglob("*")), "persistent payload files missing"
            size_samples = [float(line.rsplit(" ", 1)[1]) for line in exporter_metrics(alloy)
                            if line.startswith("otelcol_exporter_queue_size{") and 'data_type="logs"' in line
                            and 'component_id="otelcol.exporter.otlphttp.loki"' in line]
            assert size_samples and size_samples[0] > reduced_capacity, size_samples
            run("docker", "kill", "--signal", "KILL", alloy)
            # Remove the original fixture files while the collector is dead:
            # recovery can now only come from serialized payloads, even if an
            # on-disk source checkpoint lagged its most recent consumed offset.
            for path in paths.values():
                path.unlink()
            # A rollout may reduce capacity below a persisted incident backlog.
            # Exercise that exact recovery case instead of discarding old data.
            updated, changes = re.subn(r"queue_size\s*=\s*\d+", f"queue_size = {reduced_capacity}", config_path.read_text(), count=1)
            assert changes == 1
            config_path.write_text(updated)
            failures_before_restart = statuses.count(503)
            recovered = start_alloy()
            wait_for(lambda: statuses.count(503) > failures_before_restart, "503 retry after abrupt collector restart", 30)
            priority_available.set()
            write_record(journal, "priority-during-bulk-outage", journal_record=True)
            wait_for(lambda: "priority-during-bulk-outage" in by_marker(), "OS delivery past a blocked bulk backlog", 15)
            assert not set(outage_markers) & by_marker().keys(), "bulk must remain unavailable during priority proof"
            priority_available.clear()
            backend_available.set()
            recovery_started = time.monotonic()
            wait_for(lambda: set(outage_markers) <= by_marker().keys(), "durable queued payload replay", 60)
            recovery_seconds = time.monotonic() - recovery_started
            found = by_marker()
            counts = Counter({marker: len(found.get(marker, [])) for marker in outage_markers})
            missing = sorted(marker for marker, count in counts.items() if count == 0)
            duplicates = sum(max(0, count - 1) for count in counts.values())
            assert not missing, missing
            assert duplicates == 0, counts
            for index, marker in enumerate(outage_markers):
                assert found[marker][0]["labels"]["node"] == f"fixture-node-{'ab'[index % 2]}", found[marker]
            if has_audit:
                assert len(found["audit-current"]) == 1, "persisted audit offsets must avoid rereading acknowledged records"
            # A separate, intentional negative fixture proves permanent-loss
            # visibility. HTTP400 is not retried, unlike the preceding HTTP503.
            forced_status[0] = 400
            write_record(paths["a"], "intentional-http400-drop")
            wait_for(
                lambda: any(line.startswith("otelcol_exporter_send_failed_log_records_total{") and float(line.rsplit(" ", 1)[1]) >= 1 for line in exporter_metrics(recovered)),
                "permanent HTTP400 failure counter", 30,
            )
            assert "intentional-http400-drop" not in by_marker(), "the intentional rejected fixture must not appear in Loki"
            print("Permanent-loss metric sample:\n" + "\n".join(line for line in exporter_metrics(recovered) if "send_failed_log_records" in line), flush=True)
            forced_status[0] = None
            assert requests and all(path == "/otlp/v1/logs" and "protobuf" in content_type for path, content_type in requests), requests
            run("docker", "stop", "--time", "10", recovered)
            print(f"Passed: pinned Loki protobuf OTLP query proof; mixed-node identity, raw body, source/observed timestamps, bad-clock journal evidence, same-stream 3h replay; OS delivery continues while a bulk backlog exceeds capacity and retries HTTP503. HTTP503+SIGKILL replay: expected={len(outage_markers)}, unique={len(counts)}, missing={len(missing)}, duplicates={duplicates}, outage_and_restart_seconds={time.monotonic()-started:.2f}, recovery_drain_seconds={recovery_seconds:.2f}. Separate intentional HTTP400 rejection: missing=1, permanent_failure_counter>=1.")
        except Exception:
            print("Fixture HTTP status counts:", dict(Counter(statuses)), flush=True)
            try:
                print("Fixture records:", by_marker(), flush=True)
            except OSError as error:
                print("Fixture backend could not be queried:", error, flush=True)
            for container in containers:
                print(run("docker", "logs", "--tail", "100", container, stderr=subprocess.STDOUT))
            raise
        finally:
            for container in containers:
                subprocess.run(["docker", "rm", "--force", container], capture_output=True, check=False)
            proxy.shutdown()
            proxy.server_close()
            proxy_thread.join(timeout=5)


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
                    IMAGE, "validate", "--stability.level=public-preview", "/etc/alloy/config.alloy",
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

    exercise_native_journal(configs[True])
    exercise_otlp_pipeline(configs[True])


if __name__ == "__main__":
    main()
