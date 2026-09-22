"""Resolve private Next.js maps whose Turbopack hash differs from the JS hash."""

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ORIGINS = {
    "portfolio": "http://portfolio.portfolio.svc.cluster.local:3000",
    "personal-blog": "http://personal-blog.personal-blog.svc.cluster.local:3000",
    "shipyardhq": "http://shipyardhq.shipyardhq.svc.cluster.local:3000",
    "wardn-hub": "http://wardn-hub-frontend.wardn.svc.cluster.local:3000",
}
MAX_BYTES = 8 * 1024 * 1024
SLOTS = threading.BoundedSemaphore(4)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=3) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("asset exceeds size limit")
    return body


def asset_path(request_path):
    parsed = urllib.parse.urlsplit(request_path)
    path = urllib.parse.unquote(parsed.path)
    parts = path.lstrip("/").split("/")
    if (
        parsed.query or parsed.fragment or parsed.netloc or parsed.scheme
        or len(parts) < 5 or parts[0] not in ORIGINS
        or parts[1:3] != ["_next", "static"]
        or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in (".", "..") for part in parts)
        or not path.endswith(".js.map")
    ):
        raise ValueError("invalid asset path")
    return ORIGINS[parts[0]], "/" + "/".join(parts[1:])


def resolve(request_path, get=fetch):
    origin, expected = asset_path(request_path)
    private = origin + "/faro-sourcemaps"
    try:
        body = get(private + expected)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        javascript = get(origin + expected[:-4]).decode("utf-8")
        matches = re.findall(r"(?m)^\s*//#\s*sourceMappingURL=([^\s]+)\s*$", javascript)
        if not matches or not re.fullmatch(r"[A-Za-z0-9_-]+\.js\.map", matches[-1]):
            raise ValueError("no safe relative source map reference")
        body = get(private + expected.rsplit("/", 1)[0] + "/" + matches[-1])
    source_map = json.loads(body)
    if not isinstance(source_map, dict) or source_map.get("version") != 3:
        raise ValueError("invalid source map")
    return body


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            return
        if not SLOTS.acquire(blocking=False):
            self.send_error(503)
            return
        try:
            body = resolve(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=300")
            self.end_headers()
            self.wfile.write(body)
        except (ValueError, urllib.error.HTTPError) as error:
            status = 404 if isinstance(error, ValueError) or error.code == 404 else 502
            self.send_error(status)
        except (OSError, urllib.error.URLError):
            self.send_error(502)
        finally:
            SLOTS.release()

    def log_message(self, format, *args):
        # Never log source map bodies, browser metadata, or full asset paths.
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 12348), Handler).serve_forever()
