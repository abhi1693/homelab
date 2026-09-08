#!/usr/bin/env python3
"""Restore a completed temporary S3 backup to a new isolated file on server-1.

Requires a task-owned server-1 localhost:19000 port-forward to MinIO. Credentials
are passed over SSH stdin, never in command arguments or persisted to disk.
"""

import argparse
import base64
import json
import subprocess


def resource(kind, name):
    return json.loads(subprocess.check_output(
        ["kubectl", "-n", "longhorn-system", "get", kind, name, "-o", "json"], text=True))


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("backup")
args = parser.parse_args()
backup = resource("backups.longhorn.io", args.backup)
assert backup["status"]["state"] == "Completed"
url = backup["status"]["url"]
assert url.startswith("s3://longhorn@us-east-1/")
secret = resource("secret", "longhorn-backup-minio")["data"]
environment = {key: base64.b64decode(secret[key]).decode()
               for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")}
environment["AWS_ENDPOINTS"] = "http://127.0.0.1:19000"
remote = '''
import json, os, pathlib, subprocess, sys, tempfile
request = json.load(sys.stdin)
environment = os.environ.copy()
environment.update(request["environment"])
directory = pathlib.Path(tempfile.mkdtemp(prefix="longhorn-minio-restore-", dir="/var/tmp"))
image = directory / "restored.raw"
binary = "/var/lib/longhorn/engine-binaries/docker.io-rancher-mirrored-longhornio-longhorn-engine-v1.12.1/longhorn"
subprocess.run([binary, "backup", "restore-to-file", "--output-file", str(image),
                "--output-format", "raw", request["url"]], cwd=directory, env=environment, check=True)
# Crash-consistent snapshots may require journal replay. Modify only the newly
# restored isolated image, never the backup objects or production filesystem.
replay = subprocess.run(["e2fsck", "-p", str(image)])
if replay.returncode not in (0, 1):
    raise RuntimeError("Isolated filesystem recovery needs operator inspection")
subprocess.run(["e2fsck", "-fn", str(image)], check=True)
print(json.dumps({"restored_file": str(image), "logical_bytes": image.stat().st_size,
                  "filesystem_check": "passed", "source_unchanged": True}))
'''
subprocess.run(["ssh", "asaharan@192.168.3.243", "sudo", "python3", "-c",
                "'" + remote.replace("'", "'\"'\"'") + "'"],
               input=json.dumps({"environment": environment, "url": url}), text=True, check=True)
