"""Offline lifecycle tests for the named acquisition schedule controller."""

import contextlib
import copy
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("acquisition_controller", DIRECTORY / "controller.py")
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)


def config():
    return {"enabled": True, "namespace": "media", "timezone": "Asia/Kolkata",
            "start": "22:00", "end": "10:00", "startWeekdays": [0, 1, 2, 3, 4],
            "intervalSeconds": 15, "startupPhases": copy.deepcopy(c.PHASES),
            "cronJobs": list(c.CRONJOBS), "seerrRetry": {"enabled": False}}


def moment(value):
    return datetime.fromisoformat(value)


class Clock:
    def __init__(self, value="2026-11-02T22:00:00+05:30"):
        self.value = moment(value)

    def __call__(self):
        return self.value


def deployment(name, replicas=0):
    return {"metadata": {"name": name, "generation": 1}, "spec": {"replicas": replicas},
            "status": {"observedGeneration": 1, "replicas": replicas, "readyReplicas": replicas,
                       "updatedReplicas": replicas, "terminatingReplicas": 0}}


class FakeAPI:
    namespace = "media"

    def __init__(self, replicas=0, *, auto_ready=True, auto_stop=True):
        self.deployments = {name: deployment(name, replicas) for name in c.TARGETS}
        self.jobs = {name: {"spec": {"suspend": not bool(replicas)}} for name in c.CRONJOBS}
        self.auto_ready, self.auto_stop = auto_ready, auto_stop
        self.mutations, self.failures, self.on_get = [], {}, None

    def fail(self, operation, name):
        error = self.failures.pop((operation, name), None)
        if error:
            raise error

    def get_deployment(self, name):
        self.fail("get_deployment", name)
        if self.on_get:
            self.on_get(name)
        return copy.deepcopy(self.deployments[name])

    def mark_ready(self, name):
        d = self.deployments[name]
        d["status"].update({"observedGeneration": d["metadata"]["generation"], "replicas": 1,
                            "updatedReplicas": 1, "readyReplicas": 1, "terminatingReplicas": 0})

    def mark_stopped(self, name):
        d = self.deployments[name]
        d["status"].update({"observedGeneration": d["metadata"]["generation"], "replicas": 0,
                            "updatedReplicas": 0, "readyReplicas": 0, "terminatingReplicas": 0})

    def scale_deployment(self, name, replicas):
        self.fail("scale_deployment", name)
        self.mutations.append(("scale", name, replicas))
        d = self.deployments[name]
        d["spec"]["replicas"] = replicas
        d["metadata"]["generation"] += 1
        if replicas and self.auto_ready:
            self.mark_ready(name)
        elif not replicas and self.auto_stop:
            self.mark_stopped(name)
        elif not replicas:
            d["status"]["terminatingReplicas"] = 1
        return copy.deepcopy(d)

    def get_cronjob(self, name):
        self.fail("get_cronjob", name)
        return copy.deepcopy(self.jobs[name])

    def set_suspended(self, name, suspended):
        self.fail("set_suspended", name)
        self.mutations.append(("suspend", name, suspended))
        self.jobs[name]["spec"]["suspend"] = suspended
        return copy.deepcopy(self.jobs[name])


class MemoryStore:
    def __init__(self, state=None):
        self.state, self.saves, self.fail_load, self.fail_save = copy.deepcopy(state or {}), 0, False, False

    def load(self):
        if self.fail_load:
            raise ValueError("synthetic sensitive state detail")
        return copy.deepcopy(self.state)

    def save(self, state):
        if self.fail_save:
            raise c.StateConflict("synthetic conflict")
        self.state = copy.deepcopy(state)
        self.saves += 1


class RetrySpy:
    def __init__(self, *_):
        self.calls, self.error, self.on_call = [], None, None
        self.summary = {"scanned": 2, "attempted": 1, "verified": 1, "ambiguous": 0, "skipped": 1}

    def reconcile(self, now):
        self.calls.append(now)
        if self.on_call:
            self.on_call()
        if self.error:
            raise self.error
        return copy.deepcopy(self.summary)


class WindowTests(unittest.TestCase):
    def test_all_weekday_morning_and_evening_boundaries(self):
        monday = moment("2026-11-02T00:00:00+05:30")
        for day in range(7):
            date = monday + timedelta(days=day)
            for hour, minute, second, expected in [
                (0, 0, 0, (day - 1) % 7 < 5),
                (9, 59, 59, (day - 1) % 7 < 5),
                (10, 0, 0, False), (21, 59, 59, False), (22, 0, 0, day < 5),
                (23, 59, 59, day < 5),
            ]:
                now = date.replace(hour=hour, minute=minute, second=second)
                with self.subTest(now=now):
                    self.assertEqual(c.is_active(now, config()), expected)
                    self.assertEqual(c.window_id(now, config()) is not None, expected)

    def test_friday_to_saturday_and_sunday_monday(self):
        cfg = config()
        expected = "2026-11-06T22:00:00+05:30"
        self.assertEqual(c.window_id(moment("2026-11-07T09:59:59+05:30"), cfg), expected)
        for value in ["2026-11-07T10:00:00+05:30", "2026-11-07T22:00:00+05:30",
                      "2026-11-08T01:00:00+05:30", "2026-11-09T09:59:59+05:30"]:
            self.assertIsNone(c.window_id(moment(value), cfg))

    def test_utc_input_and_editable_overnight_schedule(self):
        self.assertTrue(c.is_active(moment("2026-11-02T16:30:00+00:00"), config()))
        self.assertFalse(c.is_active(moment("2026-11-03T04:30:00+00:00"), config()))
        cfg = config()
        cfg.update({"start": "23:30", "end": "09:45", "startWeekdays": [1, 3]})
        c.validate_config(cfg)
        self.assertTrue(c.is_active(moment("2026-11-06T09:44:59+05:30"), cfg))
        self.assertFalse(c.is_active(moment("2026-11-06T09:45:00+05:30"), cfg))

    def test_disabled_and_naive_datetime(self):
        cfg = config()
        cfg["enabled"] = False
        self.assertFalse(c.is_active(moment("2026-11-02T22:00:00+05:30"), cfg))
        with self.assertRaises(ValueError):
            c.is_active(datetime(2026, 11, 2, 22), config())

    def test_reject_unapproved_targets_and_invalid_configuration(self):
        for excluded in c.EXCLUDED:
            cfg = config()
            cfg["startupPhases"][0][0] = excluded
            with self.subTest(excluded=excluded), self.assertRaises(ValueError):
                c.validate_config(cfg)
        for key, value in [("namespace", "default"), ("startWeekdays", [True]),
                           ("startWeekdays", [0, 0]), ("start", "09:00"),
                           ("cronJobs", ["unrelated-job"]), ("intervalSeconds", 0)]:
            cfg = config()
            cfg[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                c.validate_config(cfg)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.clock, self.api, self.store, self.retry = Clock(), FakeAPI(), MemoryStore(), RetrySpy()

    def controller(self, cfg=None):
        return c.Controller(cfg or config(), self.api, self.store, clock=self.clock,
                            retry_factory=lambda *_: self.retry,
                            status_path=Path(self.temporary.name) / "status.json")

    def test_startup_phases_wait_for_ready_observed_generation(self):
        self.api.auto_ready = False
        controller = self.controller()
        self.assertEqual(controller.reconcile()["phase"], "starting")
        self.assertEqual(self.api.mutations, [("scale", "qbittorrent", 1), ("scale", "prowlarr", 1)])
        self.api.mark_ready("qbittorrent")
        self.api.mark_ready("prowlarr")
        self.api.deployments["qbittorrent"]["status"]["observedGeneration"] = 1
        controller.reconcile()
        self.assertEqual(len(self.api.mutations), 2)
        self.api.mark_ready("qbittorrent")
        for phase in c.PHASES[1:]:
            controller.reconcile()
            self.assertEqual([x[1] for x in self.api.mutations if x[0] == "scale"][-len(phase):], phase)
            self.assertFalse(self.retry.calls)
            for name in phase:
                self.api.mark_ready(name)
        status = controller.reconcile()
        self.assertTrue(status["appsReady"])
        self.assertEqual(status["requestRetries"], self.retry.summary)
        self.assertEqual(self.api.mutations[-3:], [("suspend", name, False) for name in c.CRONJOBS])
        self.assertEqual(len(self.retry.calls), 1)

    def test_ready_reconciliation_is_idempotent(self):
        controller = self.controller()
        controller.reconcile()
        mutations, saves = copy.deepcopy(self.api.mutations), self.store.saves
        controller.reconcile()
        self.assertEqual(self.api.mutations, mutations)
        self.assertEqual(self.store.saves, saves)
        self.assertEqual(set(self.api.deployments), set(c.TARGETS))

    def test_shutdown_suspends_helpers_then_waits_for_qbit_drain(self):
        self.api = FakeAPI(1, auto_stop=False)
        self.clock.value = moment("2026-11-03T10:00:00+05:30")
        controller = self.controller()
        self.assertEqual(controller.reconcile()["phase"], "stopping")
        self.assertEqual(self.api.mutations, [("suspend", name, True) for name in c.CRONJOBS] + [("scale", "qbittorrent", 0)])
        self.api.auto_stop = True
        self.api.mark_stopped("qbittorrent")
        self.assertEqual(controller.reconcile()["phase"], "paused")
        self.assertEqual([x[1] for x in self.api.mutations if x[0] == "scale"], list(c.TARGETS))

    def test_disabled_forces_pause_during_normal_open_window(self):
        self.api = FakeAPI(1)
        cfg = config()
        cfg["enabled"] = False
        status = self.controller(cfg).reconcile()
        self.assertEqual(status["phase"], "paused")
        self.assertTrue(all(x["spec"]["replicas"] == 0 for x in self.api.deployments.values()))
        self.assertFalse(self.retry.calls)

    def test_clock_crossing_during_get_never_starts_apps_after_cutoff(self):
        self.clock.value = moment("2026-11-03T09:59:59+05:30")
        self.api.on_get = lambda _: setattr(self.clock, "value", moment("2026-11-03T10:00:00+05:30"))
        status = self.controller().reconcile()
        self.assertFalse(any(x[0] == "scale" and x[2] == 1 for x in self.api.mutations))
        self.assertFalse(any(x[0] == "suspend" and x[2] is False for x in self.api.mutations))
        self.assertEqual(status["phase"], "paused")
        self.assertFalse(self.retry.calls)

    def test_clock_rechecked_after_status_heartbeat_before_patch(self):
        controller = self.controller()
        controller.status.update({"errors": [], "actions": []})
        values = iter([moment("2026-11-03T09:59:59+05:30"), moment("2026-11-03T10:00:00+05:30")])
        controller.clock = lambda: next(values)
        self.assertIsNone(controller.call("scale_deployment", "qbittorrent", 1))
        self.assertFalse(self.api.mutations)

    def test_restart_reconciles_missed_start_and_stop_edges(self):
        self.clock.value = moment("2026-11-03T03:00:00+05:30")
        self.assertEqual(self.controller().reconcile()["phase"], "ready")
        self.clock.value = moment("2026-11-03T11:00:00+05:30")
        self.assertEqual(self.controller().reconcile()["phase"], "paused")

    def test_partial_shutdown_errors_do_not_block_other_targets(self):
        self.api = FakeAPI(1)
        self.clock.value = moment("2026-11-03T10:00:00+05:30")
        self.api.failures[("get_cronjob", c.CRONJOBS[0])] = c.APIError("http_error", 503)
        self.api.failures[("get_deployment", "qbittorrent")] = c.APIError("transport_error")
        self.api.failures[("scale_deployment", "sonarr")] = c.APIError("http_error", 500)
        controller = self.controller()
        status = controller.reconcile()
        self.assertEqual(status["phase"], "stopping")
        self.assertEqual(self.api.deployments["radarr"]["spec"]["replicas"], 0)
        self.assertEqual(self.api.deployments["profilarr"]["spec"]["replicas"], 0)
        self.assertEqual(controller.reconcile()["phase"], "paused")

    def test_state_errors_cannot_prevent_off_window_shutdown(self):
        for failure in ("fail_load", "fail_save"):
            with self.subTest(failure=failure):
                self.api, self.store = FakeAPI(1), MemoryStore()
                setattr(self.store, failure, True)
                self.clock.value = moment("2026-11-03T10:00:00+05:30")
                status = self.controller().reconcile()
                self.assertEqual(status["phase"], "paused")
                self.assertTrue(status["healthy"])
                self.assertTrue(status["errors"])
                self.assertNotIn("synthetic sensitive", json.dumps(status))
                self.assertFalse(self.retry.calls)

    def test_retry_exception_and_cutoff_do_not_block_shutdown(self):
        controller = self.controller()
        self.retry.error = RuntimeError("synthetic private detail")
        status = controller.reconcile()
        self.assertEqual(status["phase"], "ready")
        self.assertNotIn("synthetic private", json.dumps(status))
        self.clock.value = moment("2026-11-03T10:00:00+05:30")
        self.assertEqual(controller.reconcile()["phase"], "paused")
        self.assertEqual(len(self.retry.calls), 1)

    def test_retry_finishing_across_cutoff_stops_in_same_cycle(self):
        self.clock.value = moment("2026-11-03T09:59:59+05:30")
        self.retry.on_call = lambda: setattr(self.clock, "value", moment("2026-11-03T10:00:00+05:30"))
        status = self.controller().reconcile()
        self.assertEqual(status["phase"], "paused")
        self.assertEqual(status["mode"], "off")
        self.assertFalse(status["appsReady"])

    def test_initial_activation_and_startup_interval_preserve_state(self):
        self.clock.value = moment("2026-10-31T17:00:00+05:30")
        self.store.state = {"unknown": {"keep": True}, "retryAttempts": {"keep": "attempt"}}
        controller = self.controller()
        controller.reconcile()
        activation = self.store.state["activationAt"]
        saves = self.store.saves
        controller.reconcile()
        self.assertEqual(self.store.saves, saves)
        self.assertIsNone(self.store.state["unavailabilityIntervals"][-1]["end"])
        self.clock.value = moment("2026-11-02T22:00:10+05:30")
        controller.reconcile()
        self.assertEqual(self.store.state["activationAt"], activation)
        self.assertEqual(self.store.state["unknown"], {"keep": True})
        self.assertEqual(self.store.state["retryAttempts"], {"keep": "attempt"})
        self.assertEqual(self.store.state["unavailabilityIntervals"][-1]["end"], c.iso(self.clock()))

    def test_delayed_initial_start_keeps_deployment_boundary_and_request_eligibility(self):
        cfg = config()
        cfg["activationAt"] = "2026-10-31T11:43:26+00:00"
        self.clock.value = moment("2026-10-31T11:50:00+00:00")
        self.api = FakeAPI(1)
        self.controller(cfg).reconcile()
        state = self.store.load()
        self.assertEqual(state["activationAt"], cfg["activationAt"])
        self.assertEqual(state["unavailabilityIntervals"][-1]["start"], cfg["activationAt"])

        # Exercise the actual retry eligibility guard with a request from the
        # rollout gap, without constructing a client or sending any HTTP call.
        spec = importlib.util.spec_from_file_location("boundary_retry", DIRECTORY / "seerr_retry.py")
        retry_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(retry_module)
        manager = retry_module.RetryManager(cfg, self.store,
            lambda now: c.is_active(now, cfg), lambda now: c.window_id(now, cfg), clock=self.clock)
        request = {"id": 1, "status": 4, "type": "movie", "createdAt": "2026-10-31T11:44:00+00:00",
                   "is4k": False, "serverId": 0, "seasons": [],
                   "media": {"id": 2, "tmdbId": 3, "mediaType": "movie", "status": 3, "serviceId": 0}}
        self.assertIsNone(manager._eligible(request, state))
        request["createdAt"] = "2026-10-31T11:43:25+00:00"
        self.assertEqual(manager._eligible(request, state), "outside_activation")

    def test_existing_activation_boundary_is_never_reset_by_configuration(self):
        self.clock.value = moment("2026-10-31T11:50:00+00:00")
        self.store.state = {"activationAt": "2026-10-31T11:43:26+00:00", "retryAttempts": {"preserve": "claim"}}
        cfg = config()
        cfg["activationAt"] = "2030-01-01T00:00:00+00:00"
        status = self.controller(cfg).reconcile()
        self.assertEqual(self.store.state["activationAt"], "2026-10-31T11:43:26+00:00")
        self.assertEqual(self.store.state["retryAttempts"], {"preserve": "claim"})
        self.assertFalse(status["errors"])

    def test_invalid_initial_activation_cannot_block_outside_window_shutdown(self):
        for boundary in ["2030-01-01T00:00:00+00:00", "2026-10-31T11:43:26", "invalid"]:
            with self.subTest(boundary=boundary):
                self.api, self.store = FakeAPI(1), MemoryStore()
                self.clock.value = moment("2026-10-31T11:50:00+00:00")
                cfg = config()
                cfg["activationAt"] = boundary
                status = self.controller(cfg).reconcile()
                self.assertEqual(status["phase"], "paused")
                self.assertTrue(status["errors"])
                self.assertEqual(self.store.saves, 0)
                self.assertFalse(self.retry.calls)
                self.assertTrue(all(x["spec"]["replicas"] == 0 for x in self.api.deployments.values()))

    def test_healthy_window_failure_does_not_create_retry_eligibility(self):
        controller = self.controller()
        controller.reconcile()
        intervals = copy.deepcopy(self.store.state["unavailabilityIntervals"])
        self.clock.value += timedelta(minutes=30)
        self.api.deployments["sonarr"]["status"]["readyReplicas"] = 0
        status = controller.reconcile()
        self.assertFalse(status["appsReady"])
        self.assertEqual(self.store.state["unavailabilityIntervals"], intervals)
        self.assertEqual(len(self.retry.calls), 1)

    def test_restart_after_missed_weekend_pause_covers_monday_startup_gap(self):
        self.clock.value = moment("2026-11-02T22:05:00+05:30")
        self.api.auto_ready = False
        self.store.state = {
            "activationAt": "2026-10-01T00:00:00+00:00",
            "readyWindowId": "2026-10-30T22:00:00+05:30",
            "unavailabilityIntervals": [], "retryAttempts": {},
        }
        controller = self.controller()
        controller.reconcile()
        interval = self.store.state["unavailabilityIntervals"][-1]
        self.assertEqual(interval["start"], "2026-10-31T04:30:00+00:00")
        self.assertIsNone(interval["end"])
        self.api.auto_ready = True
        self.api.mark_ready("qbittorrent")
        self.api.mark_ready("prowlarr")
        self.clock.value = moment("2026-11-02T22:06:00+05:30")
        controller.reconcile()
        interval = self.store.state["unavailabilityIntervals"][-1]
        created = moment("2026-11-02T22:02:00+05:30")
        self.assertLessEqual(moment(interval["start"]), created)
        self.assertGreater(moment(interval["end"]), created)
        self.assertEqual(interval["end"], c.iso(self.clock()))

    def test_off_interval_starts_at_boundary_and_old_intervals_are_bounded(self):
        self.clock.value = moment("2026-11-03T09:00:00+05:30")
        controller = self.controller()
        controller.reconcile()
        self.store.state["activationAt"] = "2026-10-01T00:00:00+00:00"
        self.store.state["unavailabilityIntervals"] = [
            {"start": c.iso(self.clock() - timedelta(hours=hour + 1)), "end": c.iso(self.clock() - timedelta(hours=hour))}
            for hour in reversed(range(40))
        ] + [{"start": "2026-10-02T00:00:00+00:00", "end": "2026-10-03T00:00:00+00:00"}]
        self.clock.value = moment("2026-11-03T10:00:08+05:30")
        controller.reconcile()
        intervals = self.store.state["unavailabilityIntervals"]
        self.assertLessEqual(len(intervals), 32)
        self.assertEqual(intervals[-1]["start"], "2026-11-03T04:30:00+00:00")
        self.assertTrue(all(not row["end"] or moment(row["end"]) >= self.clock() - timedelta(days=14) for row in intervals))

    def test_status_is_controller_health_not_application_readiness(self):
        self.api.auto_ready = False
        controller = self.controller()
        status = controller.reconcile()
        recorded = json.loads(controller.status_path.read_text())
        self.assertTrue(recorded["healthy"])
        self.assertFalse(recorded["appsReady"])
        self.assertEqual(recorded["phase"], "starting")
        self.assertEqual(recorded["lastReconcileAt"], status["lastReconcileAt"])
        self.assertIn("lastHeartbeatAt", recorded)

    def test_long_disabled_interval_is_clipped_before_retry_becomes_eligible(self):
        self.api = FakeAPI(1)
        self.store.state = {
            "activationAt": "2026-10-01T00:00:00+00:00", "retryAttempts": {},
            "unavailabilityIntervals": [{"start": "2026-10-01T00:00:00+00:00", "end": None}],
        }
        self.controller().reconcile()
        interval = self.store.state["unavailabilityIntervals"][-1]
        self.assertEqual(interval["start"], c.iso(self.clock() - timedelta(days=14)))
        self.assertEqual(interval["end"], c.iso(self.clock()))


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.token = Path(self.temporary.name) / "token"
        self.token.write_text("first-test-token")

    def test_token_rotation_and_only_named_scale_subresources(self):
        class Opener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout):
                self.requests.append((request, timeout))
                return io.BytesIO(b'{}')

        opener = Opener()
        api = c.KubernetesAPI(opener=opener, token_path=self.token)
        api.scale_deployment("sonarr", 0)
        self.token.write_text("rotated-test-token")
        api.get_deployment("sonarr")
        self.assertEqual(opener.requests[0][0].get_header("Authorization"), "Bearer first-test-token")
        self.assertEqual(opener.requests[1][0].get_header("Authorization"), "Bearer rotated-test-token")
        self.assertTrue(opener.requests[0][0].full_url.endswith("/deployments/sonarr/scale"))
        self.assertEqual(json.loads(opener.requests[0][0].data), {"spec": {"replicas": 0}})
        self.assertTrue(all(timeout <= 5 for _, timeout in opener.requests))
        for name in c.EXCLUDED:
            with self.assertRaises(ValueError):
                api.scale_deployment(name, 0)
        with self.assertRaises(ValueError):
            api.get_cronjob("unrelated")

    def test_transient_http_and_transport_errors_are_sanitized(self):
        for error in [urllib.error.HTTPError("https://internal/secret", 503, "private server detail", None, io.BytesIO(b'private body')),
                      urllib.error.URLError("private transport detail")]:
            class Opener:
                def open(self, *_args, **_kwargs):
                    raise error
            api = c.KubernetesAPI(opener=Opener(), token_path=self.token)
            with self.assertRaises(c.APIError) as caught:
                api.get_deployment("sonarr")
            self.assertNotIn("private", str(caught.exception))

    def test_state_store_resource_version_cas_and_unknown_keys(self):
        class API:
            namespace = "media"

            def __init__(self):
                self.calls, self.conflict = [], False

            def request(self, method, path, body=None):
                self.calls.append((method, path, body))
                if method == "GET":
                    return {"metadata": {"resourceVersion": "7"}, "data": {"state.json": '{"unknown":42}'}}
                if self.conflict:
                    raise c.StateConflict("http_conflict", 409)
                return {"metadata": {"resourceVersion": "8"}}

        api = API()
        store = c.StateStore(api)
        state = store.load()
        state["retryAttempts"] = {"request": "claimed"}
        store.save(state)
        body = api.calls[-1][2]
        self.assertEqual(body["metadata"]["resourceVersion"], "7")
        self.assertEqual(json.loads(body["data"]["state.json"])["unknown"], 42)
        self.assertEqual(store.resource_version, "8")
        self.assertEqual(api.calls[-1][1], "/api/v1/namespaces/media/configmaps/media-acquisition-schedule-state")
        api.conflict = True
        with self.assertRaises(c.StateConflict):
            store.save(state)
        self.assertEqual(store.resource_version, "8")


class CLITests(unittest.TestCase):
    def test_dry_run_with_clock_override_needs_no_kubernetes_or_seerr_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config()))
            output = io.StringIO()
            with patch.object(c, "KubernetesAPI", side_effect=AssertionError("must remain offline")), contextlib.redirect_stdout(output):
                self.assertEqual(c.main(["--config", str(path), "--once", "--dry-run", "--now", "2026-11-06T22:00:00+05:30"]), 0)
            plan = json.loads(output.getvalue())
            self.assertTrue(plan["active"])
            self.assertEqual(plan["desiredReplicas"], dict.fromkeys(c.TARGETS, 1))
            self.assertFalse(plan["helperCronJobsSuspended"])

    def test_clock_override_is_forbidden_for_live_runs(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            c.main(["--now", "2026-11-06T22:00:00+05:30"])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
