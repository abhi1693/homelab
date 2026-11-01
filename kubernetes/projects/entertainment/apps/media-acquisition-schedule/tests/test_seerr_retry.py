"""Offline native-API-shape and persistent-claim regressions for Seerr retries."""
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo


SPEC = importlib.util.spec_from_file_location("seerr_retry", Path(__file__).resolve().parents[1] / "seerr_retry.py")
retry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retry)
IST = ZoneInfo("Asia/Kolkata")


def instant(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def active(now):
    local = now.astimezone(IST)
    start = local.replace(hour=22, minute=0, second=0, microsecond=0)
    if local.hour < 10:
        start -= timedelta(days=1)
    return (start.weekday() < 5 and start <= local < start + timedelta(hours=12))


def window(now):
    if not active(now):
        return None
    local = now.astimezone(IST)
    start = local.replace(hour=22, minute=0, second=0, microsecond=0)
    if local.hour < 10:
        start -= timedelta(days=1)
    return start.isoformat()


def request(request_id=1, created="2026-11-02T12:00:00+05:30", kind="movie"):
    return {"id": request_id, "status": 4, "type": kind, "createdAt": created,
            "updatedAt": "2026-11-02T22:04:00+05:30", "is4k": False,
            "serverId": 0, "tags": [], "seasons": [{"seasonNumber": 1, "status": 2}] if kind == "tv" else [],
            "media": {"id": request_id + 100, "tmdbId": request_id + 1000,
                      "mediaType": kind, "status": 3, "serviceId": 0}}


def detail(row, *, language="en", animation=False, countries=None, keywords=None):
    return {"id": row["media"]["tmdbId"], "originalLanguage": language,
            "genres": [{"id": 16 if animation else 18, "name": "Animation" if animation else "Drama"}],
            "productionCountries": [{"iso_3166_1": c} for c in (countries if countries is not None else ["US"])],
            "keywords": [] if keywords is None else keywords}


class Clock:
    def __init__(self, value="2026-11-02T22:05:00+05:30"):
        self.value = instant(value)

    def __call__(self):
        return self.value


class Store:
    def __init__(self):
        self.state = {"activationAt": "2026-10-31T12:30:00+00:00", "retryAttempts": {},
                      "unavailabilityIntervals": [], "unrelated": {"preserve": True}}
        self.saves = []
        self.fail_claim = False

    def load(self):
        return copy.deepcopy(self.state)

    def save(self, state):
        if self.fail_claim and any(x.get("outcome") == "claimed" for x in state.get("retryAttempts", {}).values()):
            raise RuntimeError("CAS conflict; no application POST permitted")
        self.state = copy.deepcopy(state)
        self.saves.append(copy.deepcopy(state))


class Api:
    def __init__(self, rows, store):
        self.rows = {r["id"]: copy.deepcopy(r) for r in rows}
        self.details = {r["media"]["tmdbId"]: detail(r) for r in rows}
        self.store = store
        self.calls = []
        self.posts = []
        self.on_call = None
        self.post_error = None
        self.verify_error = False
        self.bad_verification = False
        self.servers = [{"id": 0, "isDefault": True, "is4k": False}]

    def request(self, method, path, payload=None):
        self.calls.append((method, path))
        if self.on_call:
            self.on_call(method, path)
        if path.startswith("/settings/"):
            return copy.deepcopy(self.servers)
        parsed = urlsplit(path)
        if parsed.path == "/request":
            query = parse_qs(parsed.query)
            assert query["filter"] == ["failed"]
            assert query["sort"] == ["added"] and query["sortDirection"] == ["desc"]
            rows = [copy.deepcopy(x) for x in self.rows.values() if x["status"] == 4]
            skip, take = int(query["skip"][0]), int(query["take"][0])
            return {"pageInfo": {"results": len(rows)}, "results": rows[skip:skip + take]}
        if path.startswith(("/movie/", "/tv/")):
            item = self.details[int(path.rsplit("/", 1)[1])]
            if isinstance(item, Exception):
                raise item
            return copy.deepcopy(item)
        request_id = int(path.split("/")[2])
        if method == "POST":
            assert path == f"/request/{request_id}/retry" and payload is None
            claim = self.store.state["retryAttempts"][str(request_id)]
            assert claim["outcome"] == "claimed", "POST happened before persistent claim"
            self.posts.append(request_id)
            if self.post_error:
                raise self.post_error
            self.rows[request_id]["status"] = 2
            # Pinned Seerr subscriber approves existing child rows in place.
            if self.rows[request_id]["type"] == "tv":
                for season in self.rows[request_id]["seasons"]:
                    season["status"] = 2
            return copy.deepcopy(self.rows[request_id])
        if self.verify_error and request_id in self.posts:
            raise retry.SeerrError("response could contain secrets; must not be logged")
        if self.bad_verification and request_id in self.posts:
            return {"id": request_id, "status": 2}
        return copy.deepcopy(self.rows[request_id])


class RetryTests(unittest.TestCase):
    def setup_manager(self, rows=None, *, clock=None, options=None, monotonic=None):
        store = Store()
        api = Api(rows if rows is not None else [request()], store)
        clock = clock or Clock()
        settings = {"enabled": True, "pageSize": 50, "maxScan": 250, "maxAttempts": 10,
                    "intervalSeconds": 60, "maxRunSeconds": 10,
                    "managedServers": {"movie": 0, "tv": 0}}
        settings.update(options or {})
        manager = retry.RetryManager({"seerrRetry": settings}, store, active, window,
                                     transport=api, clock=clock, monotonic=monotonic)
        return manager, store, api, clock

    def test_offhours_request_is_claimed_before_native_retry_and_verified(self):
        manager, store, api, clock = self.setup_manager()
        result = manager.reconcile(clock())
        self.assertEqual((result["attempted"], result["verified"]), (1, 1))
        self.assertEqual(api.posts, [1])
        self.assertEqual(store.state["retryAttempts"]["1"]["outcome"], "verified")
        self.assertTrue(store.state["unrelated"]["preserve"])
        self.assertEqual([x for x in api.calls if x[0] != "GET"], [("POST", "/request/1/retry")])

    def test_old_failure_stays_unchanged_even_with_recent_updated_at(self):
        old = request(created="2026-10-30T12:00:00+05:30")
        manager, store, api, clock = self.setup_manager([old])
        manager.reconcile(clock())
        self.assertEqual(api.rows[1], old)
        self.assertEqual(api.posts, [])
        self.assertEqual(store.state["retryAttempts"], {})

    def test_failed_list_statuses_and_media_lifecycle_are_fail_closed(self):
        variants = []
        for status in (1, 2, 3, 5):
            row = request();row["status"] = status;variants.append(row)
        for status in (5, 6, 7, None):
            row = request();row["media"]["status"] = status;variants.append(row)
        row = request();row["seasons"] = [{"seasonNumber": 1, "status": 5}];variants.append(row)
        for row in variants:
            with self.subTest(row=row):
                manager, store, api, clock = self.setup_manager([row])
                before = copy.deepcopy(api.rows)
                manager.reconcile(clock())
                self.assertEqual(api.rows, before)
                self.assertEqual(api.posts, [])

    def test_partially_available_tv_request_keeps_completed_and_failed_original_seasons(self):
        row = request(kind="tv")
        row["media"]["status"] = 4
        row["media"]["externalServiceId"] = 225
        row["seasons"] = [{"id": 41, "seasonNumber": 1, "status": 5},
                          {"id": 42, "seasonNumber": 2, "status": 4}]
        manager, store, api, clock = self.setup_manager([row])
        before_seasons = copy.deepcopy(row["seasons"])
        result = manager.reconcile(clock())
        self.assertEqual((result["attempted"], result["verified"]), (1, 1))
        self.assertEqual([(s["id"], s["seasonNumber"]) for s in api.rows[1]["seasons"]],
                         [(s["id"], s["seasonNumber"]) for s in before_seasons])
        self.assertEqual([s["status"] for s in api.rows[1]["seasons"]], [2, 2])
        self.assertEqual(api.rows[1]["media"]["serviceId"], 0)
        self.assertEqual(api.rows[1]["media"]["externalServiceId"], 225)
        self.assertEqual(api.posts, [1])
        self.assertEqual([x for x in api.calls if x[0] == "POST"], [("POST", "/request/1/retry")])

    def test_declined_child_and_wholly_completed_tv_requests_stay_untouched(self):
        for case in ("declined_child", "completed_request", "all_children_completed", "missing_seasons"):
            with self.subTest(case=case):
                row = request(kind="tv")
                row["seasons"] = [{"seasonNumber": 1, "status": 5}, {"seasonNumber": 2, "status": 4}]
                if case == "declined_child":row["seasons"][1]["status"] = 3
                if case == "completed_request":row["status"] = 5
                if case == "all_children_completed":row["seasons"][1]["status"] = 5
                if case == "missing_seasons":row["seasons"] = []
                manager, _, api, clock = self.setup_manager([row])
                manager.reconcile(clock())
                self.assertEqual(api.posts, [])
                self.assertEqual(api.rows[1], row)

    def test_requested_tv_seasons_changing_between_list_and_detail_skip_this_attempt(self):
        manager, store, api, clock = self.setup_manager([request(kind="tv")])
        def change(method, path):
            if path == "/request/1":api.rows[1]["seasons"].append({"seasonNumber": 2, "status": 2})
        api.on_call = change
        manager.reconcile(clock())
        self.assertEqual(api.posts, [])
        self.assertEqual(store.state["retryAttempts"], {})

    def test_failures_created_during_healthy_open_window_are_not_retried(self):
        manager, _, api, clock = self.setup_manager([request(created="2026-11-02T22:01:00+05:30")])
        manager.reconcile(clock())
        self.assertEqual(api.posts, [])

    def test_managed_startup_interval_covers_after_22_request_and_is_end_exclusive(self):
        rows = [request(1, "2026-11-02T22:01:00+05:30"), request(2, "2026-11-02T22:03:00+05:30")]
        manager, store, api, clock = self.setup_manager(rows)
        store.state["unavailabilityIntervals"] = [{"start": "2026-10-31T04:30:00Z", "end": "2026-11-02T16:33:00Z"}]
        manager.reconcile(clock())
        self.assertEqual(api.posts, [1])

    def test_open_managed_interval_and_activation_boundary(self):
        row = request(created="2026-10-31T12:30:00Z")
        manager, store, api, clock = self.setup_manager([row])
        store.state["unavailabilityIntervals"] = [{"start": store.state["activationAt"], "end": None}]
        manager.reconcile(clock())
        self.assertEqual(api.posts, [1])

    def test_weekend_creation_retries_monday_but_friday_night_creation_does_not(self):
        rows = [request(1, "2026-11-01T23:00:00+05:30"), request(2, "2026-10-30T23:00:00+05:30")]
        manager, store, api, clock = self.setup_manager(rows)
        store.state["activationAt"] = "2026-10-29T00:00:00Z"
        manager.reconcile(clock())
        self.assertEqual(api.posts, [1])

    def test_saturday_early_window_is_fridays_but_saturday_night_is_closed(self):
        for value, expected in [("2026-10-31T09:59:00+05:30", True), ("2026-10-31T10:00:00+05:30", False), ("2026-10-31T22:00:00+05:30", False)]:
            with self.subTest(value=value):
                self.assertEqual(active(instant(value)), expected)

    def test_anime_and_uncertain_metadata_never_reach_retry(self):
        for kind in ("movie", "tv"):
            for case in ("explicit", "keyword", "japanese_animation", "uncertain", "missing_metadata", "wrong_identity"):
                with self.subTest(kind=kind, case=case):
                    row = request(kind=kind)
                    manager, _, api, clock = self.setup_manager([row])
                    metadata = api.details[row["media"]["tmdbId"]]
                    if case == "explicit":row["isAnime"] = True;api.rows[1] = row
                    elif case == "keyword":metadata["keywords"] = {"results": [{"id": 210024, "name": "anime"}]}
                    elif case == "japanese_animation":metadata.update(detail(row, language="ja", animation=True, countries=["JP"]))
                    elif case == "uncertain":metadata.update(detail(row, animation=True, countries=["JP"]))
                    elif case == "missing_metadata":metadata.pop("keywords")
                    elif case == "wrong_identity":metadata["id"] = 9999
                    manager.reconcile(clock())
                    self.assertEqual(api.posts, [])

    def test_pixar_animation_and_japanese_live_action_are_not_broadly_excluded(self):
        for language, animation, countries in [("en", True, ["US"]), ("ja", False, ["JP"])]:
            with self.subTest(language=language):
                row = request()
                manager, _, api, clock = self.setup_manager([row])
                api.details[row["media"]["tmdbId"]] = detail(row, language=language, animation=animation, countries=countries)
                manager.reconcile(clock())
                self.assertEqual(api.posts, [1])

    def test_manga_based_live_action_remains_eligible_without_anime_evidence(self):
        for language, countries in [("ja", ["JP"]), ("en", ["US"])]:
            with self.subTest(language=language):
                row = request(kind="tv")
                manager, _, api, clock = self.setup_manager([row])
                api.details[row["media"]["tmdbId"]] = detail(
                    row, language=language, animation=False, countries=countries,
                    keywords=[{"id": 99, "name": "based on manga"}],
                )
                result = manager.reconcile(clock())
                self.assertEqual(api.posts, [1])
                self.assertEqual(result["verified"], 1)

    def test_custom_server_4k_and_changed_default_are_skipped(self):
        for change in ("override", "media_override", "4k", "default"):
            with self.subTest(change=change):
                row = request()
                if change == "override":row["serverId"] = 1
                if change == "media_override":row["media"]["serviceId"] = 1
                if change == "4k":row["is4k"] = True
                manager, _, api, clock = self.setup_manager([row])
                if change == "default":api.servers[0]["id"] = 1
                manager.reconcile(clock())
                self.assertEqual(api.posts, [])

    def test_fresh_status_race_does_not_claim_or_reapprove_declined_request(self):
        manager, store, api, clock = self.setup_manager()
        def change(method, path):
            if path == "/request/1":api.rows[1]["status"] = 3
        api.on_call = change
        manager.reconcile(clock())
        self.assertEqual(api.posts, [])
        self.assertEqual(store.state["retryAttempts"], {})

    def test_available_race_and_identity_change_do_not_retry(self):
        for field in ("available", "identity"):
            with self.subTest(field=field):
                manager, store, api, clock = self.setup_manager()
                def change(method, path):
                    if path == "/request/1":
                        api.rows[1]["media"]["status" if field == "available" else "tmdbId"] = 5 if field == "available" else 9999
                api.on_call = change
                manager.reconcile(clock())
                self.assertEqual(api.posts, [])
                self.assertEqual(store.state["retryAttempts"], {})

    def test_timeout_claim_prevents_duplicate_even_after_restart_and_next_tick(self):
        manager, store, api, clock = self.setup_manager()
        api.post_error = TimeoutError("must not leak credentials or SQL")
        first = manager.reconcile(clock())
        self.assertEqual((first["attempted"], first["ambiguous"]), (1, 1))
        clock.value += timedelta(seconds=61)
        restarted = retry.RetryManager({"seerrRetry": {"enabled": True}}, store, active, window, transport=api, clock=clock)
        result = restarted.reconcile(clock())
        self.assertEqual(api.posts, [1])
        self.assertEqual(result["skipped"]["already_attempted"], 1)
        self.assertNotIn("credentials", json.dumps(result))

    def test_next_night_may_retry_still_failed_request_once(self):
        manager, store, api, clock = self.setup_manager()
        api.post_error = TimeoutError()
        manager.reconcile(clock())
        clock.value += timedelta(days=1)
        api.post_error = None
        manager.reconcile(clock())
        self.assertEqual(api.posts, [1, 1])
        self.assertEqual(store.state["retryAttempts"]["1"]["windowId"], window(clock()))

    def test_ack_without_verified_state_is_ambiguous(self):
        for condition in ("offline", "malformed", "still_failed"):
            with self.subTest(condition=condition):
                manager, store, api, clock = self.setup_manager()
                api.verify_error = condition == "offline"
                api.bad_verification = condition == "malformed"
                if condition == "still_failed":
                    def change(method, path):
                        if method == "GET" and path == "/request/1" and api.posts:api.rows[1]["status"] = 4
                    api.on_call = change
                result = manager.reconcile(clock())
                self.assertEqual((result["verified"], result["ambiguous"]), (0, 1))
                self.assertEqual(store.state["retryAttempts"]["1"]["outcome"], "ambiguous")

    def test_state_cas_failure_prevents_post(self):
        manager, store, api, clock = self.setup_manager()
        store.fail_claim = True
        result = manager.reconcile(clock())
        self.assertEqual(api.posts, [])
        self.assertEqual(result["reason"], "unavailable_or_state_conflict")

    def test_window_crossing_before_post_preserves_claim_without_sending(self):
        manager, store, api, clock = self.setup_manager(clock=Clock("2026-11-03T09:59:59+05:30"))
        original_save = store.save
        def close_after_claim(state):
            original_save(state)
            if any(x.get("outcome") == "claimed" for x in state["retryAttempts"].values()):
                clock.value = instant("2026-11-03T10:00:00+05:30")
        store.save = close_after_claim
        result = manager.reconcile(clock())
        self.assertEqual(api.posts, [])
        self.assertEqual(result["not_sent_window_closed"], 1)

    def test_window_crossing_during_post_does_not_claim_verified_delivery(self):
        manager, store, api, clock = self.setup_manager(clock=Clock("2026-11-03T09:59:59+05:30"))
        def close(method, path):
            if method == "POST":clock.value = instant("2026-11-03T10:00:00+05:30")
        api.on_call = close
        result = manager.reconcile(clock())
        self.assertEqual((result["verified"], result["ambiguous"]), (0, 1))
        self.assertEqual(api.posts, [1])

    def test_twenty_requests_are_paginated_but_only_ten_attempted_per_minute(self):
        manager, store, api, clock = self.setup_manager([request(i) for i in range(1, 21)], options={"pageSize": 3})
        result = manager.reconcile(clock())
        self.assertEqual((result["scanned"], result["attempted"]), (20, 10))
        calls = len(api.calls)
        self.assertEqual(manager.reconcile(clock())["reason"], "interval")
        self.assertEqual(len(api.calls), calls)
        clock.value += timedelta(seconds=60)
        self.assertEqual(manager.reconcile(clock())["attempted"], 10)
        self.assertEqual(len(set(api.posts)), 20)

    def test_scan_cursor_bounds_work_and_eventually_reaches_later_entries(self):
        rows = [request(i, "2026-10-30T12:00:00+05:30") for i in range(1, 281)] + [request(281)]
        manager, store, api, clock = self.setup_manager(rows)
        first = manager.reconcile(clock())
        self.assertEqual((first["scanned"], first["attempted"]), (250, 0))
        clock.value += timedelta(seconds=60)
        second = manager.reconcile(clock())
        self.assertEqual((second["scanned"], second["attempted"]), (31, 1))
        self.assertEqual(api.posts, [281])

    def test_ledger_memory_is_bounded_without_discarding_current_night_claims(self):
        manager, store, api, clock = self.setup_manager()
        store.state["retryAttempts"] = {str(i): {"windowId": window(clock()), "outcome": "ambiguous"} for i in range(2, 2002)}
        result = manager.reconcile(clock())
        self.assertEqual(api.posts, [])
        self.assertEqual(result["reason"], "ledger_full")
        self.assertEqual(len(store.state["retryAttempts"]), 2000)

    def test_missing_activation_disabled_and_outside_window_never_call_application(self):
        for mode in ("missing_activation", "disabled", "outside"):
            with self.subTest(mode=mode):
                clock = Clock("2026-11-02T12:00:00+05:30") if mode == "outside" else Clock()
                manager, store, api, clock = self.setup_manager(clock=clock, options={"enabled": mode != "disabled"})
                if mode == "missing_activation":store.state.pop("activationAt")
                manager.reconcile(clock())
                self.assertEqual(api.calls, [])

    def test_run_budget_stops_metadata_reads_and_posts(self):
        timer = iter([0, 0, 0, 0, 11, 11, 11])
        manager, _, api, clock = self.setup_manager(monotonic=lambda: next(timer, 11))
        manager.reconcile(clock())
        self.assertEqual(api.posts, [])

    def test_claim_persistence_exhausting_budget_does_not_send_late_post(self):
        elapsed = [0]
        manager, store, api, clock = self.setup_manager(monotonic=lambda: elapsed[0])
        original = store.save
        def slow_claim(state):
            original(state)
            if any(x.get("outcome") == "claimed" for x in state["retryAttempts"].values()):
                elapsed[0] = 11
        store.save = slow_claim
        result = manager.reconcile(clock())
        self.assertEqual(api.posts, [])
        self.assertEqual(result["not_sent_budget"], 1)

    def test_metadata_unavailable_and_unknown_future_dates_fail_closed(self):
        for case in ("offline", "future", "naive"):
            with self.subTest(case=case):
                row = request()
                if case == "future":row["createdAt"] = "2026-11-03T12:00:00+05:30"
                if case == "naive":row["createdAt"] = "2026-11-02T12:00:00"
                manager, _, api, clock = self.setup_manager([row])
                if case == "offline":api.details[row["media"]["tmdbId"]] = retry.SeerrError("unavailable")
                manager.reconcile(clock())
                self.assertEqual(api.posts, [])


class SeerrClientTests(unittest.TestCase):
    def client(self, opener):
        with mock.patch.dict(os.environ, {"JELLYSEERR_API_KEY": "private-test-key"}), mock.patch.object(retry, "build_opener", return_value=opener):
            return retry.SeerrClient({"timeoutSeconds": 3})

    def test_only_exact_retry_endpoint_accepts_post_and_redirects_are_disabled(self):
        opener = mock.Mock()
        client = self.client(opener)
        for path in ("/request", "/request/1/approve", "/request/1", "/movie/1", "/request/0/retry"):
            with self.subTest(path=path), self.assertRaises(retry.SeerrError):
                client.request("POST", path)
        with self.assertRaises(retry.SeerrError):
            client.request("POST", "/request/1/retry", {"status": 2})
        opener.open.assert_not_called()
        self.assertIsNone(retry._NoRedirect().redirect_request(None, None, 302, "", {}, "https://external.invalid"))

    def test_http_error_body_is_never_exposed_and_stream_is_closed(self):
        body = io.BytesIO(b"private-test-key confidential response body")
        opener = mock.Mock()
        opener.open.side_effect = HTTPError(retry.DEFAULT_BASE + "/request/1/retry", 502, "private-test-key", {}, body)
        client = self.client(opener)
        with self.assertRaises(retry.SeerrError) as caught:
            client.request("POST", "/request/1/retry")
        self.assertEqual(str(caught.exception), "http_502")
        self.assertTrue(body.closed)

    def test_unknown_base_or_missing_key_cannot_send_requests(self):
        with mock.patch.dict(os.environ, {"JELLYSEERR_API_KEY": "private-test-key"}):
            with self.assertRaises(ValueError):
                retry.SeerrClient({"baseUrl": "http://external.invalid/api/v1"})
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            retry.SeerrClient({})


if __name__ == "__main__":
    unittest.main()
