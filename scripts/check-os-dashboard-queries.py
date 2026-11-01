#!/usr/bin/env python3
"""Validate actual OS dashboard LogQL against synthetic records in local Loki.

Requires Docker and PyYAML. Never connects to Kubernetes or a remote Loki.
The small fixture checks semantics, not production query throughput.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import statistics
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

import yaml


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "kubernetes/projects/system/apps/rancher-monitoring/os-logs-dashboard.yaml"
HOST_DASHBOARD = ROOT / "kubernetes/projects/system/apps/rancher-monitoring/os-incident-evidence-dashboard.yaml"
LOKI_VALUES = ROOT / "kubernetes/projects/system/apps/loki/values.yaml"
BOOT = "0123456789abcdef0123456789abcdef"


@dataclass(frozen=True)
class Case:
    name: str
    message: str
    level: str = "info"
    priority: str = "6"
    unit: str = "fixture.service"
    identifier: str = "fixture"
    indexed_unit: str = "other"
    node: str = "fixture-rpi1"
    adjusted: bool = False
    excluded: bool = False
    source: str = "journal"
    kind: str = "journal"
    source_age_seconds: int = 60
    audit_code: int | None = 200
    source_timestamp_ns: int | None = None

    @property
    def service(self) -> str:
        if self.kind == "plain":
            return "/var/log/dpkg.log"
        return self.unit or self.identifier or self.indexed_unit


CASES = [
    Case("normal", "ordinary successful operation"),
    Case("error-word-decoy", "previous error resolved successfully"),
    *(Case(f"priority-{priority}", "native error", "error", priority=str(priority)) for priority in range(4)),
    Case("native-warning", "native warning", "warning", priority="4"),
    Case("debug", "verbose details", "debug", priority="7"),
    Case("logfmt-error", "time=now level=error msg=bad", "error"),
    Case("uppercase-error", "time=now level=ERROR msg=bad", "error"),
    Case("json-error", '{"level":"error","msg":"bad"}', "error"),
    Case("json-uppercase", '{"level" : "FATAL", "msg":"bad"}', "error"),
    Case("json-multiline", '{"level"\n:\n"ERROR", "msg":"bad"}', "error"),
    Case("panic", "panic: bad state", "error"),
    Case("fatal", "fatal error: bad state", "error"),
    Case("logfmt-warning", "level=WARNING msg=slow", "warning"),
    Case("json-warning", '{"level":"warn","msg":"slow"}', "warning"),
    Case("embedded-error-wins", "level=error underlying warning", "error", priority="4"),
    Case("native-error-wins", "level=warn underlying error", "error", priority="3"),
    Case("memory", "level=error killed process 123", "error"),
    Case("storage", "level=error read-only file system", "error"),
    Case("clock", "level=error x509: certificate not yet valid", "error"),
    Case("network", "level=error no route to host", "error"),
    Case("service", "level=error Failed to start example", "error"),
    Case("identifier", "level=error identifier fallback", "error", unit="", identifier="custom-logger"),
    Case("indexed-unit", "native indexed unit fallback", "error", priority="3", unit="", identifier="", indexed_unit="kernel"),
    Case("second-node", "level=error second node", "error", node="fixture-rpi2"),
    Case("literal-search", 'keep literal A.*[x] "quoted" \\ path café'),
    Case("regex-decoy", "keep literal ABCx unquoted path cafe"),
    Case("multiline", "first line\nlevel=ERROR second line", "error"),
    Case("long-message", "x" * 400 + " level=ERROR no route to host LATE_SEARCH_TOKEN", "error"),
    Case("adjusted", "level=error source clock replaced", "error", adjusted=True, node="fixture-rpi6", source_age_seconds=40 * 86400),
    Case("near-epoch-native", "original source time is one second after epoch", adjusted=True, node="fixture-rpi6", source_timestamp_ns=1_000_000_000),
    Case("future", "future source clock replaced", "warning", priority="4", adjusted=True, node="fixture-rpi5", source_age_seconds=-40 * 86400),
    Case("canary", "level=error canary text", "error", indexed_unit="home-lab-log-canary", excluded=True),
    Case("plain-file", 'plain file A.*[x] "quoted" \\ path café', "unspecified", unit="", identifier="", indexed_unit="os-file", node="fixture-rpi7", source="os-file", kind="plain"),
    Case("plain-error", "level=ERROR package failure", "error", unit="", identifier="", indexed_unit="os-file", node="fixture-rpi7", source="os-file", kind="plain"),
    Case("imported", "level=ERROR historical import", "error", indexed_unit="os-file", node="fixture-rpi8", source="os-file", kind="imported", source_age_seconds=40 * 86400),
    Case("near-epoch-imported", "imported source time is one second after epoch", indexed_unit="os-file", node="fixture-rpi8", source="os-file", kind="imported", source_timestamp_ns=1_000_000_000),
    Case("audit", "", unit="", identifier="", indexed_unit="kube-apiserver", node="fixture-rpi3", source="audit", kind="audit"),
    Case("audit-adjusted", "", unit="", identifier="", indexed_unit="kube-apiserver", node="fixture-rpi4", source="audit", kind="audit", adjusted=True, source_age_seconds=40 * 86400),
    Case("audit-server-error", "", "error", unit="", identifier="", indexed_unit="kube-apiserver", node="fixture-rpi5", source="audit", kind="audit", audit_code=503),
    Case("audit-warning", "", "warning", unit="", identifier="", indexed_unit="kube-apiserver", node="fixture-rpi6", source="audit", kind="audit", audit_code=403),
    Case("audit-request", "", "unspecified", unit="", identifier="", indexed_unit="kube-apiserver", node="fixture-rpi2", source="audit", kind="audit", audit_code=None),
]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def panels(items: list[dict]) -> dict[int, dict]:
    result = {}
    for item in items:
        result[item["id"]] = item
        result.update(panels(item.get("panels", [])))
    return result


def main() -> None:
    dashboard = json.loads(yaml.safe_load(DASHBOARD.read_text())["data"]["os-logs.json"])
    assert dashboard["uid"] == "os-logs"
    assert dashboard["timezone"] == "utc", "both displayed timestamps are labeled UTC"
    host_dashboard = json.loads(yaml.safe_load(HOST_DASHBOARD.read_text())["data"]["os-incident-evidence.json"])
    assert host_dashboard["uid"] == "os-incident-evidence"
    for panel in panels(host_dashboard["panels"]).values():
        assert panel.get("datasource", {}).get("type") != "loki", "host metrics still depend on Loki"
        for target in panel.get("targets", []):
            assert target.get("datasource", {}).get("type") != "loki", "host metric query still depends on Loki"
    variables = {variable["name"] for variable in dashboard.get("templating", {}).get("list", [])}
    assert "contains" in variables and "search" not in variables, "old regex search URL state must not become a literal Contains filter"
    assert "signal" not in variables, "retired category control returned"
    level_variable = next(variable for variable in dashboard["templating"]["list"] if variable["name"] == "level")
    assert level_variable.get("multi") is True and level_variable.get("includeAll") is False, "Level must support multiple selections without a duplicate built-in All"
    level_choices = [tuple(part.strip() for part in item.rsplit(":", 1)) for item in level_variable["query"].split(",")]
    level_options = [value for _, value in level_choices]
    assert len(level_options) == 6 and set(level_options) == {"error", "warning", "info", "debug", "unspecified", ".*"}, "Level must contain All levels and five separate individual choices"
    assert dict(level_choices).get("All levels") == ".*", "the All levels preset must retain its readable label"
    assert level_variable.get("current", {}).get("value") == [".*"] and level_variable["current"].get("text") == ["All levels"], "Level must default to the existing All levels preset"
    log_panels = panels(dashboard["panels"])
    assert set(log_panels) == {11}, "OS Logs must contain only its log browser, without aggregate panels"
    targets = log_panels[11].get("targets", [])
    assert len(targets) == 1, "the browser must issue exactly one query"
    target = targets[0]
    assert target.get("queryType") == "range" and 0 < target.get("maxLines", 0) <= 100, "the browser must use a bounded log-range query"
    browser_expression = target["expr"]
    assert "${level:pipe}" in browser_expression and "${level:raw}" not in browser_expression, "multiple levels must interpolate as regex OR"
    assert "count_over_time(" not in browser_expression, "an aggregate replaced the log browser"
    assert not re.search(r"\bcount\s+[\"`]", browser_expression), "the browser recompiles a template regex for each record"
    first_regexp = browser_expression.find("| regexp ")
    assert first_regexp < 0 or browser_expression.index("|= ${contains:doublequote}") < first_regexp, "the browser classifies records before applying Contains"
    values = yaml.safe_load(LOKI_VALUES.read_text())["loki"]
    image = f"grafana/loki:{values['image']['tag']}@{values['image']['digest']}"
    timings: list[float] = []
    with tempfile.TemporaryDirectory(prefix="os-dashboard-loki-") as temporary:
        directory = Path(temporary)
        directory.chmod(0o755)
        state = directory / "state"
        state.mkdir()
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        config = {
            "auth_enabled": False,
            "analytics": {"reporting_enabled": False},
            "server": {"http_listen_address": "127.0.0.1", "http_listen_port": port,
                       "grpc_listen_address": "127.0.0.1", "grpc_listen_port": free_port(), "log_level": "warn"},
            "common": {"instance_addr": "127.0.0.1", "path_prefix": "/var/loki", "replication_factor": 1,
                       "ring": {"kvstore": {"store": "inmemory"}},
                       "storage": {"filesystem": {"chunks_directory": "/var/loki/chunks", "rules_directory": "/var/loki/rules"}}},
            "schema_config": values["schemaConfig"],
            "limits_config": values["limits_config"],
            "querier": values.get("querier", {}),
            "ingester": {**values.get("ingester", {}), "lifecycler": {"min_ready_duration": "0s"},
                         "wal": {"enabled": False}},
            "compactor": {"working_directory": "/var/loki/compactor", "retention_enabled": False},
        }
        config_path = directory / "loki.yaml"
        config_path.write_text(yaml.safe_dump(config))
        container = run(
            "docker", "run", "--detach", "--network", "host", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
            "--mount", f"type=bind,src={config_path},dst=/etc/loki/fixture.yaml,readonly",
            "--mount", f"type=bind,src={state},dst=/var/loki", image, "-config.file=/etc/loki/fixture.yaml",
        )
        try:
            deadline = time.monotonic() + 45
            while True:
                try:
                    with urlopen(base + "/ready", timeout=2) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError):
                    pass
                assert time.monotonic() < deadline, "local Loki did not become ready"
                time.sleep(0.25)
            now = time.time_ns()
            start, end = now - 120_000_000_000, now
            streams: dict[tuple, dict] = {}
            originals: dict[str, tuple[int, str]] = {}
            source_times: dict[str, int] = {}
            for index, case in enumerate(CASES):
                timestamp = now - 60_000_000_000 + index * 1_000_000
                source_timestamp = timestamp if case.source_age_seconds == 60 else now - case.source_age_seconds * 1_000_000_000
                if case.source_timestamp_ns is not None:
                    source_timestamp = case.source_timestamp_ns
                source_times[case.name] = source_timestamp
                record = {"MESSAGE": f"fixture={case.name} {case.message}", "PRIORITY": case.priority,
                          "_BOOT_ID": BOOT, "__REALTIME_TIMESTAMP": str(source_timestamp // 1000),
                          "__MONOTONIC_TIMESTAMP": str(index * 1000), "_TRANSPORT": "journal"}
                if case.unit:
                    record["_SYSTEMD_UNIT"] = case.unit
                if case.identifier:
                    record["SYSLOG_IDENTIFIER"] = case.identifier
                if case.kind == "audit":
                    record = {"auditID": "fixture=" + case.name, "verb": "patch", "stage": "ResponseComplete",
                              "user": {"username": "fixture-user"}, "objectRef": {"resource": "nodes", "name": case.node},
                              "requestReceivedTimestamp": datetime.fromtimestamp(source_timestamp / 1e9, timezone.utc).isoformat().replace("+00:00", "Z")}
                    if case.audit_code is not None:
                        record["responseStatus"] = {"code": case.audit_code}
                    else:
                        record["stage"] = "RequestReceived"
                body = f"fixture={case.name} {case.message}" if case.kind == "plain" else json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                originals[case.name] = (timestamp, body)
                labels = {"cluster": "local", "source": case.source, "node": case.node,
                          "unit": case.indexed_unit, "job": {"journal": "node/system", "os-file": "node/os-file", "audit": "node/audit"}[case.source]}
                metadata = {"severity_text": {"0": "critical", "1": "critical", "2": "critical", "3": "error", "4": "warn", "7": "debug"}.get(case.priority, "info")}
                if case.source == "journal":
                    metadata.update({"journal_priority": case.priority, "host_boot_id": BOOT})
                if case.source in {"journal", "audit"}:
                    metadata["source_timestamp_unix_nano"] = str(source_timestamp)
                if case.source == "os-file":
                    metadata["timestamp_quality"] = "observed"
                    metadata["log_file_path"] = "/host/var/log/home-lab-incident-backfill/snapshot.jsonl" if case.kind == "imported" else "/host/var/log/dpkg.log"
                if case.unit and case.source == "journal":
                    metadata["systemd_unit"] = case.unit
                if case.source == "audit":
                    metadata["audit_verb"] = "patch"
                if case.adjusted:
                    metadata["clock_timestamp_adjusted"] = "true"
                    metadata["clock_timestamp_adjustment_reason"] = "source_older_than_14d" if case.source_age_seconds > 0 else "source_more_than_10m_in_future"
                key = tuple(sorted(labels.items()))
                streams.setdefault(key, {"stream": labels, "values": []})["values"].append([str(timestamp), body, metadata])
            request = Request(base + "/loki/api/v1/push", data=json.dumps({"streams": list(streams.values())}).encode(),
                              headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=10) as response:
                assert response.status == 204

            def query(expression: str, limit: int = 1000) -> list[dict]:
                params = {"query": expression, "limit": str(limit), "direction": "backward", "start": str(start), "end": str(end)}
                before = time.monotonic()
                try:
                    with urlopen(base + "/loki/api/v1/query_range?" + urlencode(params), timeout=20) as response:
                        payload = json.load(response)
                except HTTPError as error:
                    raise AssertionError(error.read().decode()) from error
                timings.append(time.monotonic() - before)
                assert payload["status"] == "success", payload
                return payload["data"]["result"]

            def expression(*, search: str = "", level: str | list[str] = ".*", source: str = "journal", service: str = "", node: str = "fixture-rpi.*") -> str:
                # Match Grafana's pipe format for selected values; legacy URLs
                # can still supply a single value containing an OR expression.
                rendered_level = "|".join(level) if isinstance(level, list) else level
                result = browser_expression
                for old, new in {"${node:regex}": node, "${contains:doublequote}": json.dumps(search, ensure_ascii=False),
                                 "${level:pipe}": rendered_level, "${source:raw}": source,
                                 "${source:regex}": source, "${source}": source,
                                 "${service:doublequote}": json.dumps(service), "$__range": "2m", "$__interval": "1m"}.items():
                    result = result.replace(old, new)
                assert "${" not in result, result
                return result

            def browser(**kwargs: str | list[str]) -> dict[str, dict]:
                result = {}
                for stream in query(expression(**kwargs), limit=target["maxLines"]):
                    for value in stream["values"]:
                        row = json.loads(value[1])
                        match = re.search(r"fixture=([a-z0-9-]+)", row["Message"])
                        if match:
                            name = match.group(1)
                        else:
                            candidates = [case.name for case in CASES if case.source == kwargs.get("source", "journal") and case.node == row["Node"]]
                            assert len(candidates) == 1, row
                            name = candidates[0]
                        assert name not in result, f"duplicate browser row: {name}"
                        row["timestamp"] = int(value[0])
                        result[name] = row
                return result

            # Validate actual persisted evidence independently of display formatting.
            raw = query('{cluster="local",node=~"fixture-rpi.*"}')
            seen = {}
            for stream in raw:
                for value in stream["values"]:
                    seen[int(value[0])] = value[1]
            assert seen == {timestamp: body for timestamp, body in originals.values()}, "original bodies or stored timestamps changed"

            def field(row: dict, name: str) -> str:
                for key, value in row.items():
                    if re.sub(r"[^a-z]", "", key.lower()).removesuffix("utc") == name:
                        return value
                raise AssertionError((name, row))

            expected = {case.name: case for case in CASES if not case.excluded}
            for source in ("journal", "audit", "os-file"):
                rows = browser(source=source)
                source_expected = {name: case for name, case in expected.items() if case.source == source}
                assert rows.keys() == source_expected.keys(), (source, rows.keys() - source_expected.keys(), source_expected.keys() - rows.keys())
                for name, case in source_expected.items():
                    row = rows[name]
                    assert (row["Node"], row["Service"], row["Level"]) == (case.node, case.service, case.level), (name, row, case)
                    assert row["timestamp"] == originals[name][0], (name, row)
                    event_time = field(row, "eventtime")
                    context = field(row, "timecontext").lower()
                    if case.kind == "plain":
                        assert event_time.lower() in {"", "unknown", "—", "unavailable"}, (name, row)
                        assert "not recorded" in context or "unknown" in context, (name, row)
                    else:
                        parsed = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        assert parsed.utcoffset().total_seconds() == 0, (name, row)
                        assert abs(parsed.timestamp() * 1e9 - source_times[name]) < 1e9, (name, row)
                    if case.adjusted:
                        assert "adjust" in context or "replac" in context or ("collected" in context and "original" in context), (name, row)
                    if case.kind == "imported":
                        assert "import" in context or "snapshot" in context, (name, row)
                    if case.kind == "audit":
                        assert "patch" in row["Message"] and "fixture-user" in row["Message"], (name, row)
            journal_expected = {name: case for name, case in expected.items() if case.source == "journal"}
            for source in ("journal", "audit", "os-file"):
                for level in ("error", "warning", "error|warning", "info", "debug", "unspecified"):
                    assert browser(source=source, level=level).keys() == {name for name, case in expected.items() if case.source == source and re.fullmatch(level, case.level)}, (source, level)
                for selected_levels, accepted_levels in (
                    (["error", "warning"], {"error", "warning"}),
                    (["error", "debug"], {"error", "debug"}),
                    (["info", "unspecified"], {"info", "unspecified"}),
                    ([".*"], {"error", "warning", "info", "debug", "unspecified"}),
                ):
                    expected_names = {name for name, case in expected.items() if case.source == source and case.level in accepted_levels}
                    assert browser(source=source, level=selected_levels).keys() == expected_names, (source, selected_levels)
            assert browser(search='A.*[x] "quoted" \\ path café').keys() == {"literal-search"}, "Contains must be literal decoded MESSAGE text"
            assert browser(search="a.*[x]").keys() == set(), "Contains must remain case-sensitive"
            assert browser(search="LATE_SEARCH_TOKEN").keys() == {"long-message"}, "display truncation must not truncate search/classification input"
            assert browser(search="PRIORITY").keys() == set(), "Contains incorrectly searches JSON envelope fields"
            assert browser(node="fixture-rpi2").keys() == {"second-node"}, "node selector leaked another node"
            assert browser(service="fixture.").keys() == {name for name, case in journal_expected.items() if "fixture." in case.service}, "Service must search the actual service name"
            assert browser(service="fixture.*").keys() == set(), "Service must be a literal substring, not regex"
            assert browser(search="second node").keys() == {"second-node"}
            assert browser(search="no matching phrase").keys() == set()
            assert browser(service="custom-logger").keys() == {"identifier"}
            assert browser(source="audit", search="HTTP 503").keys() == {"audit-server-error"}, "Contains must search the readable audit summary"
            link = next(
                prop["value"][0]["url"]
                for override in panels(dashboard["panels"])[11]["fieldConfig"]["overrides"]
                if override["matcher"].get("options") == "Message"
                for prop in override["properties"] if prop["id"] == "links"
            )
            for source, node in (("journal", "fixture-rpi1"), ("audit", "fixture-rpi3"), ("os-file", "fixture-rpi7"), ("os-file", "fixture-rpi8")):
                url = link
                for old, new in {"${source:raw}": source, "${__data.fields.Node}": node,
                                 "${__from}": str(start // 1_000_000), "${__to}": str(end // 1_000_000)}.items():
                    url = url.replace(old, new)
                pane = next(iter(json.loads(parse_qs(urlsplit(url).query)["panes"][0]).values()))
                assert pane["datasource"] == "loki" and pane["range"] == {"from": str(start // 1_000_000), "to": str(end // 1_000_000)}, pane
                linked = {int(value[0]): value[1] for stream in query(pane["queries"][0]["expr"]) for value in stream["values"]}
                expected_originals = {originals[case.name][0]: originals[case.name][1] for case in CASES if case.source == source and case.node == node}
                assert linked == expected_originals, (source, node, "Explore link did not return exact original evidence")
            print(f"Passed: {len(CASES)} journal/audit/file fixtures; one bounded OS Logs browser query; single/multiple levels and All, native and embedded severity, service fallback, node/source isolation, literal Contains/Service, adjusted/imported/original source time and exact original bodies/stored timestamps through Explore. No aggregate panel or Host Metrics Loki dependency remains.")
            print(f"Local semantic fixture only: {len(timings)} queries, median {statistics.median(timings)*1000:.1f} ms, max {max(timings)*1000:.1f} ms. Production throughput was not measured.")
        except Exception:
            print(subprocess.check_output(["docker", "logs", "--tail", "35", container], text=True, stderr=subprocess.STDOUT))
            raise
        finally:
            subprocess.run(["docker", "rm", "--force", container], capture_output=True, check=False)


if __name__ == "__main__":
    main()
