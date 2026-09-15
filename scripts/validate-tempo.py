#!/usr/bin/env python3
"""Validate the deployed Tempo image/config and round-trip a trace in local Docker."""

import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid

import yaml


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "kubernetes/projects/system/apps/tempo"


def docker(*args, check=True, timeout=60):
    result = subprocess.run(
        ["docker", *args], check=check, capture_output=True, text=True, timeout=timeout
    )
    return (result.stdout if check else result.stdout + result.stderr).strip()


def request(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.read()


def wait_for(name, check, description, timeout=120):
    deadline = time.monotonic() + timeout
    last_error = "condition not yet met"
    while time.monotonic() < deadline:
        state = json.loads(docker("inspect", "--format", "{{json .State}}", name))
        if not state["Running"]:
            raise RuntimeError(f"Tempo exited during {description}: {state}")
        try:
            if check():
                print(f"PASS: {description}", flush=True)
                return
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {description}: {last_error}")


def main():
    deployment = yaml.safe_load((APP / "deployment.yaml").read_text())
    pod = deployment["spec"]["template"]["spec"]
    container = next(c for c in pod["containers"] if c["name"] == "tempo")
    config = yaml.safe_load((APP / "configmap.yaml").read_text())["data"]["tempo.yaml"]
    image = container["image"]
    name = f"tempo-validation-{uuid.uuid4().hex[:12]}"
    user = container["securityContext"]["runAsUser"]
    group = container["securityContext"]["runAsGroup"]
    memory = container["resources"]["limits"]["memory"].replace("Mi", "m").replace("Gi", "g")
    print(f"Validating {image}", flush=True)
    docker("pull", image, timeout=300)

    with tempfile.TemporaryDirectory(prefix="tempo-validation-") as directory:
        config_path = Path(directory) / "tempo.yaml"
        config_path.write_text(config)
        config_path.chmod(0o644)
        options = [
            "--user", f"{user}:{group}",
            "--memory", memory,
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--mount", f"type=bind,source={config_path},target=/etc/tempo/tempo.yaml,readonly",
        ]
        for env in container.get("env", []):
            options.extend(["--env", f"{env['name']}={env['value']}"])
        # Startup validates the exact config. -config.verify also fails on the
        # intentional warning for this deployment's enabled MCP endpoint.
        try:
            docker(
                "run", "--detach", "--name", name, *options,
                "--tmpfs", f"/var/tempo:rw,uid={user},gid={group},size=2g",
                "--publish", "127.0.0.1::3200",
                "--publish", "127.0.0.1::4318",
                image, *container["args"],
            )
            ports = json.loads(docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", name))
            http = f"http://127.0.0.1:{ports['3200/tcp'][0]['HostPort']}"
            otlp = f"http://127.0.0.1:{ports['4318/tcp'][0]['HostPort']}"
            wait_for(name, lambda: request(f"{http}/ready").strip() == b"ready", "readiness")

            trace_id = uuid.uuid4().hex
            span_id = uuid.uuid4().hex[:16]
            started = time.time_ns()
            payload = {"resourceSpans": [{
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "tempo-config-validation"}}]},
                "scopeSpans": [{"scope": {"name": "home-lab-validation"}, "spans": [{
                    "traceId": trace_id, "spanId": span_id,
                    "name": "tempo-config-round-trip", "kind": 2,
                    "startTimeUnixNano": str(started), "endTimeUnixNano": str(started + 1_000_000),
                    "status": {"code": 1},
                }]}],
            }]}
            response = json.loads(request(f"{otlp}/v1/traces", payload) or b"{}")
            if int(response.get("partialSuccess", {}).get("rejectedSpans", 0)):
                raise RuntimeError(f"OTLP rejected the validation span: {response}")
            print("PASS: OTLP accepted the validation span", flush=True)

            def trace_returned():
                trace = json.loads(request(f"{http}/api/traces/{trace_id}"))
                # Tempo JSON responses use batches/resourceSpans depending on API version.
                batches = trace.get("batches", trace.get("resourceSpans", []))
                return any(
                    span.get("name") == "tempo-config-round-trip"
                    for batch in batches
                    for scope in batch.get("scopeSpans", batch.get("instrumentationLibrarySpans", []))
                    for span in scope.get("spans", [])
                )

            wait_for(name, trace_returned, "trace-by-ID round trip")
            print("Tempo configuration and trace ingestion/query validation passed.", flush=True)
        except BaseException:
            print(docker("logs", "--tail", "100", name, check=False), flush=True)
            raise
        finally:
            docker("rm", "--force", name, check=False)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stdout or "", end="")
        print(error.stderr or "", end="")
        raise SystemExit(error.returncode) from error
