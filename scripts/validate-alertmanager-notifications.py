#!/usr/bin/env python3
"""Exercise real Alertmanager routing, Slack rendering and group notifications locally.

Docker is required. No cluster API or Slack webhook is contacted. Optional
--effective-config checks the operator-generated route and receiver against Git;
only that route/receiver is used and its URL is replaced before writing fixtures.
"""

import argparse
import copy
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

import yaml


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "kubernetes/projects/system/apps/rancher-monitoring"
IMAGE = "prom/alertmanager:v0.34.1"
FIXTURES = ROOT / "scripts/tests/fixtures/alertmanager-notifications.yaml"


def docker(*args, check=True, timeout=90):
    result = subprocess.run(
        ["docker", *args], check=check, capture_output=True, text=True, timeout=timeout
    )
    return (result.stdout if check else result.stdout + result.stderr).strip()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def native_route(route, receiver):
    """Translate the small route subset owned by this AlertmanagerConfig."""
    names = {
        "groupBy": "group_by", "groupWait": "group_wait",
        "groupInterval": "group_interval", "repeatInterval": "repeat_interval",
        "continue": "continue",
    }
    result = {names[key]: value for key, value in route.items() if key in names}
    if "receiver" in route:
        result["receiver"] = receiver
    if "matchers" in route:
        result["matchers"] = [
            f'{item["name"]}{item["matchType"]}{json.dumps(item["value"])}'
            for item in route["matchers"]
        ]
    if "routes" in route:
        result["routes"] = [native_route(child, receiver) for child in route["routes"]]
    check(not set(route) - set(names) - {"receiver", "matchers", "routes"},
          "Update the validator before adding unsupported route fields")
    return result


def native_slack(slack):
    names = {
        "sendResolved": "send_resolved", "username": "username",
        "iconEmoji": "icon_emoji", "title": "title", "titleLink": "title_link",
        "fallback": "fallback", "color": "color", "text": "text",
        "fields": "fields", "footer": "footer", "actions": "actions",
        "mrkdwnIn": "mrkdwn_in", "pretext": "pretext", "channel": "channel",
        "shortFields": "short_fields", "linkNames": "link_names",
    }
    check(not set(slack) - set(names) - {"apiURL"},
          "Update the validator before adding unsupported Slack fields")
    result = {names[key]: value for key, value in slack.items() if key in names}
    # The real Secret is never read or used by this validator.
    result["api_url"] = "http://127.0.0.1:1/capture"
    return result


def route_walk(route):
    yield route
    for child in route.get("routes", []):
        yield from route_walk(child)


def compare_subset(expected, actual, path):
    for key, value in expected.items():
        check(key in actual, f"Effective config is missing {path}.{key}")
        if key == "routes":
            check(len(value) == len(actual[key]), f"Different route count at {path}")
            for index, (left, right) in enumerate(zip(value, actual[key])):
                compare_subset(left, right, f"{path}.routes[{index}]")
        elif key == "matchers":
            check(sorted(value) == sorted(actual[key]), f"Different matchers at {path}")
        else:
            check(value == actual[key], f"Effective config differs at {path}.{key}")


def configuration(effective_path):
    manifest = yaml.safe_load((APP / "alertmanager-slack.yaml").read_text())
    spec = manifest["spec"]
    receiver_name = "slack"
    route = native_route(spec["route"], receiver_name)
    slack = native_slack(spec["receivers"][0]["slackConfigs"][0])
    check(spec["route"]["repeatInterval"] == "4h", "The stable repeat interval must remain 4h")
    check(spec["route"]["groupInterval"] == "5m", "Group updates must retain the 5m interval")
    check(spec["route"]["groupWait"] == "30s", "Initial grouping must retain the 30s wait")
    for child in route_walk(route):
        check(child.get("repeat_interval", "4h") == "4h", "A child route overrides the 4h stable repeat")
    check(slack["send_resolved"] is True, "Resolved alerts must be delivered")
    inhibit_rules = []
    if effective_path:
        effective = yaml.safe_load(effective_path.read_text())
        receiver_name = f'{manifest["metadata"]["namespace"]}/{manifest["metadata"]["name"]}/slack'
        expected = native_route(spec["route"], receiver_name)
        # The Operator adds continue=true to the top-level CRD route.
        expected["continue"] = True
        candidates = [item for item in effective["route"].get("routes", [])
                      if item.get("receiver") == receiver_name]
        check(len(candidates) == 1, "Expected exactly one compiled home-lab Slack route")
        route = copy.deepcopy(candidates[0])
        compare_subset(expected, route, "route")
        receiver = next(item for item in effective["receivers"] if item["name"] == receiver_name)
        check(len(receiver.get("slack_configs", [])) == 1, "Expected one Slack integration")
        actual_slack = copy.deepcopy(receiver["slack_configs"][0])
        compare_subset({key: value for key, value in slack.items() if key != "api_url"},
                       actual_slack, "receiver.slack_configs[0]")
        # Only the tested receiver is retained; secrets/other integrations are excluded.
        actual_slack.pop("api_url_file", None)
        actual_slack.pop("http_config", None)
        actual_slack["api_url"] = slack["api_url"]
        slack = actual_slack
        inhibit_rules = copy.deepcopy(effective.get("inhibit_rules", []))
        print("PASS: exact operator-compiled home-lab route and Slack template match Git", flush=True)
    return {
        "route": {"receiver": "null", "routes": [route]},
        "receivers": [{"name": "null"}, {"name": receiver_name, "slack_configs": [slack]}],
        "inhibit_rules": inhibit_rules,
    }, receiver_name


def amtool(temp, *args):
    return docker("run", "--rm", "--network=none", "--user", "0:0",
                  "--volume", f"{temp}:/fixtures:ro", "--entrypoint", "/bin/amtool", IMAGE, *args)


def template_data(alerts):
    common = {}
    if alerts:
        common = {key: value for key, value in alerts[0]["labels"].items()
                  if all(alert["labels"].get(key) == value for alert in alerts)}
    return {
        "receiver": "slack", "status": "firing" if any(alert["status"] == "firing" for alert in alerts) else "resolved",
        "alerts": alerts, "groupLabels": {key: common[key] for key in ("cluster", "incident", "namespace") if key in common},
        "commonLabels": common, "commonAnnotations": {}, "externalURL": "http://alertmanager.home",
        "notification_reason": "new alerts added",
    }


def validate_rendering(temp, config):
    alerts = yaml.safe_load(FIXTURES.read_text())["alerts"]
    slack = config["receivers"][1]["slack_configs"][0]
    (temp / "empty.tmpl").write_text("")
    cases = {
        "firing": [copy.deepcopy(alerts[0])],
        "resolved": [copy.deepcopy(alerts[2])],
        "resolved-loss": [copy.deepcopy(alerts[0])],
        "mixed": copy.deepcopy(alerts),
        "missing-namespace": [copy.deepcopy(alerts[0])],
        "priority": [copy.deepcopy(alerts[1]) for _ in range(10)] + [copy.deepcopy(alerts[0])],
        "adversarial": [copy.deepcopy(alerts[0]) for _ in range(8)],
        "overflow": [copy.deepcopy(alerts[0]) for _ in range(30)],
    }
    cases["missing-namespace"][0]["labels"].pop("namespace")
    cases["resolved-loss"][0]["status"] = "resolved"
    for index, alert in enumerate(cases["overflow"]):
        alert["labels"]["pod"] = f"alloy-overflow-{index}"
        alert["annotations"]["description"] = "Long diagnostic description " * 100
    for alert in cases["adversarial"]:
        for key in ("severity", "alertname", "pod", "reason"):
            alert["labels"][key] = key * 1000
        alert["annotations"]["summary"] = "summary " * 1000
        alert["annotations"]["description"] = "description " * 1000
        alert["annotations"]["runbook_url"] = "https://example.invalid/" + "runbook" * 1000
        alert["annotations"]["dashboard_url"] = "https://example.invalid/" + "dashboard" * 1000
        alert["generatorURL"] = "https://example.invalid/" + "query" * 1000
    for name, fixture in cases.items():
        (temp / "data.json").write_text(json.dumps(template_data(fixture)))
        # One native render per fixture keeps CI quick. Synthetic values contain
        # no record separators, so each rendered field remains unambiguous.
        names = ("title", "fallback", "text")
        texts = [slack[field] for field in names] + [field["value"] for field in slack.get("fields", [])]
        values = amtool(temp, "template", "render", "--template.glob=/fixtures/empty.tmpl",
                        "--template.text=" + "\x1e".join(texts), "--template.data=/fixtures/data.json").split("\x1e")
        check(len(values) == len(texts), f"Ambiguous {name} fixture rendering")
        rendered = dict(zip(names, values[:len(names)]))
        for field in names:
            check("<no value>" not in rendered[field], f"Missing value in {name} {field}")
        fields = values[len(names):]
        for field, value in zip(slack.get("fields", []), fields):
            check(value and "<no value>" not in value, f"Empty/missing {name} {field['title']} field")
        check(rendered["title"] and rendered["fallback"], f"Empty {name} notification title")
        check(len(rendered["text"]) < 4000, f"Unbounded {name} notification body")
        if name == "mixed":
            for alert in fixture:
                check(alert["labels"]["alertname"] in rendered["text"], "Mixed group hides an alert identity")
            check("FIRING" in rendered["text"] and "RESOLVED" in rendered["text"],
                  "Mixed group must display each alert's individual status")
            check("alloy-faro-fixture-a" in rendered["text"], "Permanent loss must identify the producer")
            check("too_far_behind" in rendered["text"], "Loki rejection reason must remain visible")
            check("https://example.invalid/runbooks/log-delivery" in rendered["text"], "Runbook link missing")
            check(any("mixed" in value.lower() for value in fields), "Mixed severities need an explicit field value")
            severity = next(value for field, value in zip(slack["fields"], fields) if field["title"] == "Severity")
            check("critical" in severity.lower(), "Mixed group must retain the firing critical severity")
        if name == "priority":
            check("alloy-faro-fixture-a" in rendered["text"], "Detail cap must prioritize firing permanent loss")
        if name == "overflow":
            check("http://alertmanager.home" in rendered["text"], "Truncation must link to the full alert group")
            check(rendered["text"].count("*FIRING ·") == 4, "Overflow detail count must remain bounded at four")
        if name == "missing-namespace":
            scope = " ".join(fields + list(rendered.values()))
            check("cluster" in scope.lower() or "home-lab" in scope or "not provided" in scope.lower(),
                  "Missing namespace must retain useful cluster scope")
        if name in {"firing", "mixed", "resolved-loss", "overflow"}:
            check("permanent" in rendered["text"].lower(), "Permanent loss warning disappeared")
        print(f"PASS: {name} Slack template ({len(rendered['text'])} characters)", flush=True)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(url, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as response:
        return response.read()


def validate_delivery(temp, config, receiver):
    """Keep the real notifier and routes; accelerate timing only in a disposable copy."""
    captures = []
    lock = threading.Lock()

    class Capture(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with lock:
                captures.append(payload)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Capture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    local = copy.deepcopy(config)
    for route in route_walk(local["route"]):
        route.update(group_wait="3s", group_interval="4s", repeat_interval="40s")
    local["receivers"][1]["slack_configs"][0]["api_url"] = f"http://127.0.0.1:{server.server_port}/capture"
    path = temp / "delivery.yaml"
    path.write_text(yaml.safe_dump(local))
    path.chmod(0o644)
    name = f"alertmanager-validation-{uuid.uuid4().hex[:12]}"
    port = free_port()
    base = f"http://127.0.0.1:{port}"

    def count():
        with lock:
            return len(captures)

    def wait_count(expected, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if count() >= expected:
                check(count() == expected, "Unexpected duplicate/group-split Slack delivery")
                return
            time.sleep(0.1)
        raise AssertionError(f"Expected {expected} local Slack deliveries, received {count()}")

    def reason():
        fields = captures[-1]["attachments"][0]["fields"]
        return next(field["value"] for field in fields if field["title"] == "Notification")

    try:
        docker("run", "--detach", "--name", name, "--network=host", "--user", "0:0",
               "--volume", f"{temp}:/fixtures:ro", IMAGE,
               "--config.file=/fixtures/delivery.yaml", "--storage.path=/tmp/alertmanager",
               f"--web.listen-address=127.0.0.1:{port}", "--cluster.listen-address=")
        deadline = time.monotonic() + 15
        while True:
            try:
                request(f"{base}/-/ready")
                break
            except (OSError, urllib.error.URLError):
                check(time.monotonic() < deadline, "Local Alertmanager failed to become ready")
                time.sleep(0.2)
        now = datetime.now(timezone.utc)
        alerts = yaml.safe_load(FIXTURES.read_text())["alerts"]
        for alert in alerts:
            alert.pop("status", None)
            alert.pop("fingerprint", None)
            # Fresh starts let groupWait collect the complete batch. Backdating
            # past groupWait allows Alertmanager to flush the first member early.
            alert["startsAt"] = now.isoformat()
            alert["endsAt"] = (now + timedelta(minutes=10)).isoformat()
        # Different names/severities in one namespace share the explicit incident group.
        request(f"{base}/api/v2/alerts", alerts[:2])
        wait_count(1)
        check(reason() == "first notification", "Initial native notification reason missing")
        initial = json.dumps(captures[-1])
        check("alloy-faro-fixture-a" in initial and "too_far_behind" in initial,
              "Critical related failure suppressed permanent-loss evidence")
        alerts[0]["annotations"]["description"] += " Updated counter value: 29."
        request(f"{base}/api/v2/alerts", alerts[:2])
        time.sleep(8.5)
        check(count() == 1, "Annotation changes triggered a notification before the repeat interval")
        print("PASS: unchanged fingerprints/updated counters do not repeat at groupInterval", flush=True)
        wait_count(2, timeout=50)
        check(reason() == "repeat interval elapsed", "Native repeat-interval reason missing")
        print("PASS: unchanged group repeats once at the accelerated 40s interval", flush=True)
        request(f"{base}/api/v2/alerts", alerts)
        wait_count(3)
        check(reason() == "new alerts added", "Native new-member notification reason missing")
        alerts[0]["endsAt"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        request(f"{base}/api/v2/alerts", alerts)
        wait_count(4)
        check(reason() == "some alerts resolved", "Native mixed-resolution reason missing")
        mixed = json.dumps(captures[-1])
        check("FIRING" in mixed and "RESOLVED" in mixed, "Delivered mixed statuses are ambiguous")
        for alert in alerts:
            alert["endsAt"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        request(f"{base}/api/v2/alerts", alerts)
        wait_count(5)
        check(reason() == "all alerts resolved", "Native final-resolution reason missing")
        check("RESOLVED" in json.dumps(captures[-1]), "Missing resolved notification")
        print("PASS: one initial group, one membership update, mixed update and final resolution", flush=True)
        burns = yaml.safe_load(FIXTURES.read_text())["devfeed_burns"]
        for alert in burns:
            alert["startsAt"] = datetime.now(timezone.utc).isoformat()
            alert["endsAt"] = (now + timedelta(minutes=10)).isoformat()
        request(f"{base}/api/v2/alerts", burns)
        wait_count(7)
        titles = [item["attachments"][0]["title"] for item in captures[-2:]]
        check(any("/ api (2 firing" in title for title in titles),
              "Fast/slow burns for one DevFeed service must share a group")
        check(any("/ admin-api (1 firing" in title for title in titles),
              "Different DevFeed services must remain separate groups")
        print("PASS: same-service DevFeed burns correlate while different services stay separate", flush=True)
        # Retained effective inhibit_rules must also leave these evidence-loss
        # alerts active beside a critical incident in the same namespace.
        evidence = []
        for alertname, namespace in (
            ("OpenTelemetryPrometheusExportFailures", "cattle-monitoring-system"),
            ("OpenTelemetryTempoExportFailures", "cattle-monitoring-system"),
            ("OpenTelemetryGatewayExportFailures", "cattle-monitoring-system"),
            ("HubbleEventsLost", "kube-system"),
            ("FixtureRelatedCritical", "cattle-monitoring-system"),
            ("FixtureRelatedCritical", "kube-system"),
        ):
            evidence.append({
                "labels": {"alertname": alertname, "namespace": namespace,
                           "cluster": "home-lab", "severity": "critical" if alertname.startswith("Fixture") else "warning"},
                "annotations": {"summary": "Synthetic evidence coverage fixture"},
                "startsAt": datetime.now(timezone.utc).isoformat(),
                "endsAt": (now + timedelta(minutes=10)).isoformat(),
            })
        request(f"{base}/api/v2/alerts", evidence)
        time.sleep(1)
        states = json.loads(request(f"{base}/api/v2/alerts"))
        for fixture in evidence:
            state = next(alert for alert in states if alert["labels"] == fixture["labels"])
            check(not state["status"]["inhibitedBy"], "Related critical alert inhibits evidence loss")
        print("PASS: OTel final-send failures and Hubble event loss remain uninhibited beside critical failures", flush=True)
    except Exception:
        print(json.dumps(captures, indent=2), flush=True)
        print(request(f"{base}/api/v2/alerts/groups").decode(), flush=True)
        print(docker("logs", name, check=False), flush=True)
        raise
    finally:
        docker("rm", "--force", "--volumes", name, check=False)
        server.shutdown()
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--effective-config", type=Path, help="Private operator-generated alertmanager YAML (never sent to Slack)")
    args = parser.parse_args()
    config, receiver = configuration(args.effective_config)
    docker("pull", IMAGE, timeout=300)
    with tempfile.TemporaryDirectory(prefix="alertmanager-validation-") as directory:
        temp = Path(directory)
        (temp / "alertmanager.yaml").write_text(yaml.safe_dump(config))
        print(amtool(temp, "check-config", "/fixtures/alertmanager.yaml"), flush=True)
        cases = [
            (["alertname=AlloyLogEntriesDropped", "incident=log-delivery", "severity=warning", "cluster=home-lab"], receiver),
            (["alertname=LokiLogEntriesRejected", "incident=log-delivery", "severity=critical", "namespace=cattle-monitoring-system"], receiver),
            (["alertname=DevFeedAvailabilityFastBurn", "severity=critical", "namespace=devfeed"], receiver),
            (["alertname=Watchdog", "severity=none"], "null"),
            (["alertname=InfoInhibitor", "severity=none"], "null"),
        ]
        for labels, expected in cases:
            amtool(temp, "config", "routes", "test", "--config.file=/fixtures/alertmanager.yaml",
                   f"--verify.receivers={expected}", *labels)
        print("PASS: routing includes critical/loss alerts and excludes heartbeat/no-severity alerts", flush=True)
        validate_rendering(temp, config)
        validate_delivery(temp, config, receiver)
    print("Validated Alertmanager routes, bounded Slack messages and group timing without cluster or Slack writes", flush=True)


if __name__ == "__main__":
    main()
