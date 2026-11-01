#!/usr/bin/env python3
"""Exercise Fleet ClickHouse admission in isolated Docker containers, never a cluster.

Uses the pinned image/configuration and generated data/passwords. Defaults to a
native ARM64 requirement; --allow-other-architecture permits local smoke checks.
No production endpoint, credential, PVC or data is accepted.
"""

from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import platform
import re
import secrets
import statistics
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "kubernetes/projects/database/apps/clickhouse"


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True).strip()


class Database:
    def __init__(self, port: int, password: str):
        self.endpoint = f"http://127.0.0.1:{port}/"
        self.password = password

    def query(self, sql: str, user: str = "clickhouse_operator", **settings: object) -> str:
        url = self.endpoint + "?" + urllib.parse.urlencode(settings)
        request = urllib.request.Request(url, data=sql.encode())
        credential = base64.b64encode(f"{user}:{self.password}".encode()).decode()
        request.add_header("Authorization", f"Basic {credential}")
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.read().decode()


@contextmanager
def server(phase: str, image: str):
    deployment = yaml.safe_load((APP / "deployment-clickhouse.yaml").read_text())
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    config = yaml.safe_load((APP / "clickhouse-config.yaml").read_text())["data"]
    env = {item["name"]: item["value"] for item in container["env"] if "value" in item}
    password = secrets.token_urlsafe(24)
    env["CLICKHOUSE_PASSWORD"] = password
    for role in ("READER", "PUBLIC", "USER", "PARTNER", "ADMIN", "WORKER", "INGEST"):
        env[f"DEVFEED_CLICKHOUSE_{role}_PASSWORD"] = password
    # Preserve admission/memory bounds while scoping synthetic fixture grants to
    # the same disposable database. Actual table grants are checked separately.
    for key in env:
        if key.endswith("_GRANT"):
            env[key] = "GRANT SELECT, INSERT ON devfeed.*"
    cpus, memory = "3", "6g"
    if phase == "baseline":
        env.update({
            "DEVFEED_CLICKHOUSE_READER_MAX_QUERIES": "4",
            "DEVFEED_CLICKHOUSE_READER_MAX_MEMORY_BYTES": "536870912",
            "DEVFEED_CLICKHOUSE_INGEST_MAX_QUERIES": "3",
            "DEVFEED_CLICKHOUSE_INGEST_MAX_MEMORY_BYTES": "402653184",
            "DEVFEED_CLICKHOUSE_USER_MAX_QUERIES": "6",
            "DEVFEED_CLICKHOUSE_WORKER_MAX_QUERIES": "6",
            "DEVFEED_CLICKHOUSE_WORKER_MAX_MEMORY_BYTES": "402653184",
            "DEVFEED_CLICKHOUSE_SERVER_MAX_MEMORY_BYTES": "1610612736",
            "DEVFEED_CLICKHOUSE_SERVER_MAX_QUERIES": "12",
            "DEVFEED_CLICKHOUSE_SERVER_MAX_SELECTS": "8",
            "DEVFEED_CLICKHOUSE_SERVER_MAX_INSERTS": "4",
        })
        cpus, memory = "1", "2g"
    name = f"clickhouse-admission-{phase}-{secrets.token_hex(4)}"
    with tempfile.TemporaryDirectory(prefix="clickhouse-admission-") as tmp:
        directory = Path(tmp)
        for filename in ("resources.xml", "users.xml"):
            (directory / filename).write_text(config[filename])
        environment = directory / "environment"
        environment.write_text("".join(f"{key}={value}\n" for key, value in env.items()))
        environment.chmod(0o600)
        try:
            docker("run", "--detach", "--name", name, "--cpus", cpus, "--memory", memory,
                   "--memory-swap", memory, "--env-file", str(environment),
                   "--publish", "127.0.0.1::8123", "--volume",
                   f"{directory / 'resources.xml'}:/etc/clickhouse-server/config.d/bounds.xml:ro",
                   "--volume",
                   f"{directory / 'users.xml'}:/etc/clickhouse-server/users.d/profiles.xml:ro", image)
            port = int(docker("port", name, "8123/tcp").rsplit(":", 1)[1])
            database = Database(port, password)
            for _ in range(90):
                try:
                    database.query("SELECT 1")
                    break
                except Exception:
                    time.sleep(1)
            else:
                raise RuntimeError("Disposable ClickHouse did not become ready")
            yield database, name
        finally:
            subprocess.run(["docker", "rm", "--force", "--volumes", name],
                           check=False, stdout=subprocess.DEVNULL)


def seed(database: Database, rows: int) -> None:
    database.query("CREATE TABLE devfeed.events (domain LowCardinality(String), id UInt64, "
                   "revision UInt64, occurred_at DateTime64(3), status LowCardinality(String), "
                   "value UInt64, context String, topics Array(UInt32)) "
                   "ENGINE=ReplacingMergeTree(revision) ORDER BY (domain,id)")
    for domain in ("pipeline", "inference", "cards"):
        for offset in range(0, rows, 100_000):
            size = min(100_000, rows - offset)
            database.query(f"INSERT INTO devfeed.events SELECT '{domain}',number+{offset},1,now64(),"
                           f"if(number%2=0,'ready','pending'),number%100,repeat('context',40),"
                           f"[toUInt32(number%100)] FROM numbers({size})")


def effective_limits(database: Database, phase: str) -> dict:
    """Assert the server loaded the rendered profiles, rather than testing defaults."""
    names = "'max_threads','max_memory_usage','max_memory_usage_for_user'," \
            "'max_concurrent_queries_for_user','max_execution_time'"
    users = {}
    expected = {
        "clickhouse_operator": 8, "devfeed_reader": 8, "devfeed_public": 8,
        "devfeed_user": 16, "devfeed_partner": 8, "devfeed_admin": 8,
        "devfeed_worker": 64, "devfeed_ingest": 8,
    }
    if phase == "baseline":
        expected = {"clickhouse_operator": 4, "devfeed_reader": 4, "devfeed_public": 3,
                    "devfeed_user": 6, "devfeed_partner": 4, "devfeed_admin": 3,
                    "devfeed_worker": 6, "devfeed_ingest": 3}
    for user, cap in expected.items():
        rows = database.query(f"SELECT name,value FROM system.settings WHERE name IN ({names}) "
                              "FORMAT JSONEachRow", user)
        values = {row["name"]: row["value"] for row in map(json.loads, rows.splitlines())}
        if int(values["max_concurrent_queries_for_user"]) != cap:
            raise RuntimeError(f"Effective {user} admission does not match the rendered profile")
        if int(values["max_memory_usage"]) != 268435456 or int(values["max_threads"]) != 2:
            raise RuntimeError(f"Effective {user} per-query bounds changed unexpectedly")
        expected_memory = (2147483648 if user == "devfeed_worker" else 805306368)
        if phase == "baseline":
            expected_memory = (536870912 if user in
                               ("clickhouse_operator", "devfeed_reader", "devfeed_partner")
                               else 402653184)
        if int(values["max_memory_usage_for_user"]) != expected_memory:
            raise RuntimeError(f"Effective {user} aggregate memory does not match the profile")
        users[user] = values
    expected_server = {
        "max_server_memory_usage": 4831838208, "max_concurrent_queries": 128,
        "max_concurrent_select_queries": 64, "max_concurrent_insert_queries": 96,
    }
    if phase == "baseline":
        expected_server.update({"max_server_memory_usage": 1610612736,
                                "max_concurrent_queries": 12,
                                "max_concurrent_select_queries": 8,
                                "max_concurrent_insert_queries": 4})
    server_names = ",".join(f"'{name}'" for name in expected_server)
    rows = database.query("SELECT name,value FROM system.server_settings WHERE name IN "
                          f"({server_names}) FORMAT JSONEachRow")
    values = {row["name"]: row["value"] for row in map(json.loads, rows.splitlines())}
    if {key: int(value) for key, value in values.items()} != expected_server:
        raise RuntimeError("Effective global limits do not match the rendered server configuration")
    return {"server": values, "users": users}


def wave(database: Database, writers: dict[str, int], readers: int, rounds: int) -> dict:
    results = []
    # Every worker credential process may hold two driver slots. 30 steady
    # writers cover 15 pods; 60 burst writers add process replacement overlap.
    clients = [(user, False) for user, count in writers.items() for _ in range(count)]
    clients += [("devfeed_reader" if i % 2 else "devfeed_partner", True)
                for i in range(readers)]
    barrier = threading.Barrier(len(clients))
    started = time.monotonic()
    identity_base = time.time_ns()

    def client(index: int, user: str, read: bool):
        local = []
        barrier.wait(timeout=30)
        for iteration in range(rounds):
            start = time.monotonic()
            try:
                if read:
                    database.query("SELECT domain,status,count(),sum(value) FROM devfeed.events "
                                   "FINAL GROUP BY domain,status FORMAT JSONEachRow", user,
                                   max_threads=2, max_memory_usage=268435456, max_execution_time=20)
                else:
                    records = [json.dumps({
                        "domain": "inference" if index % 2 else "pipeline",
                        "id": identity_base + index * 100_000 + iteration * 100 + n,
                        "revision": 2, "occurred_at": "2026-10-31 00:00:00.000",
                        "status": "ready", "value": n, "context": "context" * 40,
                        "topics": [1, 2, 3],
                    }) for n in range(100)]
                    database.query("INSERT INTO devfeed.events FORMAT JSONEachRow\n" +
                                   "\n".join(records), user, async_insert=1,
                                   wait_for_async_insert=1, async_insert_busy_timeout_ms=1000,
                                   async_insert_use_adaptive_busy_timeout=0,
                                   max_threads=2, max_memory_usage=268435456,
                                   max_execution_time=20)
                local.append({"read": read, "seconds": time.monotonic() - start, "code": 0})
            except urllib.error.HTTPError as error:
                match = re.search(r"Code:\s*(\d+)", error.read().decode())
                local.append({"read": read, "seconds": time.monotonic() - start,
                              "code": int(match[1]) if match else error.code})
            except Exception as error:
                local.append({"read": read, "seconds": time.monotonic() - start,
                              "code": type(error).__name__})
        return local

    with ThreadPoolExecutor(max_workers=len(clients)) as pool:
        futures = [pool.submit(client, i, user, read)
                   for i, (user, read) in enumerate(clients)]
        for future in futures:
            results.extend(future.result())
    elapsed = time.monotonic() - started
    errors = {}
    for row in results:
        if row["code"]:
            key = str(row["code"])
            errors[key] = errors.get(key, 0) + 1
    def latency(read: bool):
        values = sorted(row["seconds"] for row in results if row["read"] == read and not row["code"])
        return {"count": len(values), "p50": statistics.median(values) if values else None,
                "p95": values[min(len(values) - 1, int(len(values) * .95))] if values else None}
    return {"concurrency": len(clients), "requests": len(results), "seconds": elapsed,
            "successful_requests_per_second": sum(not row["code"] for row in results) / elapsed,
            "errors": errors, "reads": latency(True), "writes": latency(False)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-other-architecture", action="store_true")
    parser.add_argument("--rows-per-domain", type=int, default=1_000_000)
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--phase", choices=("both", "baseline", "headroom"), default="both")
    parser.add_argument("--output", type=Path, default=Path("clickhouse-admission-results.json"))
    args = parser.parse_args()
    architecture = platform.machine()
    if architecture not in ("aarch64", "arm64") and not args.allow_other_architecture:
        parser.error("Native ARM64 is required; use --allow-other-architecture for a local smoke check")
    deployment = yaml.safe_load((APP / "deployment-clickhouse.yaml").read_text())
    pinned = deployment["spec"]["template"]["spec"]["containers"][0]["image"]
    image = pinned.removeprefix("registry.home/docker.io/")
    docker("pull", image)
    report = {"architecture": architecture, "image": image, "rows_per_domain": args.rows_per_domain,
              "container_cpus": {"baseline": 1, "headroom": 3}, "phases": {}}
    phases = ("baseline", "headroom") if args.phase == "both" else (args.phase,)
    for phase in phases:
        with server(phase, image) as (database, name):
            phase_started = time.monotonic()
            limits = effective_limits(database, phase)
            seed(database, args.rows_per_domain)
            baseline_count = int(database.query("SELECT count() FROM devfeed.events FINAL"))
            phase_report = {"effective_limits": limits}
            for label, writers, readers in [
                ("steady", {"devfeed_worker": 30, "devfeed_public": 4, "devfeed_user": 4,
                            "devfeed_admin": 4, "devfeed_ingest": 1}, 8),
                ("burst", {"devfeed_worker": 60, "devfeed_public": 4, "devfeed_user": 8,
                           "devfeed_admin": 4, "devfeed_ingest": 4}, 8),
            ]:
                result = wave(database, writers, readers, args.rounds)
                phase_report[label] = result
                print(json.dumps({"phase": phase, "wave": label, **result}), flush=True)
            overload = wave(database, {"devfeed_worker": 80}, 8, 2)
            phase_report["overload"] = overload
            print(json.dumps({"phase": phase, "wave": "overload", **overload}), flush=True)
            if not overload["errors"].get("202"):
                raise RuntimeError("Admission bound was not enforced above the worker limit")
            # Overload must remain recoverable without restarting the container.
            if database.query("SELECT 1").strip() != "1":
                raise RuntimeError("Server did not recover from deliberate admission overload")
            state = json.loads(docker("inspect", name))[0]["State"]
            memory = database.query("SELECT max(value) FROM system.asynchronous_metrics "
                                    "WHERE metric='MemoryResident'")
            peak = int(docker("exec", name, "cat", "/sys/fs/cgroup/memory.peak"))
            cpu = dict(line.split() for line in
                       docker("exec", name, "cat", "/sys/fs/cgroup/cpu.stat").splitlines())
            final_count = int(database.query("SELECT count() FROM devfeed.events FINAL"))
            expected_rows = baseline_count + 100 * sum(
                phase_report[label]["writes"]["count"] for label in ("steady", "burst", "overload")
            )
            phase_report.update({"resident_bytes_after_waves": int(float(memory)),
                                 "container_peak_bytes": peak,
                                 "average_cpu_cores": int(cpu["usage_usec"]) / 1_000_000 /
                                     (time.monotonic() - phase_started),
                                 "throttled_period_fraction": int(cpu["nr_throttled"]) /
                                     max(1, int(cpu["nr_periods"])),
                                 "oom_killed": state["OOMKilled"], "rows": final_count,
                                 "expected_rows": expected_rows, "seed_rows": baseline_count})
            if phase == "headroom" and final_count != expected_rows:
                raise RuntimeError("Acknowledged writes do not match retained rows")
            report["phases"][phase] = phase_report
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    headroom = report["phases"].get("headroom")
    if headroom:
        if any(headroom[wave_name]["errors"] for wave_name in ("steady", "burst")):
            raise SystemExit("Proposed headroom failed concurrent traffic")
        if headroom["oom_killed"] or headroom["container_peak_bytes"] >= 6 * 1024**3:
            raise SystemExit("Proposed headroom exceeded container memory")
    baseline = report["phases"].get("baseline")
    if baseline and not baseline["burst"]["errors"].get("202"):
        raise SystemExit("Baseline did not reproduce admission rejection")


if __name__ == "__main__":
    main()
