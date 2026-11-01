#!/usr/bin/env python3
"""Exercise Loki query success, failure, staleness and safe exposition locally."""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os_log_monitor as subject


def vector(nodes=None, timestamp=None):
    return {"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"node": node}, "value": [time.time() if timestamp is None else timestamp, value]}
        for node, value in (nodes if nodes is not None else [("server1", "4"), ("rpi3", "5")])
    ]}}


@contextmanager
def fixture():
    state = {"status": 200, "body": vector(), "paths": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["paths"].append(self.path)
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            expression = parse_qs(urlsplit(self.path).query).get("query", [""])[0]
            payload = state.get("by_query", {}).get(expression, state["body"])
            self.wfile.write(payload if isinstance(payload, bytes) else json.dumps(payload).encode())

        def log_message(self, _format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}/loki/api/v1/query"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


class MonitorTest(unittest.TestCase):
    def test_query_and_exposition(self):
        with fixture() as (state, url):
            monitor = subject.Monitor(url)
            self.assertTrue(monitor.poll_once())
            query = parse_qs(urlsplit(state["paths"][0]).query)
            self.assertEqual(query["query"], [subject.QUERY])
            self.assertEqual(urlsplit(state["paths"][0]).path, "/loki/api/v1/query")
            self.assertIn('os_log_canary_recent_records{node="rpi3"} 5', monitor.metrics().decode())
            self.assertIn("os_log_monitor_query_success 1", monitor.metrics().decode())
            self.assertGreater(monitor.last_success, 0)

    def test_backend_and_parser_failures_clear_prior_green(self):
        with fixture() as (state, url):
            monitor = subject.Monitor(url)
            for bad_status, bad_body in [
                (503, b"unavailable"), (200, b"not-json"),
                (200, {"status": "error", "error": "query failed"}),
                (200, vector(timestamp=time.time() - 121)),
                (200, vector(timestamp=time.time() + 31)),
            ]:
                state.update(status=200, body=vector())
                self.assertTrue(monitor.poll_once())
                previous = monitor.last_success
                state.update(status=bad_status, body=bad_body)
                self.assertFalse(monitor.poll_once())
                metrics = monitor.metrics().decode()
                self.assertIn("os_log_monitor_query_success 0", metrics)
                self.assertNotIn('os_log_canary_recent_records{node=', metrics)
                self.assertEqual(monitor.last_success, previous)

    def test_empty_success_does_not_retain_missing_node(self):
        with fixture() as (state, url):
            monitor = subject.Monitor(url)
            self.assertTrue(monitor.poll_once())
            state["body"] = vector([])
            self.assertTrue(monitor.poll_once())
            self.assertIn("os_log_monitor_query_success 1", monitor.metrics().decode())
            self.assertNotIn('os_log_canary_recent_records{node=', monitor.metrics().decode())

    def test_queue_geometry_and_partial_query_failure(self):
        with fixture() as (state, url):
            state["by_query"] = {
                subject.QUEUE_AVAILABLE_QUERY: vector([("server1", "2147483648")]),
                subject.QUEUE_CAPACITY_QUERY: vector([("server1", "4294967296")]),
            }
            monitor = subject.Monitor(url)
            self.assertTrue(monitor.poll_once())
            metrics = monitor.metrics().decode()
            self.assertIn('os_log_queue_available_bytes{node="server1"} 2147483648', metrics)
            self.assertIn('os_log_queue_capacity_bytes{node="server1"} 4294967296', metrics)
            state["by_query"][subject.QUEUE_CAPACITY_QUERY] = {"status": "error"}
            self.assertFalse(monitor.poll_once())
            metrics = monitor.metrics().decode()
            self.assertIn("os_log_monitor_query_success 0", metrics)
            self.assertNotIn('os_log_canary_recent_records{node=', metrics)
            self.assertNotIn('os_log_queue_available_bytes{node=', metrics)

    def test_poll_worker_stall_fails_closed_at_scrape(self):
        with fixture() as (_state, url):
            monitor = subject.Monitor(url)
            self.assertTrue(monitor.poll_once())
            with patch.object(subject.time, "monotonic", return_value=monitor.last_poll_monotonic + 131):
                self.assertFalse(monitor.fresh())
                self.assertIn("os_log_monitor_query_success 0", monitor.metrics().decode())
                self.assertNotIn('os_log_canary_recent_records{node=', monitor.metrics().decode())

    def test_rejects_invalid_vector_samples(self):
        cases = [
            vector([("node\\\"\nattack", "2")]), vector([("server1", "NaN")]),
            vector([("server1", "Inf")]), vector([("server1", "-1")]),
            vector([("server1", "1"), ("server1", "2")]),
            {"status": "success", "data": {"resultType": "matrix", "result": []}},
        ]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                subject.parse_result(payload, time.time())
        self.assertEqual(subject.prometheus_escape('a\\b"c\nd'), 'a\\\\b\\"c\\nd')

    def test_response_size_limit_clears_result(self):
        with fixture() as (state, url):
            monitor = subject.Monitor(url)
            self.assertTrue(monitor.poll_once())
            with patch.object(subject, "MAX_RESPONSE_BYTES", 100):
                self.assertFalse(monitor.poll_once())
            self.assertEqual(monitor.counts, {})

    def test_metrics_and_health_http_endpoints(self):
        monitor = subject.Monitor()
        server = ThreadingHTTPServer(("127.0.0.1", 0), subject.handler_for(monitor))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/healthz") as response:
                self.assertEqual(response.status, 200)
            with urlopen(base + "/metrics") as response:
                self.assertIn(b"os_log_monitor_query_success 0", response.read())
            monitor.last_poll_monotonic -= 131
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/healthz")
            self.assertEqual(error.exception.code, 503)
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main()
