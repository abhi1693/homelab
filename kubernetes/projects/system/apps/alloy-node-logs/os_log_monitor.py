#!/usr/bin/env python3
"""Read-only journal-canary query monitor; standard library only."""
from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

QUERY = (
    'sum by (node) (count_over_time({cluster="local",source="journal",unit="home-lab-log-canary"}'
    ' | json | SYSLOG_IDENTIFIER="home-lab-log-canary" [5m]))'
)
QUEUE_AVAILABLE_QUERY = (
    'min_over_time({cluster="local",source="journal",unit="home-lab-log-canary"}'
    ' | json | SYSLOG_IDENTIFIER="home-lab-log-canary"'
    ' | line_format "{{.MESSAGE}}" | json | unwrap queue_available_bytes'
    ' | __error__="" [5m]) by (node)'
)
QUEUE_CAPACITY_QUERY = (
    'max_over_time({cluster="local",source="journal",unit="home-lab-log-canary"}'
    ' | json | SYSLOG_IDENTIFIER="home-lab-log-canary"'
    ' | line_format "{{.MESSAGE}}" | json | unwrap queue_capacity_bytes'
    ' | __error__="" [5m]) by (node)'
)
DEFAULT_URL = (
    "http://loki-gateway.cattle-monitoring-system.svc.cluster.local"
    "/loki/api/v1/query"
)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_NODES = 4096
NODE_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z")


def parse_result(payload: object, now: float) -> dict[str, float]:
    """Reject errors, invalid samples and stale/cached vectors as one failed query."""
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ValueError("Loki query was not successful")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "vector":
        raise ValueError("Loki query did not return an instant vector")
    result = data.get("result")
    if not isinstance(result, list) or len(result) > MAX_NODES:
        raise ValueError("Invalid or oversized Loki result")
    counts: dict[str, float] = {}
    for series in result:
        if not isinstance(series, dict):
            raise ValueError("Invalid vector entry")
        metric, sample = series.get("metric"), series.get("value")
        node = metric.get("node") if isinstance(metric, dict) else None
        if not isinstance(node, str) or not NODE_PATTERN.fullmatch(node):
            raise ValueError("Invalid node identity")
        if node in counts:
            raise ValueError("Duplicate node identity")
        if not isinstance(sample, list) or len(sample) != 2:
            raise ValueError("Invalid vector sample")
        if isinstance(sample[0], bool) or isinstance(sample[1], bool):
            raise ValueError("Invalid numeric sample")
        sample_time, count = float(sample[0]), float(sample[1])
        if not math.isfinite(sample_time) or not now - 120 <= sample_time <= now + 30:
            raise ValueError("Stale or future Loki sample")
        if not math.isfinite(count) or count < 0:
            raise ValueError("Invalid canary count")
        counts[node] = count
    return counts


def prometheus_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class Monitor:
    def __init__(self, url: str = DEFAULT_URL, interval: float = 60, timeout: float = 10):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("LOKI_QUERY_URL must be an HTTP(S) URL without credentials")
        if parsed.query or parsed.fragment or not parsed.path.endswith("/loki/api/v1/query"):
            raise ValueError("LOKI_QUERY_URL must identify Loki's instant-query endpoint")
        if not 1 <= interval <= 3600 or not 0 < timeout <= 60:
            raise ValueError("Invalid polling interval or query timeout")
        self.url, self.interval, self.timeout = url, interval, timeout
        self.opener = build_opener(ProxyHandler({}))
        self.lock = threading.Lock()
        self.counts: dict[str, float] = {}
        self.queue_available: dict[str, float] = {}
        self.queue_capacity: dict[str, float] = {}
        self.query_success = False
        self.last_success = 0.0
        self.last_poll_monotonic = time.monotonic()
        self.stop = threading.Event()

    def query(self, expression: str, now: float) -> dict[str, float]:
        query = urlencode({"query": expression, "time": f"{now:.6f}"})
        request = Request(f"{self.url}?{query}", headers={"Accept": "application/json"}, method="GET")
        with self.opener.open(request, timeout=self.timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("Oversized Loki response")
        return parse_result(json.loads(raw), now)

    def poll_once(self) -> bool:
        try:
            now = time.time()
            counts = self.query(QUERY, now)
            available = self.query(QUEUE_AVAILABLE_QUERY, now)
            capacity = self.query(QUEUE_CAPACITY_QUERY, now)
        except (OSError, ValueError, TypeError, OverflowError) as error:
            if isinstance(error, HTTPError):
                error.close()
            # Do not expose the response body, URL or arbitrary error text in logs.
            print(f"OS log canary query failed: {type(error).__name__}", file=sys.stderr, flush=True)
            with self.lock:
                self.query_success = False
                self.counts = {}
                self.queue_available = {}
                self.queue_capacity = {}
                self.last_poll_monotonic = time.monotonic()
            return False
        with self.lock:
            self.counts = counts
            self.queue_available = available
            self.queue_capacity = capacity
            self.query_success = True
            self.last_success = time.time()
            self.last_poll_monotonic = time.monotonic()
        return True

    def run(self) -> None:
        while not self.stop.is_set():
            started = time.monotonic()
            self.poll_once()
            self.stop.wait(max(0, self.interval - (time.monotonic() - started)))

    def fresh(self) -> bool:
        return time.monotonic() - self.last_poll_monotonic <= self.interval * 2 + self.timeout

    def metrics(self) -> bytes:
        with self.lock:
            # Also fail closed if the polling worker stops advancing while HTTP survives.
            current = self.fresh()
            success = current and self.query_success
            counts = dict(self.counts) if success else {}
            queue_available = dict(self.queue_available) if success else {}
            queue_capacity = dict(self.queue_capacity) if success else {}
            last_success = self.last_success
        lines = [
            "# HELP os_log_monitor_query_success Most recent Loki query was valid and fresh.",
            "# TYPE os_log_monitor_query_success gauge",
            f"os_log_monitor_query_success {int(success)}",
            "# HELP os_log_monitor_last_success_time_seconds Unix time of the last successful query.",
            "# TYPE os_log_monitor_last_success_time_seconds gauge",
            f"os_log_monitor_last_success_time_seconds {last_success:.6f}",
            "# HELP os_log_canary_recent_records Journal canary records per node in the last five minutes.",
            "# TYPE os_log_canary_recent_records gauge",
        ]
        for node, count in sorted(counts.items()):
            lines.append(f'os_log_canary_recent_records{{node="{prometheus_escape(node)}"}} {count:g}')
        for metric, description, samples in (
            ("os_log_queue_available_bytes", "Minimum spool filesystem free bytes reported in the last five minutes.", queue_available),
            ("os_log_queue_capacity_bytes", "Maximum spool filesystem capacity bytes reported in the last five minutes.", queue_capacity),
        ):
            lines.extend([f"# HELP {metric} {description}", f"# TYPE {metric} gauge"])
            for node, value in sorted(samples.items()):
                lines.append(f'{metric}{{node="{prometheus_escape(node)}"}} {value:.17g}')
        return ("\n".join(lines) + "\n").encode()


def handler_for(monitor: Monitor) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/metrics":
                body, status = monitor.metrics(), 200
                content_type = "text/plain; version=0.0.4; charset=utf-8"
            elif self.path == "/healthz":
                # Health checks observe the monitor worker, not Loki's availability.
                body, status = (b"ok\n", 200) if monitor.fresh() else (b"poller stale\n", 503)
                content_type = "text/plain; charset=utf-8"
            else:
                body, status, content_type = b"not found\n", 404, "text/plain; charset=utf-8"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            return

    return Handler


def main() -> None:
    monitor = Monitor(
        os.environ.get("LOKI_QUERY_URL", DEFAULT_URL),
        float(os.environ.get("POLL_INTERVAL_SECONDS", "60")),
        float(os.environ.get("QUERY_TIMEOUT_SECONDS", "10")),
    )
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("HTTP_PORT", "9091"))), handler_for(monitor))
    thread = threading.Thread(target=monitor.run, name="loki-query", daemon=True)
    thread.start()
    try:
        server.serve_forever()
    finally:
        monitor.stop.set()
        server.server_close()
        thread.join(timeout=monitor.timeout + 1)


if __name__ == "__main__":
    main()
