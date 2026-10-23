"""Owned RQ maintenance primitives; orchestration must establish scope and rollout gates."""

import hashlib
import json
import math
import time
import uuid

from rq.command import send_shutdown_command
from rq.exceptions import StopRequested

PAUSE = "rq:suspended"


def namespace(owner):
    return "devfeed:maintenance:" + hashlib.sha256(owner.encode()).hexdigest()


def acquire_pause(
    connection,
    owner,
    ttl,
    workers,
    queues,
    legacy_queues=(),
    historical_markers=(),
    idle_solver_key=None,
):
    """Refuse existing pause, changed worker births, and foreign live worker/queue scope."""
    if type(ttl) is not int or not 1 <= ttl <= 14400 or not owner:
        raise ValueError("A unique owner and a bounded1–14400s TTL are required")
    script = """
if redis.call('EXISTS', KEYS[1]) == 1 then return -1 end
local policy=cjson.decode(ARGV[3])
local expected = {}
for _,item in ipairs(policy.workers) do
 local k=item[1]; local birth=item[2]
 expected[k]=true
 if redis.call('HGET',k,'birth') ~= birth then return -2 end
end
for _,k in ipairs(redis.call('SMEMBERS','rq:workers')) do
 if redis.call('EXISTS',k)==1 and not expected[k] then return -3 end
end
local queues={}
for _,k in ipairs(policy.queues) do queues[k]=true end
for _,k in ipairs(redis.call('SMEMBERS','rq:queues')) do
 if not queues[k] then return -4 end
end
for _,q in ipairs(policy.legacy) do
 local name=string.sub(q,10)
 if redis.call('LLEN',q)~=0 or redis.call('LLEN',q..':intermediate')~=0 or redis.call('ZCARD','rq:wip:'..name)~=0 or redis.call('SCARD','rq:workers:'..name)~=0 then return -5 end
end
for _,k in ipairs(policy.markers) do
 if redis.call('SISMEMBER','rq:workers',k)~=0 then return -6 end
 if redis.call('EXISTS',k)==1 then
  local fields=redis.call('HKEYS',k)
  if #fields~=1 or fields[1]~='shutdown_requested_date' then return -6 end
 end
end
if policy.idle_solver then
 if redis.call('HGET',policy.idle_solver,'state')~='idle' or redis.call('HEXISTS',policy.idle_solver,'current_job')~=0 or redis.call('LLEN','rq:queue:solver')~=0 or redis.call('LLEN','rq:queue:solver:intermediate')~=0 or redis.call('ZCARD','rq:wip:solver')~=0 then return -7 end
end
if redis.call('SET',KEYS[1],ARGV[1],'NX','EX',ARGV[2]) then return 1 end
return -1
"""
    policy = {
        "workers": [
            [key, birth.decode() if isinstance(birth, bytes) else birth]
            for key, birth in workers.items()
        ],
        "queues": list(queues),
        "legacy": list(legacy_queues),
        "markers": list(historical_markers),
    }
    if idle_solver_key is not None:
        policy["idle_solver"] = idle_solver_key
    return connection.eval(script, 1, PAUSE, owner, ttl, json.dumps(policy))


def resume_owned(connection, owner):
    return bool(
        connection.eval(
            "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
            1,
            PAUSE,
            owner,
        )
    )


def publish_warm_once(connection, owner, worker_key, birth):
    """One ATTEMPT per original worker. Ambiguous delivery is never retried."""
    if not worker_key.startswith("rq:worker:"):
        raise ValueError("Exact RQ worker hash key is required")
    retry = connection.connection_pool.connection_kwargs.get("retry")
    if retry is None or retry.get_retries() != 0:
        raise ValueError("Official warm PUBLISH requires an explicitly zero-retry Redis client")
    ledger = namespace(owner) + ":publish-attempts"
    admitted = connection.eval(
        """
if redis.call('GET',KEYS[1])~=ARGV[1] or redis.call('PTTL',KEYS[1])<=0 then return -1 end
if redis.call('HGET',ARGV[2],'birth')~=ARGV[3] then return -2 end
if redis.call('HEXISTS',KEYS[2],ARGV[2])==1 then return 0 end
if redis.call('HEXISTS',ARGV[2],'shutdown_requested_date')==1 then return -4 end
if redis.call('SISMEMBER','rq:workers',ARGV[2])==0 then return -3 end
redis.call('HSET',KEYS[2],ARGV[2],'attempted')
redis.call('PEXPIRE',KEYS[2],redis.call('PTTL',KEYS[1])+300000)
return 1
""",
        2,
        PAUSE,
        ledger,
        owner,
        worker_key,
        birth,
    )
    if admitted != 1:
        return admitted
    # Native RQ handler sends SIGINT internally. Never retry this call on uncertainty.
    send_shutdown_command(connection, worker_key.removeprefix("rq:worker:"))
    return 1


def solver_bridge_class(base):
    """Preserve normal worker execution; bypass only the owned pause on exact solver queue."""

    class SolverBridge(base):
        def __init__(
            self,
            *args,
            maintenance_owner,
            handoff_key,
            stop_key,
            original_solver_key,
            original_execution_keys=(),
            lifetime=1800,
            handoff_timeout=330,
            min_remaining_ms=330000,
            poll_seconds=0.1,
            **kwargs,
        ):
            super().__init__(*args, **kwargs)
            if self.queue_names() != ["solver"]:
                raise ValueError("Maintenance bridge may consume only solver")
            if (
                type(lifetime) is not int
                or not 1 <= lifetime <= 3600
                or type(handoff_timeout) is not int
                or not 1 <= handoff_timeout <= lifetime
                or type(min_remaining_ms) is not int
                or not 1 <= min_remaining_ms <= 14400000
                or not 0.01 <= poll_seconds <= 1
            ):
                raise ValueError("Bridge requires positive bounded timing parameters")
            self.maintenance_owner = maintenance_owner
            self.handoff_key, self.stop_key = handoff_key, stop_key
            self.original_solver_key = original_solver_key
            self.original_execution_keys = tuple(original_execution_keys)
            self.until = time.monotonic() + lifetime
            self.handoff_until = time.monotonic() + handoff_timeout
            self.min_remaining_ms, self.poll_seconds = min_remaining_ms, poll_seconds
            self.lease_key = namespace(maintenance_owner) + ":solver-bridge"
            self.lease_value = uuid.uuid4().hex
            self.lease_ttl = lifetime + math.ceil(min_remaining_ms / 1000) + 60
            if not self.connection.set(
                self.lease_key, self.lease_value, nx=True, ex=self.lease_ttl
            ):
                raise ValueError("Another bridge already owns the solver-consumer lease")

        def allowed(self):
            values = self.connection.pipeline(transaction=False)
            values.get(PAUSE)
            values.pttl(PAUSE)
            values.get(self.lease_key)
            values.get(self.stop_key)
            owner, ttl, lease, stop = values.execute()
            return (
                not self._stop_requested
                and time.monotonic() < self.until
                and owner == self.maintenance_owner.encode()
                and ttl > self.min_remaining_ms
                and lease == self.lease_value.encode()
                and stop != self.maintenance_owner.encode()
            )

        def handoff_ready(self):
            # Controller grants handoff only after observing old solver process exit.
            if self.connection.get(self.handoff_key) != self.maintenance_owner.encode():
                return False
            if self.connection.sismember("rq:workers", self.original_solver_key):
                return False
            if self.connection.hget(self.original_solver_key, "current_job"):
                return False
            return not self.original_execution_keys or not self.connection.exists(
                *self.original_execution_keys
            )

        def check_for_suspension(self, burst):
            if not self.allowed():
                raise StopRequested()
            self.heartbeat()

        def dequeue_job_and_maintain_ttl(self, timeout, max_idle_time=None):
            while self.allowed():
                if self.handoff_ready():
                    # Nonblocking attempt: return to ownership/deadline checks on every retry.
                    result = super().dequeue_job_and_maintain_ttl(None)
                    if result is not None:
                        return result
                elif time.monotonic() >= self.handoff_until:
                    raise StopRequested()
                self.heartbeat()
                time.sleep(self.poll_seconds)
            raise StopRequested()

        def close_maintenance_lease(self):
            self.connection.eval(
                "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
                1,
                self.lease_key,
                self.lease_value,
            )

    return SolverBridge
