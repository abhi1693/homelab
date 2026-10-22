#!/usr/bin/env python3
"""Ingest and query a profile, then prove v2 snapshot/WAL recovery in local Docker."""

import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import yaml


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "kubernetes/projects/system/apps/pyroscope"
CLEANUP_IMAGE = "docker.io/library/busybox:1.37.0"


def docker(*args, check=True, timeout=60):
    result = subprocess.run(
        ["docker", *args], check=check, capture_output=True, text=True, timeout=timeout
    )
    return (result.stdout if check else result.stdout + result.stderr).strip()


def request(url, payload=None, content_type="application/json"):
    data = payload
    if payload is not None and not isinstance(payload, bytes):
        data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": content_type, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read()


def wait_for(name, condition, description, timeout=150):
    deadline = time.monotonic() + timeout
    last_error = "condition not yet met"
    while time.monotonic() < deadline:
        state = json.loads(docker("inspect", "--format", "{{json .State}}", name))
        if not state["Running"]:
            raise RuntimeError(f"Pyroscope exited during {description}: {state}")
        try:
            if condition():
                print(f"PASS: {description}", flush=True)
                return
        except OSError as exc:
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {description}: {last_error}")


def main():
    deployment = yaml.safe_load((APP / "deployment.yaml").read_text())
    pod = deployment["spec"]["template"]["spec"]
    container = next(c for c in pod["containers"] if c["name"] == "pyroscope")
    data_mount = next(m for m in container["volumeMounts"] if m["name"] == "data")
    data_root = Path(data_mount["mountPath"])
    data_source = next(v for v in pod["volumes"] if v["name"] == "data")
    if "persistentVolumeClaim" not in data_source:
        raise RuntimeError("Pyroscope data must use a persistent volume claim")
    arguments = dict(arg.lstrip("-").split("=", 1) for arg in container["args"] if "=" in arg)
    durable_flags = (
        "storage.filesystem.dir", "metastore.data-dir",
        "metastore.raft.dir", "metastore.raft.snapshots-dir",
    )
    if not all(Path(arguments[flag]).is_relative_to(data_root) for flag in durable_flags):
        raise RuntimeError("Pyroscope blocks, metadata, Raft WAL and snapshots must share the data volume")
    image = container["image"]
    name = f"pyroscope-validation-{uuid.uuid4().hex[:12]}"
    user = container["securityContext"]["runAsUser"]
    group = container["securityContext"]["runAsGroup"]
    memory = container["resources"]["limits"]["memory"].replace("Mi", "m").replace("Gi", "g")
    print(f"Validating {image}", flush=True)
    docker("pull", image, timeout=300)
    docker("pull", CLEANUP_IMAGE, timeout=300)

    with tempfile.TemporaryDirectory(prefix="pyroscope-validation-") as directory:
        data = Path(directory) / "data"
        data.mkdir(mode=0o777)
        # The private parent remains 0700. The image's unprivileged UID needs to
        # write this disposable bind mount without requiring host root access.
        data.chmod(0o777)
        options = [
            "--user", f"{user}:{group}",
            "--memory", memory,
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--mount", f"type=bind,source={data},target={data_root}",
            "--publish", "127.0.0.1::4040",
        ]
        for env in container.get("env", []):
            options.extend(["--env", f"{env['name']}={env['value']}"])
        # Speed up a real snapshot and Raft log truncation only in this fixture.
        # Production keeps the upstream thresholds and snapshot schedule.
        fixture_args = [
            "-metastore.raft.snapshot-interval=1s",
            "-metastore.raft.snapshot-threshold=1",
            "-metastore.raft.trailing-logs=1",
        ]

        def start():
            docker("run", "--detach", "--name", name, *options, image, *container["args"], *fixture_args)
            ports = json.loads(docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", name))
            return f"http://127.0.0.1:{ports['4040/tcp'][0]['HostPort']}"

        try:
            http = start()
            original_hostname = docker("inspect", "--format", "{{.Config.Hostname}}", name)
            wait_for(name, lambda: request(f"{http}/ready").strip() == b"ready", "readiness")
            started = int(time.time()) - 2
            service = "pyroscope-persistence-validation"
            marker = f"persistence_probe_{uuid.uuid4().hex[:12]}"
            query = urllib.parse.urlencode({
                "name": service,
                "from": started,
                "until": started + 1,
                "format": "lines",
                "sampleRate": 100,
                "spyName": "gospy",
                "units": "samples",
            })
            request(f"{http}/ingest?{query}", f"main;{marker}\n".encode(), "text/plain")
            print("PASS: validation profile ingested", flush=True)
            window = {"start": started * 1000 - 1000, "end": started * 1000 + 5000}

            def profile_returned():
                response = json.loads(request(f"{http}/querier.v1.QuerierService/ProfileTypes", window))
                types = response.get("profileTypes", response.get("profile_types", []))
                for profile_type in types:
                    profile_id = profile_type.get("ID") or profile_type.get("id") or ":".join(
                        profile_type[key]
                        for key in ("name", "sampleType", "sampleUnit", "periodType", "periodUnit")
                    )
                    body = {
                        **window,
                        "profileTypeID": profile_id,
                        "labelSelector": f'{{service_name="{service}"}}',
                    }
                    result = json.loads(request(f"{http}/querier.v1.QuerierService/SelectMergeStacktraces", body))
                    flamegraph = result.get("flamegraph", {})
                    if marker in flamegraph.get("names", []) and int(flamegraph.get("total", 0)) > 0:
                        return True
                return False

            wait_for(name, profile_returned, "historical profile query before container replacement")
            snapshots = data / "v2/metastore/raft/snapshots"
            snapshot_after = time.time()

            def snapshot_and_truncation():
                complete = list(snapshots.glob("*/meta.json"))
                logs = docker("logs", name, check=False)
                return any(path.stat().st_mtime > snapshot_after for path in complete) and "compacting logs" in logs

            wait_for(name, snapshot_and_truncation, "Raft snapshot written and WAL logs compacted")
            docker("stop", "--time", str(pod.get("terminationGracePeriodSeconds", 120)), name, timeout=150)
            state = json.loads(docker("inspect", "--format", "{{json .State}}", name))
            if state["OOMKilled"] or state["ExitCode"] != 0:
                raise RuntimeError(f"Pyroscope did not stop cleanly: {state}")
            docker("rm", name)
            http = start()
            replacement_hostname = docker("inspect", "--format", "{{.Config.Hostname}}", name)
            if replacement_hostname == original_hostname:
                raise RuntimeError("Container replacement reused the previous runtime identity")
            print("PASS: replacement has a new container hostname", flush=True)
            wait_for(name, lambda: request(f"{http}/ready").strip() == b"ready", "readiness after container replacement")
            wait_for(name, profile_returned, "same historical profile query after container replacement")
            logs = docker("logs", name, check=False)
            if "restored from snapshot" not in logs:
                raise RuntimeError("Restart did not report restoring a Raft snapshot")
            print("PASS: startup restored a Raft snapshot", flush=True)
            print("Pyroscope profile and persistent snapshot/WAL recovery validation passed.", flush=True)
        except BaseException:
            print(docker("logs", "--tail", "100", name, check=False), flush=True)
            raise
        finally:
            docker("rm", "--force", name, check=False)
            # Files are owned by the deployed UID, which may differ from the
            # host user. Clean only the disposable mounted data, using Docker.
            docker(
                "run", "--rm", "--network", "none",
                "--mount", f"type=bind,source={data},target=/fixture",
                CLEANUP_IMAGE, "sh", "-c", "rm -rf /fixture/* /fixture/.[!.]* /fixture/..?*",
            )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stdout or "", end="")
        print(error.stderr or "", end="")
        raise SystemExit(error.returncode) from error
