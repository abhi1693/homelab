"""Bounded Seerr 3.5 delivery retries for requests affected by scheduled downtime.

The only application mutation is POST /request/{id}/retry. A persistent claim
precedes it; an uncertain response never permits another attempt that night.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
import re
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_BASE = "http://jellyseerr.media.svc.cluster.local:10241/api/v1"
FAILED, APPROVED, COMPLETED = 4, 2, 5
UNAVAILABLE_MEDIA_STATES = {1, 2, 3, 4}
MAX_LEDGER_ENTRIES = 2000


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except ValueError:
        return None


def _positive_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _iso(value):
    return value.astimezone(timezone.utc).isoformat()


class SeerrError(Exception):
    """Carries no response body, URL, headers, or credentials."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class SeerrClient:
    def __init__(self, options):
        self.base = options.get("baseUrl", DEFAULT_BASE).rstrip("/")
        if self.base != DEFAULT_BASE:
            raise ValueError("Seerr retry base must be the managed internal service")
        self.key = os.environ.get(options.get("apiKeyEnv", "JELLYSEERR_API_KEY"), "")
        if not self.key:
            raise ValueError("Seerr retry API key is unavailable")
        self.timeout = max(0.1, min(5.0, float(options.get("timeoutSeconds", 3))))
        self.opener = build_opener(_NoRedirect())

    def request(self, method, path, payload=None):
        if method not in {"GET", "POST"} or not path.startswith("/"):
            raise SeerrError("unsupported_operation")
        if method == "POST" and not re.fullmatch(r"/request/[1-9][0-9]*/retry", path):
            raise SeerrError("unsupported_operation")
        if payload is not None:
            raise SeerrError("request_payload_not_allowed")
        request = Request(
            self.base + path,
            data=b"" if method == "POST" else None,
            method=method,
            headers={"X-Api-Key": self.key, "Accept": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                # Seerr's list/detail/metadata responses are bounded by this client.
                body = response.read(4 * 1024 * 1024 + 1)
                if len(body) > 4 * 1024 * 1024:
                    raise SeerrError("response_too_large")
                return json.loads(body)
        except HTTPError as exc:
            exc.close()
            raise SeerrError("http_" + str(exc.code)) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise SeerrError("request_failed") from None


def classify_anime(request, detail):
    """Return anime/non_anime/uncertain using explicit and TMDB evidence.

    Japanese language alone and Animation alone are insufficient. Metadata must
    include genres, original language and keywords before a negative result.
    """
    media = request.get("media", {})
    if any(obj.get("isAnime") is True for obj in (request, media, detail)):
        return "anime"
    for tag in request.get("tags") or []:
        label = tag.get("label", tag.get("name", "")) if isinstance(tag, dict) else tag
        if isinstance(label, str) and (label.lower() == "anime" or label.lower().startswith("anime-")):
            return "anime"
    if not _positive_id(detail.get("id")) or detail.get("id") != media.get("tmdbId"):
        return "uncertain"
    keywords = detail.get("keywords")
    if isinstance(keywords, dict):
        keywords = keywords.get("keywords", keywords.get("results"))
    if not isinstance(keywords, list) or any(
            not isinstance(k, dict) or not _positive_id(k.get("id"))
            or not isinstance(k.get("name"), str) for k in keywords):
        return "uncertain"
    if any(k.get("id") == 210024 or str(k.get("name", "")).lower() == "anime" for k in keywords):
        return "anime"
    genres = detail.get("genres")
    language = detail.get("originalLanguage")
    if (not isinstance(genres, list) or not genres
            or any(not isinstance(g, dict) or not _positive_id(g.get("id")) for g in genres)
            or not isinstance(language, str) or not re.fullmatch(r"[a-z]{2}", language)):
        return "uncertain"
    animation = any(g["id"] == 16 or g.get("name") == "Animation" for g in genres)
    if animation and language == "ja":
        return "anime"
    countries = detail.get("originCountry", [])
    production = detail.get("productionCountries", [])
    if not isinstance(countries, list) or not isinstance(production, list):
        return "uncertain"
    countries = [c for c in countries if isinstance(c, str)] + [
        c.get("iso_3166_1") for c in production if isinstance(c, dict)
    ]
    if animation and ("JP" in countries or not countries):
        return "uncertain"
    return "non_anime"


class RetryManager:
    def __init__(self, config, state_store, is_active, window_id, *, transport=None,
                 clock: Callable[[], datetime] | None = None, monotonic=None):
        self.options = copy.deepcopy(config.get("seerrRetry", {}))
        self.store = state_store
        self.is_active = is_active
        self.window_id = window_id
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic or time.monotonic
        self.client = transport
        self.max_scan = max(1, min(250, int(self.options.get("maxScan", 250))))
        self.max_attempts = max(1, min(10, int(self.options.get("maxAttempts", 10))))
        self.page_size = max(1, min(100, int(self.options.get("pageSize", 50))))
        self.interval = max(60, int(self.options.get("intervalSeconds", 60)))
        self.max_run = max(1, min(20, float(self.options.get("maxRunSeconds", 10))))

    def _open(self, instant, window):
        return (isinstance(instant, datetime) and instant.tzinfo is not None
                and self.is_active(instant) and self.window_id(instant) == window)

    def _affected(self, created, state):
        if not self.is_active(created):
            return True
        intervals = state.get("unavailabilityIntervals", [])
        if not isinstance(intervals, list):
            return False
        for interval in intervals:
            if not isinstance(interval, dict):
                continue
            start, end = _date(interval.get("start")), _date(interval.get("end"))
            if start and start <= created and ((interval.get("end") is None) or (end and created < end)):
                return True
        return False

    def _eligible(self, request, state):
        if not isinstance(request, dict) or not _positive_id(request.get("id")):
            return "invalid_request"
        if request.get("status") != FAILED:
            return "status_changed"
        created, activation = _date(request.get("createdAt")), _date(state.get("activationAt"))
        if not created or not activation or created < activation:
            return "outside_activation"
        if created > self.clock() or not self._affected(created, state):
            return "not_managed_downtime"
        media = request.get("media")
        kind = request.get("type")
        managed = self.options.get("managedServers", {"movie": 0, "tv": 0})
        if (kind not in ("movie", "tv") or not isinstance(media, dict)
                or media.get("mediaType") != kind or not _positive_id(media.get("id"))
                or not _positive_id(media.get("tmdbId"))):
            return "invalid_identity"
        if request.get("is4k") is not False or managed.get(kind) != 0:
            return "unmanaged_server"
        if request.get("serverId") not in (None, 0) or media.get("serviceId") not in (None, 0):
            return "unmanaged_server"
        if media.get("status") not in UNAVAILABLE_MEDIA_STATES:
            return "media_not_retryable"
        seasons = request.get("seasons", [])
        if not isinstance(seasons, list) or (kind == "tv" and (
                not seasons or any(not isinstance(s, dict)
                    or type(s.get("seasonNumber")) is not int or s["seasonNumber"] < 0
                    or s.get("status") not in {1, 2, 3, 4, 5} for s in seasons))):
            return "invalid_seasons"
        # Native Seerr retries exactly these originally requested season numbers.
        # Completed older seasons can coexist with an undelivered new season;
        # a declined season must never be implicitly reapproved by that endpoint.
        if any(s.get("status") == 3 for s in seasons if isinstance(s, dict)):
            return "season_not_retryable"
        if seasons and all(isinstance(s, dict) and s.get("status") == 5 for s in seasons):
            return "season_not_retryable"
        return None

    @staticmethod
    def _identity(request):
        media = request.get("media", {})
        if not isinstance(media, dict):
            return None
        return (request.get("id"), request.get("type"), request.get("createdAt"),
                media.get("id"), media.get("tmdbId"), request.get("is4k"),
                tuple(sorted(s.get("seasonNumber") for s in request.get("seasons", []) if isinstance(s, dict))))

    def _finish(self, request_id, window, outcome, summary):
        state = self.store.load()
        record = state.get("retryAttempts", {}).get(str(request_id))
        if not isinstance(record, dict) or record.get("windowId") != window:
            return
        record.update({"outcome": outcome, "checkedAt": _iso(self.clock())})
        self.store.save(state)
        summary[outcome] = summary.get(outcome, 0) + 1

    def reconcile(self, now):
        summary = {"scanned": 0, "attempted": 0, "verified": 0, "ambiguous": 0, "skipped": {}}
        if not self.options.get("enabled", False):
            return {**summary, "reason": "disabled"}
        window = self.window_id(now)
        if not window or not self._open(now, window) or not self._open(self.clock(), window):
            return {**summary, "reason": "outside_window"}
        deadline = self.monotonic() + self.max_run

        def live():
            return self.monotonic() < deadline and self._open(self.clock(), window)

        def skip(reason):
            summary["skipped"][reason] = summary["skipped"].get(reason, 0) + 1

        try:
            state = self.store.load()
            activation = state.get("activationAt")
            if not _date(activation):
                return {**summary, "reason": "missing_activation"}
            last = _date(state.get("lastRetryReconcileAt"))
            if last and (now - last).total_seconds() < self.interval:
                return {**summary, "reason": "interval"}
            state["lastRetryReconcileAt"] = _iso(now)
            # Older-night claims are unnecessary for the per-night safety rule.
            ledger = state.get("retryAttempts", {})
            if not isinstance(ledger, dict):
                return {**summary, "reason": "invalid_ledger"}
            state["retryAttempts"] = {
                k: v for k, v in ledger.items()
                if isinstance(v, dict) and v.get("windowId") == window
            }
            cursor = state.get("retryScanCursor", 0)
            cursor = cursor if isinstance(cursor, int) and cursor >= 0 else 0
            self.store.save(state)
            if self.client is None:
                self.client = SeerrClient(self.options)
            # Verify server zero is still the actual default primary on both types.
            for kind in ("movie", "tv"):
                if not live():
                    return {**summary, "reason": "window_or_budget"}
                servers = self.client.request("GET", "/settings/" + ("radarr" if kind == "movie" else "sonarr"))
                if (not isinstance(servers, list) or not any(
                        s.get("id") == 0 and s.get("isDefault") is True and s.get("is4k") is False
                        for s in servers if isinstance(s, dict))):
                    return {**summary, "reason": "managed_default_changed"}
            candidates = []
            total = None
            while summary["scanned"] < self.max_scan and live():
                take = min(self.page_size, self.max_scan - summary["scanned"])
                page = self.client.request("GET", "/request?" + urlencode({
                    "take": take, "skip": cursor, "filter": "failed", "sort": "added", "sortDirection": "desc",
                }))
                rows = page.get("results") if isinstance(page, dict) else None
                count = page.get("pageInfo", {}).get("results") if isinstance(page, dict) else None
                if (not isinstance(rows, list) or len(rows) > take or not isinstance(count, int)
                        or isinstance(count, bool) or count < 0):
                    return {**summary, "reason": "invalid_page"}
                total = count
                summary["scanned"] += len(rows)
                candidates.extend(rows)
                cursor += len(rows)
                if not rows or cursor >= total:
                    cursor = 0
                    break
            current = self.store.load()
            if current.get("activationAt") != activation:
                return {**summary, "reason": "activation_changed"}
            current["retryScanCursor"] = cursor
            self.store.save(current)
            seen = set()
            for candidate in candidates:
                if summary["attempted"] >= self.max_attempts or not live():
                    break
                state = self.store.load()
                reason = self._eligible(candidate, state)
                if reason:
                    skip(reason)
                    continue
                request_id = candidate["id"]
                if request_id in seen:
                    continue
                seen.add(request_id)
                existing = state.get("retryAttempts", {}).get(str(request_id), {})
                if existing.get("windowId") == window:
                    skip("already_attempted")
                    continue
                kind = candidate["type"]
                detail = self.client.request("GET", "/" + kind + "/" + str(candidate["media"]["tmdbId"]))
                if not isinstance(detail, dict):
                    skip("uncertain_metadata")
                    continue
                classification = classify_anime(candidate, detail)
                if classification != "non_anime":
                    skip(classification)
                    continue
                if not live():
                    break
                fresh = self.client.request("GET", "/request/" + str(request_id))
                state = self.store.load()
                reason = self._eligible(fresh, state)
                if reason or self._identity(fresh) != self._identity(candidate):
                    skip(reason or "identity_changed")
                    continue
                if classify_anime(fresh, detail) != "non_anime":
                    skip("classification_changed")
                    continue
                if state.get("activationAt") != activation or not live():
                    break
                ledger = state.get("retryAttempts", {})
                if not isinstance(ledger, dict):
                    return {**summary, "reason": "invalid_ledger"}
                if ledger.get(str(request_id), {}).get("windowId") == window:
                    skip("already_attempted")
                    continue
                if len(ledger) >= MAX_LEDGER_ENTRIES:
                    return {**summary, "reason": "ledger_full"}
                ledger[str(request_id)] = {"windowId": window, "claimedAt": _iso(self.clock()),
                    "createdAt": fresh["createdAt"], "mediaId": fresh["media"]["id"],
                    "tmdbId": fresh["media"]["tmdbId"], "type": fresh["type"], "outcome": "claimed"}
                state["retryAttempts"] = ledger
                self.store.save(state)  # CAS failure or uncertain persistence MUST prevent POST.
                if not live():
                    outcome = "not_sent_window_closed" if not self._open(self.clock(), window) else "not_sent_budget"
                    self._finish(request_id, window, outcome, summary)
                    break
                summary["attempted"] += 1
                try:
                    self.client.request("POST", "/request/" + str(request_id) + "/retry")
                    if not live():
                        self._finish(request_id, window, "ambiguous", summary)
                        break
                    verified = self.client.request("GET", "/request/" + str(request_id))
                    if (isinstance(verified, dict) and verified.get("id") == request_id
                            and self._identity(verified) == self._identity(fresh)
                            and verified.get("status") in (APPROVED, COMPLETED)
                            and verified.get("media", {}).get("status") in {1, 2, 3, 4, 5}):
                        self._finish(request_id, window, "verified", summary)
                    else:
                        self._finish(request_id, window, "ambiguous", summary)
                except Exception:
                    self._finish(request_id, window, "ambiguous", summary)
        except Exception:
            # No raw exception text: HTTP bodies/credentials must never enter logs.
            return {**summary, "reason": "unavailable_or_state_conflict"}
        return summary
