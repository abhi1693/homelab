#!/usr/bin/env python3
"""Scoped RQ drain controller. Fleet gates and image/schema rollout remain external."""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from redis.exceptions import ConnectionError as RedisConnectionError
from maintenance_candidate import (
    PAUSE,
    acquire_pause,
    namespace,
    publish_warm_once,
    resume_owned,
    solver_bridge_class,
)

FIELDS = ("hostname", "birth", "last_heartbeat", "state", "current_job", "queues", "death")
SCANNED_KEYS = set()
PRODUCTION_ROLES = Counter(
    {
        "article-analysis": 3,
        **{
            role: 1
            for role in (
                "ai",
                "article-enrichment",
                "images",
                "ingestion",
                "notification",
                "relationships",
                "research-verification",
                "solver",
                "source-analysis",
                "source-discovery",
                "source-enrichment",
                "topic-analysis",
            )
        },
    }
)


class GateError(Exception):
    pass


def require(value, message):
    if not value:
        raise GateError(message)


def connect(args):
    if args.fixture_socket:
        root, socket = args.fixture_root.resolve(), args.fixture_socket.resolve()
        require(
            root in socket.parents and (root / ".devfeed-disposable-fixture").is_file(),
            "Fixture requires marked private Unix socket root",
        )
        connection = Redis(
            unix_socket_path=str(socket),
            db=15,
            socket_timeout=3,
            retry=Retry(NoBackoff(), retries=0),
        )
    else:
        from devfeed_core.config import get_settings
        from devfeed_core.redis import create_redis

        connection = create_redis(
            get_settings(),
            socket_connect_timeout=3,
            socket_timeout=3,
            retry=Retry(NoBackoff(), retries=0),
        )
        require(
            connection.connection_pool.connection_kwargs.get("db") == 10,
            "Production maintenance requires logical Redis DB10",
        )
    return connection


def runtime_guard(args, mode):
    expected = ("0.1.2", "0034") if mode == "resume" else ("0.1.1", "0033")
    if args.fixture_socket:
        # Explicit test injection: Redis-only fixtures do not prove PostgreSQL schema.
        context = json.loads(args.fixture_context.read_text())
        args.fixture_flags = context.get("faults", {})
        actual = context["runtime"], context["schema"]
    else:
        from devfeed_core.version import __version__

        if mode == "drain":
            from devfeed_core.config import get_settings

            solver_settings(get_settings())
        from devfeed_core.db import session_factory
        from sqlalchemy import text

        with session_factory()() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            revision = session.scalar(text("SELECT version_num FROM alembic_version"))
        actual = __version__, revision
    require(actual == expected, "Runtime/schema do not match the selected maintenance phase")
    return {
        "runtime": actual[0],
        "schema": actual[1],
        "sql_guard_injected": bool(args.fixture_socket),
    }


def solver_settings(settings):
    require(
        settings.solver_queue_enabled
        and settings.solver_services
        and 5 <= settings.solver_timeout_seconds <= 60
        and not settings.database_pool_enabled,
        "Solver bridge requires enabled bounded solver configuration and NullPool",
    )


def write_private(path, value, exclusive=False):
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC), 0o600
    )
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")


def raw_workers(connection, scan=False):
    registered = {key.decode() for key in connection.smembers("rq:workers")}
    if scan:
        cursor, count, until = 0, 0, time.monotonic() + 5
        while True:
            cursor, found = connection.scan(cursor, match="rq:worker:*", count=10000)
            SCANNED_KEYS.update(key.decode() for key in found)
            count += 1
            require(
                count <= 500 and time.monotonic() <= until and len(SCANNED_KEYS) <= 200,
                "Full worker SCAN exceeded its bounded budget",
            )
            if cursor == 0:
                break
    for _ in range(3):
        keys = sorted(set(registered) | SCANNED_KEYS)
        require(len(keys) <= 200, "Worker snapshot exceeds the bounded scope")
        # RQ birth/death changes registration and identity in one transaction.
        # Read membership with the hashes, rather than pairing old membership
        # with a newer death hash. Retry only when a new key needs enumeration.
        pipeline = connection.pipeline(transaction=True)
        pipeline.smembers("rq:workers")
        for key in keys:
            pipeline.hmget(key, FIELDS)
        members, *values = pipeline.execute()
        registered = {key.decode() for key in members}
        if registered - set(keys):
            continue
        rows = {
            key: {name: value.decode() if value else "" for name, value in zip(FIELDS, row)}
            for key, row in zip(keys, values)
        }
        return registered, rows
    raise GateError("Worker membership changed beyond the bounded snapshot retries")


def fresh(row, now):
    if not row["last_heartbeat"]:
        return False
    stamp = datetime.fromisoformat(row["last_heartbeat"].replace("Z", "+00:00")).timestamp()
    return -5 <= now - stamp <= 120


def inspect_scope(
    connection, scope, allowed_bridge=None, original_keys=(), scan=False, maintenance_owner=None
):
    registered, rows = raw_workers(connection, scan=scan)
    allowed_hosts = {item["hostname"]: item for item in scope["workers"]}
    markers = set(scope["historical_markers"])
    now = connection.time()[0]
    for key, row in rows.items():
        if not any(row.values()) and key not in registered and not connection.exists(key):
            continue
        shutdown_only = key not in registered and set(connection.hkeys(key)) == {
            b"shutdown_requested_date"
        }
        if key in markers or (key in original_keys and shutdown_only):
            require(shutdown_only, "A historical shutdown-only marker changed shape or registered")
            continue
        require(
            key == allowed_bridge or key in markers or row["hostname"] in allowed_hosts,
            "A registered or scanned worker is outside the approved scope",
        )
    queues = {value.decode() for value in connection.smembers("rq:queues")}
    approved_queues = set(scope["canonical_queues"]) | set(scope["empty_legacy_queues"])
    require(queues <= approved_queues, "Redis contains an unapproved RQ queue")
    for queue in scope["empty_legacy_queues"]:
        name = queue.removeprefix("rq:queue:")
        require(
            connection.llen(queue) == 0
            and connection.llen(queue + ":intermediate") == 0
            and connection.zcard("rq:wip:" + name) == 0
            and connection.scard("rq:workers:" + name) == 0,
            "Approved legacy queue is not empty and unsubscribed",
        )
    live = {}
    for key in registered:
        row = rows[key]
        if key in markers or key == allowed_bridge:
            continue
        require(
            row["birth"] and not row["death"] and fresh(row, now),
            "A registered scoped worker is not fresh",
        )
        pending_startup = (
            maintenance_owner
            and original_keys
            and key not in original_keys
            and row["birth"] not in original_keys.values()
            and row["state"] in {"", "started"}
            and not row["current_job"]
            and connection.get(PAUSE) == maintenance_owner.encode()
        )
        require(
            row["state"] in {"busy", "idle", "suspended"} or pending_startup,
            "A scoped worker has an unexpected runtime state",
        )
        host = row["hostname"]
        require(host not in live, "Multiple current workers share an approved Pod hostname")
        require(
            row["queues"].split(",") == allowed_hosts[host]["queues"],
            "Worker queue mapping differs from approved scope",
        )
        live[host] = (key, row)
    return registered, rows, live


def read_scope(args):
    raw = args.scope.read_bytes()
    scope = json.loads(raw)
    require(
        set(scope)
        == {
            "schema_version",
            "workers",
            "historical_markers",
            "canonical_queues",
            "empty_legacy_queues",
        }
        and scope["schema_version"] == 1,
        "Invalid approved scope schema",
    )
    require(
        len(scope["workers"]) == (3 if args.fixture_socket else 15),
        "Approved scope has the wrong Pod count",
    )
    require(
        len({item["hostname"] for item in scope["workers"]}) == len(scope["workers"]),
        "Approved Pod hostnames are duplicated",
    )
    require(
        len(scope["historical_markers"]) == (0 if args.fixture_socket else 4),
        "Historical marker scope differs",
    )
    require(
        sum(item["role"] == "solver" for item in scope["workers"]) == 1,
        "Exactly one original solver role is required",
    )
    if not args.fixture_socket:
        from devfeed_core.worker_queues import QUEUES, worker_queues

        require(
            set(scope["canonical_queues"]) == {"rq:queue:" + value for value in QUEUES},
            "Canonical production queue inventory differs",
        )
        require(
            scope["empty_legacy_queues"] == ["rq:queue:analysis"],
            "Approved empty legacy queue inventory differs",
        )
        require(
            Counter(item["role"] for item in scope["workers"]) == PRODUCTION_ROLES,
            "Approved production role counts differ",
        )
        for item in scope["workers"]:
            cli = {"ai": "analysis", "notification": "notifications"}.get(
                item["role"], item["role"]
            )
            require(
                item["queues"] == worker_queues(cli, ai_enabled=True, notifications_enabled=True),
                "Approved role queue mapping differs from source",
            )
    return scope, hashlib.sha256(raw).hexdigest()


def owned(connection, owner, minimum_ms):
    value, ttl = connection.get(PAUSE), connection.pttl(PAUSE)
    require(
        value == owner.encode() and ttl >= minimum_ms,
        "Owned pause is absent, changed, or has insufficient remaining TTL",
    )


def solver_envelope(connection, rows):
    ids = set()
    for key in ("rq:queue:solver", "rq:queue:solver:intermediate"):
        require(
            connection.llen(key) <= 1000, "Solver inventory exceeds the bounded admission check"
        )
        ids.update(value.decode() for value in connection.lrange(key, 0, -1))
    for row in rows.values():
        if row["current_job"] and row["queues"] == "solver":
            ids.add(row["current_job"])
    for identifier in ids:
        timeout = connection.hget("rq:job:" + identifier, "timeout")
        require(
            timeout and timeout.lstrip(b"+").isdigit() and 0 < int(timeout) <= 240,
            "Solver delivery exceeds the verified positive240s timeout envelope",
        )


def durable_state(connection, args, scope_hash):
    state = json.loads(connection.get(namespace(args.owner) + ":state"))
    bridge_key = "rq:worker:maintenance-" + namespace(args.owner).rsplit(":", 1)[1][:24]
    require(
        state["owner"] == args.owner
        and state["scope_sha256"] == scope_hash
        and state["bridge_key"] == bridge_key
        and state["solver_key"] in state["originals"]
        and all(
            key.startswith("rq:worker:") and birth for key, birth in state["originals"].items()
        ),
        "Owned durable state identity or frozen scope differs",
    )
    return state


def bridge_command(args):
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "bridge",
        "--owner",
        args.owner,
        "--scope",
        str(args.scope),
        "--state",
        str(args.state),
        "--output",
        str(args.output),
        "--bridge-lifetime",
        str(args.bridge_lifetime),
        "--handoff-timeout",
        str(args.handoff_timeout),
        "--minimum-remaining",
        str(args.minimum_remaining),
    ]
    if args.fixture_socket:
        command += [
            "--fixture-root",
            str(args.fixture_root),
            "--fixture-socket",
            str(args.fixture_socket),
            "--fixture-context",
            str(args.fixture_context),
        ]
    return command


def run_bridge(args, connection, state):
    from devfeed_aggregator.analysis_worker import AnalysisAwareWorker
    from rq import Queue
    from rq.serializers import JSONSerializer

    if not args.fixture_socket:
        from devfeed_core.config import get_settings

        solver_settings(get_settings())
    own, prefix = state["owner"], namespace(state["owner"])
    connection.set(prefix + ":prewarmed", own, ex=60)
    until = time.monotonic() + args.handoff_timeout
    while connection.get(PAUSE) != own.encode():
        require(
            time.monotonic() < until and connection.get(prefix + ":stop") != own.encode(),
            "Prewarmed bridge aborted before owned pause",
        )
        time.sleep(0.05)
    worker_type = solver_bridge_class(AnalysisAwareWorker)
    options = (
        {"worker_ttl": 18, "job_monitoring_interval": 1}
        if args.fixture_socket
        else {"worker_ttl": 90}
    )
    worker = worker_type(
        [Queue("solver", connection=connection, serializer=JSONSerializer)],
        connection=connection,
        serializer=JSONSerializer,
        name=state["bridge_key"].removeprefix("rq:worker:"),
        log_job_description=False,
        maintenance_owner=own,
        handoff_key=prefix + ":handoff",
        stop_key=prefix + ":stop",
        original_solver_key=state["solver_key"],
        lifetime=args.bridge_lifetime,
        handoff_timeout=args.handoff_timeout,
        min_remaining_ms=args.minimum_remaining * 1000,
        **options,
    )
    try:
        worker.work(logging_level="CRITICAL")
    finally:
        try:
            successful, failed = connection.hmget(
                worker.key, "successful_job_count", "failed_job_count"
            )
            connection.set(
                prefix + ":bridge-result",
                json.dumps(
                    {
                        "successful_job_count": int(successful or 0),
                        "failed_job_count": int(failed or 0),
                    }
                ),
                ex=14400,
            )
        finally:
            worker.close_maintenance_lease()


def drain(args, connection, scope, scope_hash, interrupted):
    registered, rows, live = inspect_scope(connection, scope, scan=True)
    require(
        len(live) == len(scope["workers"]), "Not every approved Pod has one fresh original worker"
    )
    solver_envelope(connection, rows)
    originals = {key: row["birth"] for key, row in live.values()}
    solver_host = next(item["hostname"] for item in scope["workers"] if item["role"] == "solver")
    solver_key = live[solver_host][0]
    executions = [
        "rq:execution:" + value.decode() for value in connection.zrange("rq:wip:solver", 0, -1)
    ]
    owner = args.owner
    prefix = namespace(owner)
    state = {
        "owner": owner,
        "scope_sha256": scope_hash,
        "originals": originals,
        "solver_key": solver_key,
        "bridge_key": "rq:worker:maintenance-" + prefix.rsplit(":", 1)[1][:24],
    }
    write_private(args.state, state, exclusive=True)
    require(
        connection.set(prefix + ":state", json.dumps(state), nx=True, ex=args.ttl + 600),
        "Owned durable state already exists; do not repeat a drain owner",
    )
    child = subprocess.Popen(
        bridge_command(args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    child_started = time.monotonic()
    deadline = time.monotonic() + args.deadline
    try:
        while connection.get(prefix + ":prewarmed") != owner.encode():
            require(
                not interrupted.is_set() and child.poll() is None and time.monotonic() < deadline,
                "Bridge failed to prewarm",
            )
            time.sleep(0.1)
        require(
            acquire_pause(
                connection,
                owner,
                args.ttl,
                {key: birth for key, birth in originals.items()},
                scope["canonical_queues"] + scope["empty_legacy_queues"],
                scope["empty_legacy_queues"],
                scope["historical_markers"],
                None if args.fixture_socket else solver_key,
            )
            == 1,
            "Owned scoped suspension could not be acquired",
        )
        # Close the already-blocked solver race first; no repeat publications.
        for key in [solver_key, *(key for key in originals if key != solver_key)]:
            birth = originals[key]
            require(
                publish_warm_once(connection, owner, key, birth) == 1,
                "Official warm publish attempt was refused",
            )
        granted = False
        while True:
            require(
                not interrupted.is_set() and time.monotonic() < deadline,
                "Drain interrupted or exceeded bounded deadline",
            )
            owned(connection, owner, args.minimum_remaining * 1000)
            require(
                child.poll() is None, "Bridge exited before the controller declared solver drain"
            )
            registered, rows, current = inspect_scope(
                connection, scope, state["bridge_key"], originals, maintenance_owner=owner
            )
            replacements = {
                host: (key, row)
                for host, (key, row) in current.items()
                if key not in originals and row["birth"] not in originals.values()
            }
            replacement_solver = replacements.get(solver_host)
            if (
                not granted
                and solver_key not in registered
                and not rows.get(solver_key, {}).get("current_job")
                and (not executions or not connection.exists(*executions))
                and connection.zcard("rq:wip:solver") == 0
                and connection.llen("rq:queue:solver:intermediate") == 0
                and replacement_solver
                and replacement_solver[1]["state"] == "suspended"
            ):
                solver_envelope(connection, rows)
                connection.set(prefix + ":handoff", owner, ex=args.ttl)
                granted = True
            replacements_ready = len(replacements) == len(scope["workers"]) and all(
                row["state"] == "suspended" and not row["current_job"]
                for _, row in replacements.values()
            )
            originals_gone = all(
                key not in registered and not rows.get(key, {}).get("current_job")
                for key in originals
            )
            intermediate = sum(
                connection.llen(queue + ":intermediate") for queue in scope["canonical_queues"]
            )
            bridge_idle = not connection.hget(state["bridge_key"], "current_job")
            if (
                args.fixture_socket
                and granted
                and not bridge_idle
                and args.fixture_flags.get("abort_when_bridge_active")
                and connection.exists(args.fixture_flags["active_bridge_marker"])
            ):
                raise GateError("Injected controller failure while bridge job remains active")
            wip = sum(
                connection.zcard("rq:wip:" + queue.removeprefix("rq:queue:"))
                for queue in scope["canonical_queues"]
            )
            if (
                granted
                and replacements_ready
                and originals_gone
                and not intermediate
                and not wip
                and bridge_idle
                and connection.llen("rq:queue:solver") == 0
            ):
                if args.fixture_socket and args.fixture_flags.get("hold_final"):
                    connection.set("fixture:final-gate-ready", 1)
                    if not connection.exists("fixture:allow-final"):
                        time.sleep(0.05)
                        continue
                connection.set(prefix + ":stop", owner, ex=600)
                child.wait(timeout=args.minimum_remaining)
                require(
                    child.returncode == 0 and not connection.exists(prefix + ":solver-bridge"),
                    "Bridge failed to exit cleanly after solver drain",
                )
                args.bridge_summary = json.loads(connection.get(prefix + ":bridge-result"))
                require(
                    args.bridge_summary["failed_job_count"] == 0,
                    "Bridge recorded an RQ execution failure; cutover is refused",
                )
                # Recheck after actual child exit; no queued non-solver work is deleted.
                owned(connection, owner, args.minimum_remaining * 1000)
                _, _, final = inspect_scope(
                    connection,
                    scope,
                    state["bridge_key"],
                    originals,
                    scan=True,
                    maintenance_owner=owner,
                )
                require(
                    len(final) == len(scope["workers"])
                    and all(
                        row["state"] == "suspended" and not row["current_job"]
                        for _, row in final.values()
                    ),
                    "Replacement suspension changed after bridge exit",
                )
                require(
                    connection.llen("rq:queue:solver") == 0
                    and all(
                        connection.llen(queue + ":intermediate") == 0
                        for queue in scope["canonical_queues"]
                    ),
                    "Solver or intermediate work reappeared",
                )
                require(
                    all(
                        connection.zcard("rq:wip:" + queue.removeprefix("rq:queue:")) == 0
                        for queue in scope["canonical_queues"]
                    ),
                    "WIP references remain after worker settlement",
                )
                return {
                    "original_scope_count": len(scope["workers"]),
                    "shutdown_marker_attempts": 0,
                    "official_publish_attempt_count": len(originals),
                    "replacement_suspended_count": len(final),
                    "solver_bridge_exited": True,
                    "owned_pause_retained": True,
                    "handoff_granted_after_solver_replacement": True,
                    "non_solver_backlogs_preserved": True,
                }
            time.sleep(0.1 if args.fixture_socket else 1)
    finally:
        # Never resume automatically, retry warm publication, or kill a child.
        try:
            for attempt in range(3):
                try:
                    if (
                        args.fixture_socket
                        and args.fixture_flags.get("fail_stop_once")
                        and attempt == 0
                    ):
                        args.stop_write_failures = 1
                        connection.set("fixture:stop-write-failed", 1)
                        raise RedisConnectionError("Injected fixture stop-marker failure")
                    connection.set(prefix + ":stop", owner, ex=600)
                    break
                except Exception:
                    if attempt < 2:
                        time.sleep(0.1 if args.fixture_socket else 1)
        finally:
            if child.poll() is None:
                try:
                    remaining = max(
                        1,
                        child_started
                        + args.bridge_lifetime
                        + args.minimum_remaining
                        - time.monotonic(),
                    )
                    child.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    raise GateError(
                        "Bridge child did not settle within the safe wait envelope; manual intervention required"
                    ) from None
            # This is the controller's actual Popen exit observation, not registry absence.
            connection.set(prefix + ":child-exit-observed", owner, ex=args.ttl + 600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("drain", "bridge", "resume", "abort-before-cutover"))
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ttl", type=int, default=7200)
    parser.add_argument("--deadline", type=int, default=3000)
    parser.add_argument("--bridge-lifetime", type=int, default=2400)
    parser.add_argument("--handoff-timeout", type=int, default=420)
    parser.add_argument("--minimum-remaining", type=int, default=420)
    parser.add_argument("--fixture-root", type=Path)
    parser.add_argument("--fixture-socket", type=Path)
    parser.add_argument("--fixture-context", type=Path)
    args = parser.parse_args()
    interrupted = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: interrupted.set())
    evidence = {"success": False, "mode": args.mode, "fixture_only": bool(args.fixture_socket)}
    connection = None
    try:
        require(
            bool(args.fixture_root) == bool(args.fixture_socket) == bool(args.fixture_context),
            "Fixture arguments must be supplied together",
        )
        require(
            re.fullmatch(r"[A-Za-z0-9_-]{16,128}", args.owner),
            "A reviewed unique maintenance owner is required",
        )
        require(
            args.fixture_socket
            or (
                args.minimum_remaining == 420
                and args.ttl in (7200, 14400)
                and args.bridge_lifetime == 2400
                and args.handoff_timeout == 420
                and args.deadline == 3000
            ),
            "Unsafe production timing parameters",
        )
        connection = connect(args)
        if args.mode == "bridge":
            _, scope_hash = read_scope(args)
            run_bridge(args, connection, durable_state(connection, args, scope_hash))
            return 0
        evidence["runtime_guard"] = runtime_guard(args, args.mode)
        scope, scope_hash = read_scope(args)
        evidence["scope_sha256"] = scope_hash
        if args.mode == "drain":
            evidence.update(drain(args, connection, scope, scope_hash, interrupted))
        else:
            state = durable_state(connection, args, scope_hash)
            prefix = namespace(state["owner"])
            require(
                connection.get(prefix + ":child-exit-observed") == args.owner.encode()
                and not connection.exists(prefix + ":solver-bridge")
                and not connection.sismember("rq:workers", state["bridge_key"]),
                "Solver bridge has not proved actual child settlement",
            )
            require(resume_owned(connection, state["owner"]), "Owner CAS resume was refused")
            evidence["owner_cas_resumed"] = True
        evidence["success"] = True
    except Exception as exc:
        evidence["error"] = (
            str(exc)
            if isinstance(exc, GateError)
            else "Maintenance operation failed (" + type(exc).__name__ + ")"
        )
    finally:
        if connection is not None:
            connection.close()
    if getattr(args, "stop_write_failures", 0):
        evidence["stop_write_failures"] = args.stop_write_failures
    if hasattr(args, "bridge_summary"):
        evidence["bridge_rq_counts"] = args.bridge_summary
    write_private(args.output, evidence)
    print(json.dumps(evidence, sort_keys=True), flush=True)
    return 0 if evidence["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
