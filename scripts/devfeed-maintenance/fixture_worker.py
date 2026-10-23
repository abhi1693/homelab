import argparse
import time
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from rq import Queue
from rq.exceptions import StopRequested
from rq.serializers import JSONSerializer
from devfeed_aggregator.analysis_worker import AnalysisAwareWorker
from maintenance_candidate import PAUSE, solver_bridge_class

parser = argparse.ArgumentParser()
parser.add_argument("--socket", required=True)
parser.add_argument("--queue", required=True)
parser.add_argument("--name", required=True)
parser.add_argument("--hostname")
parser.add_argument("--startup-gate")
parser.add_argument("--jobs", default=2, type=int)
parser.add_argument("--owner")
parser.add_argument("--original-solver", default="rq:worker:fixture-already-exited")
parser.add_argument("--execution", action="append", default=[])
parser.add_argument("--min-remaining-ms", default=3000, type=int)
args = parser.parse_args()
connection = Redis(
    unix_socket_path=args.socket, db=15, socket_timeout=3, retry=Retry(NoBackoff(), retries=0)
)
queue = Queue(args.queue, connection=connection, serializer=JSONSerializer)
worker_type = AnalysisAwareWorker
options = {}
if args.owner:
    until = time.monotonic() + 15
    while connection.get(PAUSE) != args.owner.encode():
        if time.monotonic() >= until:
            raise TimeoutError("Owned pause did not arrive for prewarmed fixture bridge")
        time.sleep(0.025)
    worker_type = solver_bridge_class(AnalysisAwareWorker)
    options = {
        "maintenance_owner": args.owner,
        "handoff_key": "fixture:handoff",
        "stop_key": "fixture:bridge-stop",
        "original_solver_key": args.original_solver,
        "original_execution_keys": args.execution,
        "lifetime": 25,
        "handoff_timeout": 12,
        "min_remaining_ms": args.min_remaining_ms,
    }
if args.startup_gate:

    class StartupGatedWorker(worker_type):
        """Hold the native missing/started states; preserve normal RQ work and suspension."""

        def wait_startup(self, phase):
            self.connection.set(args.startup_gate + ":" + phase, 1)
            until = time.monotonic() + 10
            while not self.connection.exists(args.startup_gate + ":continue-" + phase):
                if time.monotonic() >= until:
                    raise TimeoutError("Fixture startup acknowledgement deadline exceeded")
                time.sleep(0.02)

        def register_birth(self):
            super().register_birth()
            self.wait_startup("registered")

        def check_for_suspension(self, burst):
            if self.get_state() == "started":
                self.wait_startup("started")
            return super().check_for_suspension(burst)

    worker_type = StartupGatedWorker
worker = worker_type(
    [queue],
    connection=connection,
    serializer=JSONSerializer,
    name=args.name,
    worker_ttl=18,
    job_monitoring_interval=1,
    log_job_description=False,
    **options,
)
if args.hostname:
    worker.hostname = args.hostname  # Fixture models distinct Pod hostnames on one test host.
try:
    worker.work(max_jobs=args.jobs, max_idle_time=12, logging_level="CRITICAL")
except StopRequested:
    pass
finally:
    if args.owner:
        worker.close_maintenance_lease()
    connection.close()
