#!/usr/bin/env python3
"""Collect bounded, private OS evidence over SSH even when Kubernetes is down."""

from __future__ import annotations

import argparse
import concurrent.futures
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time

import yaml


ROOT = Path(__file__).resolve().parents[1]


def inventory() -> dict[str, str]:
    source = ROOT / "infrastructure/ansible/inventories/home/hosts.yml"
    groups = yaml.safe_load(source.read_text())["all"]["children"]["k3s_nodes"]["children"]
    result = {}
    for group in ("k3s_servers", "k3s_workers"):
        for alias, host in groups[group]["hosts"].items():
            variables = source.parent / "host_vars" / f"{alias}.yml"
            hostname = yaml.safe_load(variables.read_text())["node_identity"]["hostname"]
            if hostname in result:
                raise ValueError(f"Duplicate inventory hostname: {hostname}")
            result[hostname] = host["ansible_host"]
    return result


def private_write(path: Path, value: object) -> None:
    with open(path, "w", opener=lambda name, flags: os.open(name, flags, 0o600)) as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")


def capture(host: str, command: list[str], target: Path, *, limit: int, timeout: int) -> dict:
    """Keep original bytes; truncate visibly and bound unavailable-host waits."""
    args = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o",
            "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2", host, shlex.join(command)]
    started = time.monotonic()
    truncated = False
    timed_out = False
    total = 0
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors)
        assert process.stdout is not None
        # SSH's keepalive bounds a dead connection. `timeout` on the remote side
        # also bounds a responsive host with a stuck journal/storage operation.
        with open(target, "wb", opener=lambda name, flags: os.open(name, flags, 0o600)) as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb") as compressed:
                while chunk := process.stdout.read(65536):
                    available = limit - total
                    compressed.write(chunk[:available])
                    total += min(len(chunk), available)
                    if len(chunk) > available:
                        truncated = True
                        process.kill()
                        break
                    if time.monotonic() - started > timeout + 20:
                        timed_out = True
                        process.kill()
                        break
        try:
            code = process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            code = process.wait()
            timed_out = True
        errors.seek(0)
        error = errors.read(4096).decode(errors="replace")
    return {"command": command, "returncode": code, "bytes": total,
            "truncated": truncated, "timed_out": timed_out,
            "stderr": error, "file": target.name}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", action="append", choices=sorted(inventory()))
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--since", help="journalctl time, e.g. '2026-10-26 10:00:00 UTC'")
    window.add_argument("--boot", default=None, help="boot offset or ID; default current boot (0)")
    parser.add_argument("--until", help="optional journalctl end time")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-mib", type=int, default=256, help="per-command uncompressed cap")
    parser.add_argument("--timeout", type=int, default=120, help="per-command remote time limit")
    options = parser.parse_args()
    if not 1 <= options.max_mib <= 1024 or not 5 <= options.timeout <= 600:
        parser.error("max-mib must be 1..1024 and timeout 5..600")
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (options.output or Path(tempfile.gettempdir()) / f"os-incident-{now}").resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("evidence contains original private logs; choose a directory outside the repository")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(output, 0o700)
    hosts = inventory()
    journal = ["sudo", "-n", "timeout", str(options.timeout), "journalctl",
               "--no-pager", "--all", "--output=json"]
    if options.since:
        journal.append(f"--since={options.since}")
    else:
        journal.append(f"--boot={options.boot or '0'}")
    if options.until:
        journal.append(f"--until={options.until}")
    facts = ["sudo", "-n", "timeout", str(options.timeout), "sh", "-c", "\n".join([
        "date --utc --iso-8601=ns", "cat /proc/sys/kernel/random/boot_id", "uptime",
        "uname -a", "journalctl --list-boots --no-pager", "journalctl --disk-usage",
        "timedatectl show --property=NTP --property=NTPSynchronized --property=Timezone",
        "systemctl --failed --no-pager", "df -h", "df -i", "findmnt --real",
        "ip -s link", "ip route", "cat /proc/pressure/cpu", "cat /proc/pressure/io",
        "cat /proc/pressure/memory", "cat /proc/meminfo", "cat /proc/loadavg",
    ])]

    def collect(node: str) -> tuple[str, dict]:
        host = f"asaharan@{hosts[node]}"
        result = {}
        for name, command in (("journal", journal), ("host", facts)):
            suffix = "json" if name == "journal" else "txt"
            result[name] = capture(host, command, output / f"{node}-{name}.{suffix}.gz",
                                   limit=options.max_mib * 1024 * 1024, timeout=options.timeout)
        return node, result

    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    selected = options.node or sorted(hosts)
    report = {"captured_at_utc": now, "repository_revision": revision, "nodes": {},
              "limits": {"max_mib_per_command": options.max_mib, "timeout_seconds": options.timeout},
              "interpretation": "Original records, including monotonic/boot timestamps. Capture failures and truncation are evidence gaps. Correlation alone does not establish an initiating cause."}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for node, result in pool.map(collect, selected):
            report["nodes"][node] = result
            print(f"{node}: journal bytes={result['journal']['bytes']} "
                  f"status={result['journal']['returncode']} truncated={result['journal']['truncated']}")
    private_write(output / "manifest.json", report)
    print(f"Private evidence: {output}")
    if any(item["returncode"] or item["truncated"] or item["timed_out"]
           for result in report["nodes"].values() for item in result.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
