#!/usr/bin/env python3
"""Validate Tempo ingestion and recovery after replacing its Docker container."""

import http.client
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
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as exc:
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
    volume = f"{name}-data"
    user = container["securityContext"]["runAsUser"]
    group = container["securityContext"]["runAsGroup"]
    memory = container["resources"]["limits"]["memory"].replace("Mi", "m").replace("Gi", "g")
    print(f"Validating {image}", flush=True)
    docker("pull", image, timeout=300)

    data_mount = next(m for m in container["volumeMounts"] if m["name"] == "data")
    data_root = Path(data_mount["mountPath"])
    data_source = next(v for v in pod["volumes"] if v["name"] == "data")
    if "persistentVolumeClaim" not in data_source:
        raise RuntimeError("Tempo data must use a persistent volume claim")
    settings = yaml.safe_load(config)
    durable_paths = [
        settings["live_store"]["wal"]["path"],
        settings["live_store"]["shutdown_marker_dir"],
        settings["metrics_generator"]["storage"]["path"],
        settings["storage"]["trace"]["local"]["path"],
    ]
    if not all(Path(path).is_relative_to(data_root) for path in durable_paths):
        raise RuntimeError("Tempo durable paths must be inside the data volume")

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

        def start():
            docker(
                "run", "--detach", "--name", name, *options,
                "--mount", f"type=volume,source={volume},target={data_root}",
                "--publish", "127.0.0.1::3200",
                "--publish", "127.0.0.1::4318",
                image, *container["args"],
            )
            ports = json.loads(docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", name))
            http = f"http://127.0.0.1:{ports['3200/tcp'][0]['HostPort']}"
            otlp = f"http://127.0.0.1:{ports['4318/tcp'][0]['HostPort']}"
            wait_for(name, lambda: request(f"{http}/ready").strip() == b"ready", "readiness")
            return http, otlp

        def replace():
            original_id = docker("inspect", "--format", "{{.Id}}", name)
            grace = pod.get("terminationGracePeriodSeconds", 30)
            docker("stop", "--time", str(grace), name, timeout=grace + 15)
            state = json.loads(docker("inspect", "--format", "{{json .State}}", name))
            if state["ExitCode"] != 0 or state["OOMKilled"]:
                raise RuntimeError(f"Tempo did not shut down cleanly: {state}")
            if "done cutting all instances to WAL" not in docker("logs", name, check=False):
                raise RuntimeError("Tempo did not flush live traces to its persistent WAL")
            print("PASS: graceful shutdown flushed live traces to WAL", flush=True)
            docker("rm", name)
            endpoints = start()
            if original_id == docker("inspect", "--format", "{{.Id}}", name):
                raise RuntimeError("Persistence validation must replace the original container")
            return endpoints

        # Startup validates the exact config. -config.verify also fails on the
        # intentional warning for this deployment's enabled MCP endpoint.
        try:
            # Docker initializes the volume from the image's UID/GID 10001 data
            # directory, matching the Kubernetes fsGroup-owned PVC mount.
            docker("volume", "create", volume)
            http, otlp = start()

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

            def trace_returned(mode="all"):
                trace = json.loads(request(f"{http}/api/traces/{trace_id}?mode={mode}"))
                # Tempo JSON responses use batches/resourceSpans depending on API version.
                batches = trace.get("batches", trace.get("resourceSpans", []))
                return any(
                    span.get("name") == "tempo-config-round-trip"
                    for batch in batches
                    for scope in batch.get("scopeSpans", batch.get("instrumentationLibrarySpans", []))
                    for span in scope.get("spans", [])
                )

            wait_for(name, trace_returned, "trace-by-ID round trip")
            http, otlp = replace()
            wait_for(name, trace_returned, "same trace ID recovered after container replacement")

            def block_flushed():
                metrics = request(f"{http}/metrics").decode()
                flushed = any(
                    float(line.split()[1]) > 0
                    for line in metrics.splitlines()
                    if line.startswith("tempo_live_store_local_blocks_flushed_total ")
                )
                # The previous container can also have flushed the block before
                # shutdown; startup polling makes it immediately queryable.
                return flushed or trace_returned("blocks")

            wait_for(name, block_flushed, "recovered WAL flushed to a completed backend block")
            http, otlp = replace()
            # Restrict this read to backend blocks, separately proving that
            # /var/tempo/blocks persists rather than only live-store WAL.
            wait_for(name, lambda: trace_returned("blocks"), "completed backend block survives another container replacement")
            print("Tempo configuration, trace delivery and persistent recovery validation passed.", flush=True)
        except BaseException:
            print(docker("logs", "--tail", "100", name, check=False), flush=True)
            raise
        finally:
            docker("rm", "--force", name, check=False)
            docker("volume", "rm", volume, check=False)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stdout or "", end="")
        print(error.stderr or "", end="")
        raise SystemExit(error.returncode) from error
