import time
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from rq import Queue
from rq.serializers import JSONSerializer


def connect(socket_path):
    return Redis(
        unix_socket_path=socket_path, db=15, socket_timeout=2, retry=Retry(NoBackoff(), retries=0)
    )


def gated(socket_path, marker):
    with connect(socket_path) as connection:
        if connection.exists("fixture:hold-function-entry"):
            connection.set(marker + ":entry-wait", 1)
            until = time.monotonic() + 10
            while not connection.exists(marker + ":entry-release"):
                if time.monotonic() >= until:
                    raise TimeoutError("Gated fixture function-entry deadline exceeded")
                time.sleep(0.02)
        connection.set(marker + ":started", time.monotonic())
        until = time.monotonic() + 10
        while not connection.exists(marker + ":release"):
            if time.monotonic() >= until:
                raise TimeoutError("Gated fixture deadline exceeded")
            time.sleep(0.02)
        connection.set(marker + ":finished", time.monotonic())


def record(socket_path, marker):
    with connect(socket_path) as connection:
        connection.set(marker + ":started", time.monotonic())
        connection.set(marker + ":finished", time.monotonic())


def explode(socket_path, marker):
    raise RuntimeError("Deliberate fixture solver exception")


def dependent(socket_path, marker, phase_timeout=10):
    with connect(socket_path) as connection:
        connection.set(marker + ":started", time.monotonic())
        until = time.monotonic() + phase_timeout
        while not connection.exists(marker + ":release"):
            if time.monotonic() >= until:
                raise TimeoutError("Dependent fixture release deadline exceeded")
            time.sleep(0.02)
        function = "gated" if connection.exists("fixture:hold-solver") else "record"
        Queue("solver", connection=connection, serializer=JSONSerializer).enqueue(
            "fixture_jobs." + function,
            socket_path,
            marker + ":solver",
            job_timeout=12,
            result_ttl=0,
        )
        # Match queued_solver._request: the dependency budget starts after enqueue,
        # independently of the fixture's earlier pre-handoff release handshake.
        until = time.monotonic() + phase_timeout
        while not connection.exists(marker + ":solver:finished"):
            if time.monotonic() >= until:
                raise TimeoutError("Synchronous solver dependency was not served")
            time.sleep(0.02)
        connection.set(marker + ":finished", time.monotonic())
