#!/usr/bin/env python3
"""Reconcile the named acquisition workloads against their overnight window."""

import argparse
import copy
import json
import os
import signal
import ssl
import threading
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

UTC = timezone.utc
PHASES = [
    ["qbittorrent", "prowlarr"],
    ["sonarr", "radarr"],
    ["episeerr", "profilarr"],
    ["qbittorrent-smart-queues"],
]
TARGETS = tuple(name for phase in PHASES for name in phase)
EXCLUDED = frozenset({"flaresolverr", "jellyfin", "jellyseerr", "ryokan", "shoko"})
CRONJOBS = (
    "qbittorrent-downloads-layout",
    "qbittorrent-state-backup",
    "qbittorrent-tracker-refresh",
)
STATE_NAME = "media-acquisition-schedule-state"


def utc_now():
    return datetime.now(UTC)


def iso(value):
    return value.astimezone(UTC).isoformat()


def aware(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware datetime is required")
    return value


def parse_time(value):
    if not isinstance(value, str) or len(value) != 5:
        raise ValueError("Schedule times must use HH:MM")
    parsed = time.fromisoformat(value)
    if parsed.isoformat(timespec="minutes") != value:
        raise ValueError("Schedule times must use HH:MM")
    return parsed


def validate_config(config):
    if config.get("namespace") != "media":
        raise ValueError("Only the media namespace is supported")
    if not isinstance(config.get("enabled"), bool):
        raise ValueError("enabled must be a boolean")
    ZoneInfo(config["timezone"])
    if parse_time(config["start"]) <= parse_time(config["end"]):
        raise ValueError("The schedule must be an overnight window")
    days = config["startWeekdays"]
    if not isinstance(days, list) or not days or any(type(x) is not int or x not in range(7) for x in days) or len(set(days)) != len(days):
        raise ValueError("startWeekdays must contain distinct weekdays from 0 to 6")
    phases = config["startupPhases"]
    if phases != PHASES or any(name in EXCLUDED for phase in phases for name in phase):
        raise ValueError("The seven approved startup targets and phases are required")
    jobs = config["cronJobs"]
    if not isinstance(jobs, list) or len(jobs) != len(CRONJOBS) or set(jobs) != set(CRONJOBS):
        raise ValueError("Only the three approved helper CronJobs are supported")
    if type(config["intervalSeconds"]) is not int or not 1 <= config["intervalSeconds"] <= 60:
        raise ValueError("intervalSeconds must be between 1 and 60")
    return copy.deepcopy(config)


def window_id(now, config):
    local = aware(now).astimezone(ZoneInfo(config["timezone"]))
    if not config["enabled"]:
        return None
    start, end = parse_time(config["start"]), parse_time(config["end"])
    if local.time() >= start:
        date = local.date()
    elif local.time() < end:
        date = local.date() - timedelta(days=1)
    else:
        return None
    if date.weekday() not in config["startWeekdays"]:
        return None
    return datetime.combine(date, start, local.tzinfo).isoformat()


def is_active(now, config):
    return window_id(now, config) is not None


def desired_plan(now, config):
    active = is_active(now, config)
    return {
        "dryRun": True,
        "now": iso(now),
        "active": active,
        "windowId": window_id(now, config),
        "desiredReplicas": dict.fromkeys(TARGETS, int(active)),
        "helperCronJobsSuspended": not active,
        "startupPhases": config["startupPhases"],
        "stopOrder": [["qbittorrent"], [name for name in TARGETS if name != "qbittorrent"]],
    }


class APIError(Exception):
    def __init__(self, kind, status=None):
        super().__init__(kind)
        self.kind, self.status = kind, status


class StateConflict(APIError):
    pass


class KubernetesAPI:
    def __init__(self, namespace="media", *, timeout=3, opener=None, base_url=None,
                 token_path="/var/run/secrets/kubernetes.io/serviceaccount/token",
                 ca_path="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"):
        if namespace != "media" or not 0 < timeout <= 5:
            raise ValueError("Invalid API namespace or timeout")
        host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
        if ":" in host and not host.startswith("["):
            host = "[" + host + "]"
        port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
        self.base_url = base_url or f"https://{host}:{port}"
        if not self.base_url.startswith("https://"):
            raise ValueError("The Kubernetes API must use HTTPS")
        self.namespace, self.timeout = namespace, timeout
        self.token_path = Path(token_path)
        self.opener = opener or urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=ca_path))
        )

    def request(self, method, path, body=None):
        headers = {"Authorization": "Bearer " + self.token_path.read_text().strip(), "Accept": "application/json"}
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/merge-patch+json"
            payload = json.dumps(body, separators=(",", ":")).encode()
        request = urllib.request.Request(self.base_url + path, data=payload, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1048577)
            if len(raw) > 1048576:
                raise APIError("response_too_large")
            return json.loads(raw)
        except urllib.error.HTTPError as error:
            error.close()
            if error.code == 409:
                raise StateConflict("http_conflict", 409) from None
            raise APIError("http_error", error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise APIError("transport_error") from None
        except (ValueError, UnicodeError):
            raise APIError("invalid_response") from None

    def deployment_path(self, name):
        if name not in TARGETS:
            raise ValueError("Unapproved deployment")
        return f"/apis/apps/v1/namespaces/{self.namespace}/deployments/{quote(name, safe='')}"

    def get_deployment(self, name):
        return self.request("GET", self.deployment_path(name))

    def scale_deployment(self, name, replicas):
        if type(replicas) is not int or replicas not in (0, 1):
            raise ValueError("Only zero or one replica is supported")
        return self.request("PATCH", self.deployment_path(name) + "/scale", {"spec": {"replicas": replicas}})

    def cronjob_path(self, name):
        if name not in CRONJOBS:
            raise ValueError("Unapproved CronJob")
        return f"/apis/batch/v1/namespaces/{self.namespace}/cronjobs/{quote(name, safe='')}"

    def get_cronjob(self, name):
        return self.request("GET", self.cronjob_path(name))

    def set_suspended(self, name, suspended):
        if not isinstance(suspended, bool):
            raise ValueError("suspend must be a boolean")
        return self.request("PATCH", self.cronjob_path(name), {"spec": {"suspend": bool(suspended)}})


class StateStore:
    def __init__(self, api):
        self.api, self.resource_version = api, None
        self.path = f"/api/v1/namespaces/{api.namespace}/configmaps/{STATE_NAME}"

    def load(self):
        document = self.api.request("GET", self.path)
        self.resource_version = document["metadata"]["resourceVersion"]
        state = json.loads(document.get("data", {}).get("state.json", "{}"))
        if not isinstance(state, dict):
            raise ValueError("Invalid controller state")
        return state

    def save(self, state):
        if self.resource_version is None:
            raise StateConflict("state_not_loaded")
        document = self.api.request("PATCH", self.path, {
            "metadata": {"resourceVersion": self.resource_version},
            "data": {"state.json": json.dumps(state, separators=(",", ":"))},
        })
        self.resource_version = document["metadata"]["resourceVersion"]


def ready(deployment):
    metadata, spec, status = deployment["metadata"], deployment["spec"], deployment.get("status", {})
    return (spec.get("replicas", 1) == 1
            and status.get("observedGeneration", 0) >= metadata["generation"]
            and status.get("readyReplicas", 0) >= 1
            and status.get("updatedReplicas", 0) >= 1
            and status.get("replicas", 0) == 1
            and status.get("terminatingReplicas", 0) == 0)


def stopped(deployment):
    metadata, spec, status = deployment["metadata"], deployment["spec"], deployment.get("status", {})
    return (spec.get("replicas", 1) == 0
            and status.get("observedGeneration", 0) >= metadata["generation"]
            and status.get("replicas", 0) == 0
            and status.get("terminatingReplicas", 0) == 0)


class Controller:
    def __init__(self, config, api, state_store, *, clock=utc_now, retry_factory=None,
                 status_path="/tmp/status.json"):
        self.config, self.api, self.state_store = validate_config(config), api, state_store
        self.clock, self.retry_factory, self.retry_manager = clock, retry_factory, None
        self.status_path = Path(status_path)
        self.status = {"healthy": True, "lastReconcileAt": None, "phase": "starting", "appsReady": False, "dryRun": False}

    def pulse(self):
        self.status["lastHeartbeatAt"] = iso(self.clock())
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.status_path.with_name(self.status_path.name + f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(self.status, separators=(",", ":")))
        temporary.replace(self.status_path)

    def call(self, operation, name, *args):
        self.pulse()
        if operation == "scale_deployment" and self.active() != bool(args[0]):
            return None
        if operation == "set_suspended" and self.active() == args[0]:
            return None
        try:
            return getattr(self.api, operation)(name, *args)
        except Exception as error:
            entry = {"operation": operation, "resource": name, "error": type(error).__name__}
            if isinstance(error, APIError):
                entry.update({"kind": error.kind, "status": error.status})
            self.status["errors"].append(entry)
            return None

    def active(self):
        return is_active(self.clock(), self.config)

    def scale(self, name, replicas, deployment):
        if deployment["spec"].get("replicas", 1) == replicas:
            return deployment
        if self.active() != bool(replicas):
            return None
        result = self.call("scale_deployment", name, replicas)
        if result is None:
            return None
        self.status["actions"].append({"deployment": name, "replicas": replicas})
        return self.call("get_deployment", name)

    def helpers(self, suspended):
        for name in self.config["cronJobs"]:
            if self.active() == suspended:
                return
            job = self.call("get_cronjob", name)
            if job is not None and bool(job.get("spec", {}).get("suspend", False)) != suspended:
                if self.active() == suspended:
                    return
                if self.call("set_suspended", name, suspended) is not None:
                    self.status["actions"].append({"cronJob": name, "suspended": suspended})

    def start(self):
        self.status["phase"] = "starting"
        for phase in self.config["startupPhases"]:
            phase_ready = True
            for name in phase:
                if not self.active():
                    return False
                deployment = self.call("get_deployment", name)
                if deployment is not None:
                    deployment = self.scale(name, 1, deployment)
                phase_ready = deployment is not None and ready(deployment) and phase_ready
            if not phase_ready:
                return False
        # Earlier phases can lose readiness while a later phase starts.
        for name in TARGETS:
            if not self.active():
                return False
            deployment = self.call("get_deployment", name)
            if deployment is None or not ready(deployment):
                return False
        self.helpers(False)
        return self.active()

    def stop(self):
        self.status["phase"] = "stopping"
        self.helpers(True)
        if self.active():
            return False
        deployment = self.call("get_deployment", "qbittorrent")
        failed = deployment is None
        if deployment is not None:
            deployment = self.scale("qbittorrent", 0, deployment)
            failed = deployment is None
        # An ordinary drain must finish before stopping its acquisition clients.
        # A failed API operation must not prevent best-effort shutdown elsewhere.
        if not failed and not stopped(deployment):
            return False
        all_stopped = not failed
        for name in TARGETS:
            if name == "qbittorrent":
                continue
            if self.active():
                return False
            deployment = self.call("get_deployment", name)
            if deployment is not None:
                deployment = self.scale(name, 0, deployment)
            all_stopped = deployment is not None and stopped(deployment) and all_stopped
        return all_stopped

    def state_transition(self, now, *, all_ready=False):
        self.pulse()
        state = self.state_store.load()
        original = copy.deepcopy(state)
        if "activationAt" not in state:
            # Validate initialization here so bad state configuration cannot
            # prevent an outside-window shutdown or invalidate an older ledger.
            activation = (aware(datetime.fromisoformat(self.config["activationAt"]))
                          if "activationAt" in self.config else now)
            if activation > now:
                raise ValueError("The activation boundary must not be in the future")
            state["activationAt"] = iso(activation)
        state.setdefault("retryAttempts", {})
        activation = aware(datetime.fromisoformat(state["activationAt"]))
        intervals = state.setdefault("unavailabilityIntervals", [])
        current = window_id(now, self.config)
        open_interval = next((x for x in intervals if x.get("end") is None), None)
        if current is None or state.get("readyWindowId") != current:
            if open_interval is None:
                start = now
                if self.config["enabled"]:
                    local = now.astimezone(ZoneInfo(self.config["timezone"]))
                    ends = [datetime.combine(local.date() - timedelta(days=days), parse_time(self.config["end"]), local.tzinfo)
                            for days in range(8)
                            if (local.date() - timedelta(days=days + 1)).weekday() in self.config["startWeekdays"]]
                    past = [end for end in ends if end <= now]
                    if past:
                        start = max(activation, max(past))
                open_interval = {"start": iso(max(start, activation)), "end": None}
                intervals.append(open_interval)
        if all_ready and current is not None:
            if open_interval is not None:
                open_interval["end"] = iso(now)
            state["readyWindowId"] = current
        if state != original:
            cutoff = now - timedelta(days=14)
            state["unavailabilityIntervals"] = [x for x in intervals
                if x.get("end") is None or datetime.fromisoformat(x["end"]) >= cutoff][-32:]
            for interval in state["unavailabilityIntervals"]:
                if datetime.fromisoformat(interval["start"]) < cutoff:
                    interval["start"] = iso(cutoff)
            self.state_store.save(state)
        return True

    def update_state(self, now, *, all_ready=False):
        try:
            return self.state_transition(now, all_ready=all_ready)
        except Exception as error:
            self.status["errors"].append({"operation": "state_transition", "error": type(error).__name__})
            return False

    def reconcile(self):
        now = aware(self.clock())
        self.status.update({"mode": "active" if is_active(now, self.config) else "off", "appsReady": False,
                            "errors": [], "actions": [], "requestRetries": None})
        state_ok = self.update_state(now)
        self.status["mode"] = "active" if self.active() else "off"
        if self.active():
            all_ready = self.start()
            if not self.active():
                self.status["mode"] = "off"
                self.update_state(self.clock())
                paused = self.stop()
                self.status["phase"] = "paused" if paused else "stopping"
            elif all_ready:
                self.status.update({"phase": "ready", "appsReady": True})
                state_ok = self.update_state(self.clock(), all_ready=True) and state_ok
                if state_ok and self.active():
                    try:
                        if self.retry_manager is None:
                            factory = self.retry_factory
                            if factory is None:
                                from seerr_retry import RetryManager
                                factory = RetryManager
                            self.retry_manager = factory(self.config, self.state_store,
                                lambda value: is_active(value, self.config), lambda value: window_id(value, self.config))
                        self.pulse()
                        if self.active():
                            self.status["requestRetries"] = self.retry_manager.reconcile(self.clock())
                    except Exception as error:
                        self.status["errors"].append({"operation": "seerr_retry", "error": type(error).__name__})
        else:
            paused = self.stop()
            self.status["phase"] = "paused" if paused else "stopping"
        # A bounded retry can finish across the cutoff; stop in this same cycle.
        if self.status["mode"] == "active" and not self.active():
            self.status.update({"mode": "off", "appsReady": False})
            self.update_state(self.clock())
            self.status["phase"] = "paused" if self.stop() else "stopping"
        self.status["lastReconcileAt"] = iso(self.clock())
        self.pulse()
        return copy.deepcopy(self.status)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/policy/config.json"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--now", help="Aware ISO timestamp; permitted only with --dry-run")
    args = parser.parse_args(argv)
    if args.now and not args.dry_run:
        parser.error("--now requires --dry-run")
    config = validate_config(json.loads(args.config.read_text()))
    fixed_now = aware(datetime.fromisoformat(args.now.replace("Z", "+00:00"))) if args.now else None
    if args.dry_run:
        print(json.dumps(desired_plan(fixed_now or utc_now(), config), separators=(",", ":")))
        return 0
    api = KubernetesAPI(config["namespace"])
    controller = Controller(config, api, StateStore(api))
    stopping = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopping.set())
    while not stopping.is_set():
        try:
            status = controller.reconcile()
            print(json.dumps({"event": "reconciled", **status}, separators=(",", ":")), flush=True)
        except Exception as error:
            print(json.dumps({"event": "controller_error", "error": type(error).__name__}), flush=True)
        if args.once:
            break
        stopping.wait(config["intervalSeconds"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
