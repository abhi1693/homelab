#!/usr/bin/env python3
"""Portable actual-worker regression fixture; requires externally isolated empty Redis DB15."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import time
import threading
import uuid
from unittest.mock import patch
from types import SimpleNamespace

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from rq import Queue
from rq.serializers import JSONSerializer
from rq.command import send_shutdown_command
import rq
from maintenance_candidate import PAUSE, acquire_pause, namespace, publish_warm_once, resume_owned

parser = argparse.ArgumentParser()
parser.add_argument("--root", required=True, type=Path)
parser.add_argument("--socket", required=True, type=Path)
parser.add_argument(
    "--case",
    choices=("all", "dependency-budget", "worker-snapshot", "controller-fault"),
    default="all",
)
args = parser.parse_args()
root, socket_path = args.root.resolve(), args.socket.resolve()
source = Path(__file__).resolve().parent
if root not in socket_path.parents or not (root / ".devfeed-disposable-fixture").is_file():
    raise SystemExit("Disposable-root marker and Unix socket below --root are required")
if not stat.S_ISSOCK(socket_path.stat().st_mode):
    raise SystemExit("Fixture requires a Unix socket, never a network Redis URL")
connection = Redis(
    unix_socket_path=str(socket_path), db=15, socket_timeout=3, retry=Retry(NoBackoff(), retries=0)
)
if connection.dbsize() != 0 or rq.__version__ != "2.12.0":
    raise SystemExit("Fixture requires empty disposable DB15 and RQ2.12.0")
worker_base = Path(rq.__file__).parent / "worker/base.py"
if (
    hashlib.sha256(worker_base.read_bytes()).hexdigest()
    != "8606ed972b04e294cc92d4f1cd42d77c0b652c06548f8001ed6926c06622fc07"
):
    raise SystemExit("Actual RQ source does not match the pinned old backend")
run_dir = root / ("run-" + uuid.uuid4().hex[:8])
run_dir.mkdir(mode=0o700)
processes, owners, result = [], [], {}
controllers, worker_keys = [], []
active_case = "warm_bridge_handoff"
queues = ["rq:queue:producer", "rq:queue:solver", "rq:queue:foreign"]


class SelectedCaseComplete(Exception):
    pass


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def wait(predicate, seconds=12, *, condition=None):
    if condition is None:
        condition = f"{predicate.__code__.co_name}:{predicate.__code__.co_firstlineno}"
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(0.025)
    result["failure_boundary"] = {
        "case": active_case,
        "condition": condition,
        "deadline_seconds": seconds,
    }
    raise TimeoutError(f"Bounded fixture condition deadline exceeded: {active_case}/{condition}")


def owner():
    value = "fixture-" + uuid.uuid4().hex
    owners.append(value)
    return value


def worker(
    queue,
    jobs=2,
    bridge_owner=None,
    old_solver=None,
    executions=(),
    min_remaining_ms=3000,
    hostname=None,
    startup_gate=None,
):
    name = "fixture-" + uuid.uuid4().hex
    command = [
        sys.executable,
        str(source / "fixture_worker.py"),
        "--socket",
        str(socket_path),
        "--queue",
        queue,
        "--name",
        name,
        "--jobs",
        str(jobs),
    ]
    if bridge_owner:
        command.extend(["--owner", bridge_owner, "--min-remaining-ms", str(min_remaining_ms)])
        if old_solver:
            command.extend(["--original-solver", old_solver])
        for key in executions:
            command.extend(["--execution", key])
    if hostname:
        command.extend(["--hostname", hostname])
    if startup_gate:
        command.extend(["--startup-gate", startup_gate])
    # Deliberately do not inherit host app settings, credentials or telemetry endpoints.
    environment = {key: os.environ[key] for key in ("PATH", "LANG", "TZ") if key in os.environ}
    environment.update(
        {
            "PYTHONPATH": str(source),
            "PYTHONDONTWRITEBYTECODE": "1",
            "DEVFEED_DATABASE_URL": "postgresql+psycopg://fixture:fixture@127.0.0.1:1/maintenance_test",
            "DEVFEED_REDIS_URL": "unix://" + str(socket_path) + "?db=15",
            "DEVFEED_AI_ENABLED": "false",
            "DEVFEED_METRICS_ENABLED": "false",
            "DEVFEED_TELEMETRY_ENVIRONMENT": "test",
            "OTEL_SDK_DISABLED": "true",
        }
    )
    logfile = (run_dir / ("worker-" + str(len(processes)) + ".log")).open("wb")
    process = subprocess.Popen(
        command, cwd=root, env=environment, stdout=logfile, stderr=subprocess.STDOUT
    )
    key = "rq:worker:" + name
    processes.append((process, logfile))
    worker_keys.append(key)
    return process, key


def enqueue(queue, function, marker, *arguments):
    return Queue(queue, connection=connection, serializer=JSONSerializer).enqueue(
        "fixture_jobs." + function,
        str(socket_path),
        marker,
        *arguments,
        job_timeout=12,
        result_ttl=0,
        failure_ttl=30,
    )


def current(key):
    return connection.hget(key, "state")


def exited(process):
    check(process.wait(timeout=18) == 0, "Actual worker did not exit successfully")


def scope(keys):
    return {key: connection.hget(key, "birth") for key in keys}


def admission_regressions():
    from maintenance import GateError, solver_envelope, solver_settings

    approved = list(
        {value.decode() for value in connection.smembers("rq:queues")} | {"rq:queue:analysis"}
    )
    enqueue("solver", "gated", "admission-busy")
    busy, key = worker("solver", jobs=1)
    wait(lambda: connection.exists("admission-busy:started"))
    check(
        acquire_pause(connection, owner(), 20, scope([key]), approved, idle_solver_key=key) == -7,
        "Production idle-solver admission accepted an actual busy solver",
    )
    check(not connection.exists(PAUSE), "Busy solver refusal created pause")
    connection.set("admission-busy:release", 1)
    exited(busy)
    idle, key = worker("solver", jobs=1)
    wait(lambda: current(key) == b"idle")
    frozen = scope([key])
    marker = "rq:worker:fixture-historical"
    connection.hset(marker, "shutdown_requested_date", "fixture")
    connection.sadd("rq:queues", "rq:queue:analysis")
    own = owner()
    check(
        acquire_pause(connection, own, 20, frozen, approved, ["rq:queue:analysis"], [marker], key)
        == 1,
        "Verified idle solver/empty legacy/historical shape was refused",
    )
    check(resume_owned(connection, own), "Admission test could not resume owned pause")
    connection.hset(marker, "unexpected", "fixture")
    check(
        acquire_pause(
            connection, owner(), 20, frozen, approved, ["rq:queue:analysis"], [marker], key
        )
        == -6,
        "Changed shutdown-only marker shape was accepted",
    )
    connection.hdel(marker, "unexpected")
    connection.rpush("rq:queue:analysis", "fixture-legacy-pending")
    check(
        acquire_pause(
            connection, owner(), 20, frozen, approved, ["rq:queue:analysis"], [marker], key
        )
        == -5,
        "Nonempty legacy queue was accepted at atomic pause admission",
    )
    connection.lpop("rq:queue:analysis")
    enqueue("solver", "record", "admission-idle-cleanup")
    exited(idle)
    connection.hset("rq:job:fixture-unbounded", "timeout", -1)
    connection.rpush("rq:queue:solver", "fixture-unbounded")
    try:
        solver_envelope(connection, {})
    except GateError:
        pass
    else:
        raise AssertionError("Unbounded solver timeout metadata was accepted")
    connection.lpop("rq:queue:solver")
    connection.delete("rq:job:fixture-unbounded")
    configured = SimpleNamespace(
        solver_queue_enabled=True,
        solver_services=[object()],
        solver_timeout_seconds=45,
        database_pool_enabled=False,
    )
    solver_settings(configured)
    for field, invalid in (
        ("solver_queue_enabled", False),
        ("solver_services", []),
        ("solver_timeout_seconds", 61),
        ("database_pool_enabled", True),
    ):
        values = vars(configured).copy()
        values[field] = invalid
        try:
            solver_settings(SimpleNamespace(**values))
        except GateError:
            pass
        else:
            raise AssertionError("Unsafe solver configuration was accepted")
    result["production_admission_guards"] = {
        "actual_busy_solver_refused": True,
        "idle_solver_with_empty_transport_accepted": True,
        "legacy_nonempty_refused_atomically": True,
        "changed_shutdown_only_marker_refused": True,
        "unbounded_solver_metadata_refused": True,
        "solver_configuration_and_nullpool_guard_checked": True,
    }


def dependency_budget_regression():
    """Spend the release budget without spending the not-yet-enqueued dependency budget."""
    global active_case
    active_case = "dependency_phase_deadlines"
    solver, key = worker("solver", jobs=1)
    wait(lambda: current(key) == b"idle", condition="solver ready before producer")
    connection.set("fixture:hold-solver", 1)
    job = enqueue("producer", "dependent", "phase-budget", 3)
    producer, _ = worker("producer", jobs=1)
    wait(
        lambda: connection.exists("phase-budget:started"), condition="producer release wait started"
    )
    started = float(connection.get("phase-budget:started"))
    wait(
        lambda: time.monotonic() >= started + 2,
        seconds=4,
        condition="controlled delay before enqueue",
    )
    connection.set("phase-budget:release", 1)
    wait(
        lambda: connection.exists("phase-budget:solver:started"),
        condition="actual dependency started after delayed release",
    )
    dependency_started = float(connection.get("phase-budget:solver:started"))
    wait(
        lambda: time.monotonic() >= max(started + 3.25, dependency_started + 0.5),
        seconds=4,
        condition="held dependency exceeds the old shared deadline",
    )
    connection.set("phase-budget:solver:release", 1)
    wait(
        lambda: (
            connection.exists("phase-budget:finished")
            or connection.hget("rq:job:" + job.id, "status") == b"failed"
        ),
        condition="producer finishes within its separate dependency budget",
    )
    exited(solver)
    exited(producer)
    connection.delete("fixture:hold-solver")
    check(
        connection.exists("phase-budget:finished"),
        "Pre-enqueue release wait incorrectly consumed the synchronous dependency deadline",
    )
    check(
        float(connection.get("phase-budget:finished")) > started + 3,
        "Regression did not cross the previous shared deadline",
    )
    result["dependency_phase_deadlines"] = {
        "actual_worker_and_solver_completed": True,
        "delayed_release_did_not_spend_dependency_budget": True,
        "completion_crossed_previous_shared_deadline": True,
    }


def worker_snapshot_regressions():
    """Force native registration changes between enumeration and the coherent snapshot."""
    from maintenance import raw_workers

    global active_case
    active_case = "worker_snapshot_transitions"
    idle, key = worker("producer", jobs=1)
    wait(lambda: current(key) == b"idle", condition="snapshot departure worker ready")
    smembers = connection.smembers

    def depart_after_enumeration(name):
        members = smembers(name)
        send_shutdown_command(connection, key.removeprefix("rq:worker:"))
        exited(idle)
        return members

    with patch.object(connection, "smembers", side_effect=depart_after_enumeration):
        registered, rows = raw_workers(connection)
    check(
        key not in registered and rows[key]["death"],
        "Snapshot paired departed-worker membership with its later death hash",
    )
    born = []

    def arrive_after_enumeration(name):
        members = smembers(name)
        born.append(worker("producer", jobs=1))
        wait(lambda: current(born[0][1]) == b"idle", condition="snapshot arrival worker ready")
        return members

    with patch.object(connection, "smembers", side_effect=arrive_after_enumeration):
        registered, rows = raw_workers(connection)
    process, key = born[0]
    check(
        key in registered and rows[key]["state"] == "idle",
        "Snapshot omitted a worker born between enumeration and the read transaction",
    )
    enqueue("producer", "record", "snapshot-cleanup")
    exited(process)
    result["worker_snapshot_transitions"] = {
        "actual_worker_death_read_coherently": True,
        "actual_worker_birth_retried_and_included": True,
    }


def controller_regression(fault=False, solver_error=False):
    """Exercise the same CLI with actual same-host supervisor restarts, not mocked workers."""
    global active_case
    active_case = (
        "controller-fault"
        if fault
        else "controller-solver-error"
        if solver_error
        else "controller-success"
    )
    connection.flushdb()  # Exclusively owned marked Unix-socket DB15 fixture only.
    case_dir = run_dir / (
        "controller-fault"
        if fault
        else "controller-solver-error"
        if solver_error
        else "controller-success"
    )
    case_dir.mkdir(mode=0o700)
    plan = {
        "schema_version": 1,
        "workers": [
            {"hostname": "fixture-" + role, "role": role, "queues": [queue]}
            for role, queue in (("producer", "producer"), ("solver", "solver"), ("idle", "idle"))
        ],
        "canonical_queues": ["rq:queue:producer", "rq:queue:solver", "rq:queue:idle"],
        "historical_markers": [],
        "empty_legacy_queues": ["rq:queue:analysis"],
    }
    plan_path, context = case_dir / "scope.json", case_dir / "context.json"
    plan_path.write_text(json.dumps(plan))
    flags = (
        {
            "abort_when_bridge_active": True,
            "active_bridge_marker": "controller-producer:solver:started",
            "fail_stop_once": True,
        }
        if fault
        else {"hold_final": True}
    )
    context.write_text(json.dumps({"runtime": "0.1.1", "schema": "0033", "faults": flags}))
    original, replacements, supervisors = {}, {}, []
    original["solver"] = worker("solver", hostname="fixture-solver")
    wait(
        lambda: current(original["solver"][1]) == b"idle", condition="original solver bootstrapped"
    )
    original["producer"] = worker("producer", hostname="fixture-producer")
    wait(
        lambda: current(original["producer"][1]) == b"idle",
        condition="original producer bootstrapped",
    )
    original["idle"] = worker("idle", jobs=1, hostname="fixture-idle")
    wait(lambda: current(original["idle"][1]) == b"idle", condition="original idle worker ready")
    # Bootstrap/import time belongs to fixture setup, not an already-running job's budget.
    enqueue("solver", "gated", "controller-solver")
    wait(
        lambda: connection.exists("controller-solver:started"),
        condition="original solver function started",
    )
    enqueue("producer", "dependent", "controller-producer")
    wait(
        lambda: connection.exists("controller-producer:started"),
        condition="original producer function started",
    )

    def supervise(role):
        process, key = original[role]
        if process.wait(timeout=20) != 0:
            return
        replacements[role] = worker(
            role,
            jobs=1,
            hostname="fixture-" + role,
            startup_gate="fixture:replacement-bootstrap" if role == "idle" else None,
        )

    for role in original:
        thread = threading.Thread(target=supervise, args=(role,))
        thread.start()
        supervisors.append(thread)
    own = owner()
    state, output = case_dir / "state.json", case_dir / "drain.json"
    common = [
        "--scope",
        str(plan_path),
        "--owner",
        own,
        "--state",
        str(state),
        "--output",
        str(output),
        "--fixture-root",
        str(root),
        "--fixture-socket",
        str(socket_path),
        "--fixture-context",
        str(context),
    ]
    environment = {key: os.environ[key] for key in ("PATH", "LANG", "TZ") if key in os.environ}
    environment.update(
        {
            "PYTHONPATH": str(source),
            "PYTHONDONTWRITEBYTECODE": "1",
            "DEVFEED_DATABASE_URL": "postgresql+psycopg://fixture:fixture@127.0.0.1:1/maintenance_test",
            "DEVFEED_REDIS_URL": "unix://" + str(socket_path) + "?db=15",
            "DEVFEED_AI_ENABLED": "false",
            "DEVFEED_METRICS_ENABLED": "false",
            "DEVFEED_TELEMETRY_ENVIRONMENT": "test",
            "OTEL_SDK_DISABLED": "true",
        }
    )
    command = [
        sys.executable,
        str(source / "maintenance.py"),
        "drain",
        *common,
        "--ttl",
        "90",
        "--deadline",
        "35",
        "--bridge-lifetime",
        "30",
        "--handoff-timeout",
        "15",
        "--minimum-remaining",
        "15",
    ]
    controller = subprocess.Popen(
        command, cwd=root, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    controllers.append((active_case, controller, output, own))
    wait(
        lambda: (
            connection.hget(original["solver"][1], "shutdown_requested_date")
            and connection.hget(original["producer"][1], "shutdown_requested_date")
        ),
        condition="original solver and producer acknowledged warm shutdown",
    )
    from maintenance import GateError, inspect_scope

    bridge_key = json.loads(connection.get(namespace(own) + ":state"))["bridge_key"]
    startup_gate = "fixture:replacement-bootstrap"
    for phase, expected_state in (("registered", None), ("started", b"started")):
        wait(
            lambda: connection.exists(startup_gate + ":" + phase),
            condition="replacement native startup phase: " + phase,
        )
        replacement_key = replacements["idle"][1]
        check(
            current(replacement_key) == expected_state,
            "Fixture did not hold the native pre-suspension startup state",
        )
        try:
            inspect_scope(connection, plan, allowed_bridge=bridge_key)
        except GateError as exc:
            check(
                str(exc) == "A scoped worker has an unexpected runtime state",
                "Initial admission failed for a reason other than the held startup state",
            )
        else:
            raise AssertionError("Initial admission accepted a worker before suspension startup")
        time.sleep(0.2)
        check(controller.poll() is None, "Controller rejected an owned replacement during startup")
        connection.set(startup_gate + ":continue-" + phase, 1)
    enqueue("producer", "record", "controller-backlog")
    if fault:
        connection.set("fixture:hold-solver", 1)
        connection.set("fixture:hold-function-entry", 1)
    connection.set("controller-solver:release", 1)
    wait(
        lambda: connection.get(namespace(own) + ":handoff") == own.encode(),
        condition="controller granted handoff after supervised solver replacement",
    )
    connection.set("controller-producer:release", 1)
    if fault:
        wait(
            lambda: connection.exists("controller-producer:solver:entry-wait"),
            condition="solver function entered before active-job fault acknowledgement",
        )
        time.sleep(0.2)
        check(
            controller.poll() is None and not connection.exists("fixture:stop-write-failed"),
            "Controller injected failure from the RQ current-job pointer before function acknowledgement",
        )
        connection.set("controller-producer:solver:entry-release", 1)
        wait(
            lambda: (
                connection.exists("controller-producer:solver:started")
                and connection.exists("fixture:stop-write-failed")
            ),
            condition="held solver function started and controller stop write failed",
        )
        time.sleep(0.3)
        check(
            controller.poll() is None
            and not connection.exists("controller-producer:solver:finished"),
            "Controller exited before active bridge work settled after stop-write failure",
        )
        connection.set("controller-producer:solver:release", 1)
        check(controller.wait(timeout=18) == 1, "Injected controller failure was not reported")
        evidence = json.loads(output.read_text())
        check(
            not evidence["success"] and evidence.get("stop_write_failures") == 1,
            "Stop-write failure evidence differs",
        )
        check(
            connection.get(PAUSE) == own.encode(), "Controller failure automatically resumed pause"
        )
        result["controller_failure_settlement"] = {
            "fault_waited_for_held_function_acknowledgement": True,
            "active_bridge_job_completed_before_controller_exit": True,
            "stop_write_failure_did_not_bypass_child_wait": True,
            "owned_pause_retained": True,
        }
    else:
        wait(
            lambda: connection.exists("fixture:final-gate-ready"),
            condition="controller reached final drain gate",
        )
        if solver_error:
            enqueue("solver", "explode", "deliberate-solver-error")
            bridge_key = json.loads(connection.get(namespace(own) + ":state"))["bridge_key"]
            wait(
                lambda: connection.hget(bridge_key, "failed_job_count") == b"1",
                condition="bridge recorded the deliberate solver exception",
            )
        else:
            connection.zadd(
                "rq:wip:producer", {"fixture-orphan:fixture-execution": time.time() + 60}
            )
        connection.set("fixture:allow-final", 1)
        if not solver_error:
            time.sleep(0.4)
            check(
                controller.poll() is None and connection.get(PAUSE) == own.encode(),
                "Controller ignored stray WIP reference",
            )
            connection.zrem("rq:wip:producer", "fixture-orphan:fixture-execution")
        check(
            controller.wait(timeout=18) == (1 if solver_error else 0),
            "Controller execution-failure gate returned an unexpected status",
        )
        evidence = json.loads(output.read_text())
        if solver_error:
            check(
                not evidence["success"]
                and evidence["bridge_rq_counts"]["failed_job_count"] == 1
                and connection.get(PAUSE) == own.encode(),
                "A bridge RQ exception was reported as a successful drain",
            )
            result["controller_bridge_failure_gate"] = {
                "deliberate_solver_exception_count": 1,
                "cutover_refused": True,
                "normal_original_jobs_completed": True,
                "owned_pause_retained": True,
            }
        else:
            check(
                evidence["success"]
                and evidence["replacement_suspended_count"] == 3
                and evidence["solver_bridge_exited"],
                "Controller did not prove all replacements/bridge settlement",
            )
        check(
            connection.llen("rq:queue:producer") == 1
            and not connection.exists("controller-backlog:started"),
            "Controller removed or consumed non-solver backlog",
        )
        if not solver_error:
            result["controller_cli"] = {
                "actual_supervisor_replacements": 3,
                "all_replacements_suspended": True,
                "synchronous_dependency_completed": True,
                "durable_owned_state_present": True,
                "stray_wip_prevented_completion": True,
                "non_solver_backlog_preserved": True,
                "runtime_schema_guard_explicitly_injected": True,
            }
    for thread in supervisors:
        thread.join(timeout=5)
    wait(
        lambda: (
            len(replacements) == 3
            and all(current(key) == b"suspended" for _, key in replacements.values())
        )
    )
    result["controller_startup_transitions"] = {
        "native_missing_and_started_states_held": True,
        "initial_admission_refused_both_states": True,
        "owned_replacements_waited_until_suspended": True,
    }
    # Authoritative state survives removal of the private local snapshot.
    state.unlink()
    from maintenance import GateError, durable_state

    stored = connection.get(namespace(own) + ":state")
    corrupted = json.loads(stored)
    corrupted["owner"] = "different-fixture-owner"
    connection.set(namespace(own) + ":state", json.dumps(corrupted), ex=90)
    try:
        durable_state(
            connection,
            SimpleNamespace(owner=own),
            hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        )
    except GateError:
        pass
    else:
        raise AssertionError("Copied/wrong-owner durable state was accepted")
    connection.set(namespace(own) + ":state", stored, ex=90)
    rejected = subprocess.run(
        [sys.executable, str(source / "maintenance.py"), "resume", *common],
        cwd=root,
        env=environment,
        capture_output=True,
        timeout=10,
    )
    check(
        rejected.returncode == 1 and connection.get(PAUSE) == own.encode(),
        "Old-image normal resume bypassed version/schema guard",
    )
    mode = "abort-before-cutover" if fault or solver_error else "resume"
    if not fault and not solver_error:
        context.write_text(json.dumps({"runtime": "0.1.2", "schema": "0034"}))
    resumed = subprocess.run(
        [sys.executable, str(source / "maintenance.py"), mode, *common],
        cwd=root,
        env=environment,
        capture_output=True,
        timeout=10,
    )
    check(
        resumed.returncode == 0 and not connection.exists(PAUSE),
        "Durable-state guarded owner resume/abort failed",
    )
    enqueue("solver", "record", "controller-solver-resume")
    enqueue("idle", "record", "controller-idle-resume")
    for process, key in replacements.values():
        exited(process)
    check(
        connection.exists("controller-backlog:finished"),
        "Preserved producer backlog did not run after owner resume",
    )
    result["controller_abort_before_cutover" if fault else "controller_new_release_resume"] = {
        "local_state_file_not_required": True,
        "old_image_normal_resume_refused": True,
        "correct_guard_owner_cas_passed": True,
    }


def controller_transport(own):
    stored = connection.get(namespace(own) + ":state")
    if not stored:
        return {"durable_state_present": False}
    state = json.loads(stored)
    registered = connection.smembers("rq:workers")
    rows = [
        dict(
            zip(
                ("hostname", "state", "current_job"),
                connection.hmget(key, "hostname", "state", "current_job"),
            )
        )
        for key in registered
    ]
    return {
        "owned_pause_matches": connection.get(PAUSE) == own.encode(),
        "pause_ttl_ms": connection.pttl(PAUSE),
        "handoff_present": connection.get(namespace(own) + ":handoff") == own.encode(),
        "original_solver_registered": state["solver_key"].encode() in registered,
        "original_solver_current_job": bool(connection.hget(state["solver_key"], "current_job")),
        "bridge_registered": state["bridge_key"].encode() in registered,
        "bridge_current_job": bool(connection.hget(state["bridge_key"], "current_job")),
        "solver_replacement_states": [
            row["state"].decode()
            if row["state"] in (b"idle", b"busy", b"suspended", b"started")
            else "missing_or_unknown"
            for row in rows
            if row["hostname"] == b"fixture-solver"
        ],
        "execution_key_count": sum(1 for _ in connection.scan_iter(match="rq:execution:*")),
    }


try:
    if args.case != "all":
        {
            "dependency-budget": dependency_budget_regression,
            "worker-snapshot": worker_snapshot_regressions,
            "controller-fault": lambda: controller_regression(fault=True),
        }[args.case]()
        raise SelectedCaseComplete()
    dependency_budget_regression()
    worker_snapshot_regressions()
    active_case = "warm_bridge_handoff"
    # Original active solver + active producer which will synchronously need another solver job.
    enqueue("solver", "gated", "original-solver")
    solver, solver_key = worker("solver")
    wait(lambda: connection.exists("original-solver:started"))
    enqueue("producer", "dependent", "producer")
    enqueue("producer", "record", "producer-backlog")
    producer, producer_key = worker("producer")
    wait(lambda: connection.exists("producer:started"))
    original = scope([solver_key, producer_key])
    original_executions = [
        "rq:execution:" + item.decode() for item in connection.zrange("rq:wip:solver", 0, -1)
    ]
    check(len(original_executions) == 1, "Expected one actual original solver execution")
    own = owner()
    bridge, bridge_key = worker(
        "solver", jobs=20, bridge_owner=own, old_solver=solver_key, executions=original_executions
    )
    check(
        acquire_pause(connection, own, 45, original, queues) == 1,
        "Could not acquire owned scoped pause",
    )
    wait(lambda: connection.exists(bridge_key))
    for key, birth in original.items():
        check(
            publish_warm_once(connection, own, key, birth) == 1,
            "Initial official warm publish was refused",
        )
    wait(lambda: all(connection.hget(key, "shutdown_requested_date") for key in original))
    time.sleep(1.1)
    check(
        all(publish_warm_once(connection, own, key, birth) == 0 for key, birth in original.items()),
        "Ledger allowed a duplicate warm command",
    )
    check(not connection.exists("producer:finished"), "Producer fixture completed before handoff")
    check(
        connection.hget(bridge_key, "current_job") is None,
        "Bridge consumed before original solver exit",
    )
    connection.set("original-solver:release", 1)
    wait(lambda: connection.exists("original-solver:finished"))
    exited(solver)
    check(
        not connection.sismember("rq:workers", solver_key)
        and not connection.exists(*original_executions),
        "Original solver has not released its RQ execution",
    )
    handoff = time.monotonic()
    connection.set("fixture:handoff", own, ex=45)  # Granted only after actual process exit above.
    connection.set("producer:release", 1)
    wait(lambda: connection.exists("producer:finished"))
    exited(producer)
    check(
        float(connection.get("producer:solver:started")) >= handoff,
        "Bridge violated single-consumer handoff",
    )
    check(
        not connection.exists("producer-backlog:started"),
        "Original producer consumed further backlog",
    )
    replacement, replacement_key = worker("producer", jobs=1)
    wait(lambda: current(replacement_key) == b"suspended")
    check(
        not connection.exists("producer-backlog:started"),
        "Replacement dequeued before observing pause",
    )
    check(
        connection.hlen(namespace(own) + ":publish-attempts") == 2,
        "Warm publish ledger differs from exact original scope",
    )
    check(
        connection.llen("rq:queue:solver") == 0
        and connection.llen("rq:queue:solver:intermediate") == 0
        and connection.hget(bridge_key, "current_job") is None,
        "Solver did not drain",
    )
    connection.set("fixture:bridge-stop", own, ex=45)
    exited(bridge)
    check(
        not connection.exists(namespace(own) + ":solver-bridge"),
        "Exited bridge retained consumer lease",
    )
    enqueue("solver", "record", "after-bridge-exit")
    time.sleep(0.3)
    check(
        not connection.exists("after-bridge-exit:started"), "Exited bridge performed later activity"
    )
    wrong = owner()
    check(
        not resume_owned(connection, wrong) and connection.get(PAUSE) == own.encode(),
        "Wrong owner resumed pause",
    )
    result["warm_bridge_handoff"] = {
        "actual_original_jobs_completed": True,
        "synchronous_solver_dependency_preserved": True,
        "original_solver_exited_before_bridge_consumed": True,
        "official_warm_publish_attempts": 2,
        "duplicate_attempts_refused_after_one_second": True,
        "replacement_observed_pause_before_dequeue": True,
        "bridge_stopped_after_solver_drain": True,
        "no_bridge_activity_after_exit": True,
        "wrong_owner_resume_refused": True,
    }
    check(resume_owned(connection, own), "Owner failed to resume after bridge exit")
    exited(replacement)
    normal_solver, normal_key = worker("solver", jobs=1)
    wait(lambda: connection.exists("after-bridge-exit:finished"))
    exited(normal_solver)

    # Official warm command wakes an empty, blocked-idle worker without a synthetic delivery.
    active_case = "idle_warm_stop"
    idle, idle_key = worker("producer", jobs=1)
    wait(lambda: current(idle_key) == b"idle")
    idle_birth = connection.hget(idle_key, "birth")
    own = owner()
    check(
        acquire_pause(connection, own, 20, {idle_key: idle_birth}, queues) == 1,
        "Idle scoped pause failed",
    )
    check(publish_warm_once(connection, own, idle_key, idle_birth) == 1, "Idle warm publish failed")
    exited(idle)
    enqueue("producer", "record", "idle-backlog")
    idle_replacement, replacement_key = worker("producer", jobs=1)
    wait(lambda: current(replacement_key) == b"suspended")
    check(not connection.exists("idle-backlog:started"), "Idle replacement raced through pause")
    result["idle_warm_stop"] = {
        "blocked_idle_process_exited_without_delivery": True,
        "replacement_acknowledged_suspended_before_any_delivery": True,
    }
    check(resume_owned(connection, own), "Idle owner could not resume")
    exited(idle_replacement)

    # Foreign live worker and foreign existing pause are never adopted.
    active_case = "ownership_refusals"
    foreign, foreign_key = worker("foreign", jobs=1)
    wait(lambda: current(foreign_key) == b"idle")
    check(
        acquire_pause(connection, owner(), 10, {}, queues) == -3,
        "Foreign actual worker was accepted",
    )
    check(not connection.exists(PAUSE), "Scope refusal created pause")
    enqueue("foreign", "record", "foreign")
    exited(foreign)
    foreign_owner = owner()
    connection.set(PAUSE, foreign_owner)
    check(
        acquire_pause(connection, owner(), 10, {}, queues) == -1 and connection.pttl(PAUSE) == -1,
        "Pre-existing persistent pause changed",
    )
    check(not resume_owned(connection, owner()), "Foreign pause was resumed")
    check(resume_owned(connection, foreign_owner), "Fixture pause creator could not release it")
    result["ownership_refusals"] = {
        "actual_foreign_worker_refused": True,
        "pre_existing_persistent_pause_preserved": True,
        "foreign_resume_refused": True,
    }

    # A different controller already warmed this actual busy worker: never send its second SIGINT.
    active_case = "already_warm_refusal"
    enqueue("producer", "gated", "already-warm")
    warming, warming_key = worker("producer", jobs=1)
    wait(lambda: connection.exists("already-warm:started"))
    birth = connection.hget(warming_key, "birth")
    send_shutdown_command(connection, warming_key.removeprefix("rq:worker:"))
    wait(lambda: connection.hget(warming_key, "shutdown_requested_date"))
    own = owner()
    check(
        acquire_pause(connection, own, 20, {warming_key: birth}, queues) == 1,
        "Already-warm fixture pause failed",
    )
    time.sleep(1.1)
    check(
        publish_warm_once(connection, own, warming_key, birth) == -4,
        "Already-warm worker received another shutdown",
    )
    connection.set("already-warm:release", 1)
    wait(lambda: connection.exists("already-warm:finished"))
    exited(warming)
    check(resume_owned(connection, own), "Already-warm fixture resume failed")
    result["already_warm_refusal"] = {
        "existing_native_warm_request_detected": True,
        "second_shutdown_not_published": True,
        "current_job_completed_normally": True,
    }

    # A failed/ambiguous native publish is not retried, and retains the bounded pause.
    active_case = "publish_uncertainty"
    uncertain, uncertain_key = worker("producer", jobs=1)
    wait(lambda: current(uncertain_key) == b"idle")
    birth = connection.hget(uncertain_key, "birth")
    own = owner()
    check(
        acquire_pause(connection, own, 20, {uncertain_key: birth}, queues) == 1,
        "Ambiguous-case pause failed",
    )
    try:
        with patch.object(
            connection,
            "publish",
            side_effect=ConnectionError("Injected fixture publish uncertainty"),
        ):
            publish_warm_once(connection, own, uncertain_key, birth)
    except ConnectionError:
        pass
    else:
        raise AssertionError("Injected publish failure was hidden")
    check(
        publish_warm_once(connection, own, uncertain_key, birth) == 0,
        "Uncertain publish was retried",
    )
    check(
        connection.get(PAUSE) == own.encode() and connection.pttl(PAUSE) > 0,
        "Publish failure removed pause",
    )
    check(
        connection.connection_pool.connection_kwargs["retry"].get_retries() == 0,
        "Fixture client enables publish retries",
    )
    try:
        acquire_pause(connection, owner(), True, {}, queues)
    except ValueError:
        pass
    else:
        raise AssertionError("Boolean TTL was accepted")
    result["publish_uncertainty"] = {
        "injected_connection_failure_propagated": True,
        "no_second_publish_attempt": True,
        "owned_bounded_pause_retained": True,
        "redis_command_retries": 0,
        "boolean_ttl_refused": True,
    }
    check(resume_owned(connection, own), "Uncertain fixture owner could not resume after audit")
    enqueue("producer", "record", "uncertain-cleanup")
    exited(uncertain)

    # An owned bridge exits before the remaining TTL is too small, and never starts later work.
    active_case = "bridge_ttl_and_cas"
    own = owner()
    check(acquire_pause(connection, own, 8, {}, queues) == 1, "Bounded expiry pause failed")
    connection.set("fixture:handoff", own, ex=10)
    connection.delete("fixture:bridge-stop")
    expiring, expiring_key = worker("solver", jobs=20, bridge_owner=own, min_remaining_ms=2000)
    exited(expiring)
    wait(lambda: not connection.exists(PAUSE), seconds=10)
    enqueue("solver", "record", "after-ttl-loss")
    time.sleep(0.3)
    check(not connection.exists("after-ttl-loss:started"), "Bridge admitted work after TTL expiry")
    replacement_owner = owner()
    check(
        acquire_pause(connection, replacement_owner, 10, {}, queues) == 1,
        "Replacement owner could not acquire pause",
    )
    check(
        not resume_owned(connection, own) and connection.get(PAUSE) == replacement_owner.encode(),
        "Stale owner removed replacement pause",
    )
    check(resume_owned(connection, replacement_owner), "Replacement owner resume failed")
    drain, key = worker("solver", jobs=1)
    exited(drain)
    result["bridge_ttl_and_cas"] = {
        "bridge_exited_on_insufficient_owned_ttl": True,
        "no_new_activity_after_expiry": True,
        "stale_owner_cannot_remove_replacement": True,
    }
    active_case = "production_admission_guards"
    admission_regressions()
    controller_regression()
    controller_regression(fault=True)
    controller_regression(solver_error=True)
    result["success"] = True
except SelectedCaseComplete:
    result["success"] = True
except Exception as exc:
    result["success"] = False
    result["error"] = f"{type(exc).__name__}: {exc}"
    result["failure_case"] = active_case
    result["failure_processes"] = {
        "worker_total": len(processes),
        "worker_running": sum(process.poll() is None for process, _ in processes),
        "worker_exit_codes": [process.poll() for process, _ in processes],
        "controllers": [
            {
                "case": case,
                "exit_code": process.poll(),
                "evidence_present": output.exists(),
                "evidence": json.loads(output.read_text()) if output.exists() else None,
                "transport": controller_transport(own),
            }
            for case, process, output, own in controllers
        ],
    }
    result["failure_transport"] = {
        "registered_worker_count": connection.scard("rq:workers"),
        "retained_worker_hash_states": {
            state: sum(current(key) == state.encode() for key in worker_keys)
            for state in ("idle", "busy", "suspended")
        },
        "solver_queued": connection.llen("rq:queue:solver"),
        "solver_wip": connection.zcard("rq:wip:solver"),
        "producer_wip": connection.zcard("rq:wip:producer"),
    }
finally:
    # Local fixture cleanup only. No direct OS signals or production connections.
    for value in owners:
        try:
            resume_owned(connection, value)
        except Exception:
            pass
    for process, log in processes:
        try:
            process.wait(timeout=40)
        except subprocess.TimeoutExpired:
            result["success"] = False
            result["cleanup_error"] = "Worker did not exit naturally; no force signal sent"
        log.close()
    for _, process, _, _ in controllers:
        try:
            process.wait(timeout=50)
        except subprocess.TimeoutExpired:
            result["success"] = False
            result["cleanup_error"] = "Controller did not exit naturally; no force signal sent"
    result.update(
        {
            "fixture_only": True,
            "selected_case": args.case,
            "full_suite": args.case == "all",
            "redis_db": 15,
            "redis_transport": "private Unix socket",
            "architecture": platform.machine(),
            "native_arm64_proven": platform.machine() in ("aarch64", "arm64"),
            "rq_version": rq.__version__,
            "rq_worker_base_sha256": hashlib.sha256(worker_base.read_bytes()).hexdigest(),
            "actual_worker_base": "devfeed_aggregator.analysis_worker.AnalysisAwareWorker",
            "fixture_worker_ttl_seconds": 18,
            "fixture_job_monitor_seconds": 1,
            "no_production_access": True,
            "no_direct_control_signals": True,
            "native_shutdown_handler_internal_signal": "SIGINT",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "source_sha256": {
                name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                for name in (
                    "maintenance.py",
                    "maintenance_candidate.py",
                    "fixture_jobs.py",
                    "fixture_worker.py",
                    "run_fixture.py",
                )
            },
            "limitations": [
                "PubSub ledger proves at-most-one attempt, not guaranteed delivery.",
                "Failure retains the owned pause until its bounded TTL; TTL loss aborts rollout.",
                "Admission owner/TTL checks precede each nonblocking dequeue; an externally replaced owner between check and dequeue is not an atomic barrier.",
                "Fixture proves RQ lifecycle and dependency transport, not actual external solver/Codex or Kubernetes/Fleet behavior.",
            ],
        }
    )
    path = root / "evidence.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    connection.close()
raise SystemExit(0 if result.get("success") else 1)
