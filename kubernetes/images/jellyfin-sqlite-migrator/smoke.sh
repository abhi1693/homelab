#!/usr/bin/env bash
set -euo pipefail
image=${1:?image required}
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:uid=1000,gid=1000 \
  -v "$PWD/kubernetes/images/jellyfin-sqlite-migrator/test_migrate.py:/app/test_migrate.py:ro" \
  --entrypoint python "$image" -B -m unittest -v test_migrate
