#!/usr/bin/env bash
set -euo pipefail
image=${1:?image reference required}
name="episeerr-smoke-${RANDOM}"
cleanup() {
  docker logs --tail 20 "$name" || true
  docker stop "$name" >/dev/null || true
}
trap cleanup EXIT
docker run --rm -d --name "$name" --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges \
  --tmpfs /tmp:uid=1000,gid=1000 \
  --tmpfs /app/config:uid=1000,gid=1000 \
  --tmpfs /app/data:uid=1000,gid=1000 \
  --tmpfs /app/logs:uid=1000,gid=1000 \
  --tmpfs /app/temp:uid=1000,gid=1000 \
  -e REQUIRE_AUTH=true -e AUTH_BYPASS_LOCALHOST=false \
  -e AUTH_USERNAME=smoke -e AUTH_PASSWORD=smoke-only-not-a-real-credential \
  -e TZ=Asia/Kolkata "$image" >/dev/null
# Probe from inside the container so no host port is exposed.
docker exec -i "$name" python - <<'PY'
import os
import time
import urllib.error
import urllib.request
assert os.getuid() == 1000
assert time.strftime('%z') == '+0530', 'timezone data missing'
for _ in range(60):
    try:
        with urllib.request.urlopen('http://127.0.0.1:5002/login', timeout=2) as response:
            assert response.status == 200
        break
    except (OSError, urllib.error.URLError):
        time.sleep(1)
else:
    raise RuntimeError('login did not become ready')
try:
    urllib.request.urlopen('http://127.0.0.1:5002/api/series-stats', timeout=5)
except urllib.error.HTTPError as error:
    assert error.code == 401, error.code
else:
    raise AssertionError('unauthenticated API request was accepted')
print('PASS: non-root read-only startup, timezone, login and API authentication')
PY
