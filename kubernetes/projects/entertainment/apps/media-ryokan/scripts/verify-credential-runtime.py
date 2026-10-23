#!/usr/bin/env python3
"""Run the actual credential script in its pinned native image with synthetic tmpfs state."""
import json
from pathlib import Path
import platform
import re
import subprocess

APP = Path(__file__).resolve().parents[1]
METADATA = APP.parent / "media-state-backups/public-helper-image.json"
IMAGE = json.loads(METADATA.read_text())["image"]
if not re.fullmatch(r"cgr\.dev/chainguard/python:latest@sha256:[a-f0-9]{64}", IMAGE):
    raise SystemExit("Credential runtime must use the reviewed immutable public image")
host = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
if host is None:
    raise SystemExit("Unsupported native validation architecture")
# This read-only pull obtains only the reviewed digest, without passing credentials.
subprocess.run(["docker", "pull", "--quiet", IMAGE], check=True)
architecture = subprocess.check_output(
    ["docker", "image", "inspect", IMAGE, "--format", "{{.Architecture}}"], text=True
).strip()
if architecture != host:
    raise SystemExit("Refuse an emulated image as native runtime evidence")
command = [
    "docker", "run", "--rm", "--pull=never", "--network", "none", "--read-only",
    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "568:568",
    "--tmpfs", "/data:rw,nosuid,nodev,noexec,size=32m,uid=568,gid=568,mode=0700",
    "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=16m,uid=568,gid=568,mode=0700",
]
for source, target in [
    (APP / "deployment.yaml", "/fixture/deployment.yaml"),
    (APP / "tests/test_credential_sync.py", "/fixture/test_credential_sync.py"),
    (METADATA, "/fixture/public-helper-image.json"),
]:
    command += ["--mount", f"type=bind,source={source},target={target},readonly"]
command += [
    "--env", "CREDENTIAL_SYNC_MANIFEST=/fixture/deployment.yaml",
    "--env", "CREDENTIAL_SYNC_IMAGE_METADATA=/fixture/public-helper-image.json",
    "--env", "CREDENTIAL_SYNC_EXACT_TMPFS=1",
    "--entrypoint", "/usr/bin/python", IMAGE, "-B", "/fixture/test_credential_sync.py",
]
subprocess.run(command, check=True)
print(json.dumps({
    "status": "PASS", "architecture": architecture, "uid": 568, "gid": 568,
    "image": IMAGE, "root_readonly": True, "capabilities": "none",
    "network": "none", "production_state_mounted": False,
    "script_bytes_unchanged": True, "database": "new private Docker tmpfs",
}))
