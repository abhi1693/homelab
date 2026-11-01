#!/bin/sh
# Check the controller heartbeat without starting another Python interpreter.
set -eu
status_file=${MEDIA_SCHEDULE_STATUS_PATH:-/tmp/status.json}
[ -s "$status_file" ] || exit 1
grep -q '"healthy":true' "$status_file" || exit 1
status_epoch=$(stat -c %Y "$status_file")
now_epoch=$(date +%s)
[ "$now_epoch" -ge "$status_epoch" ]
[ "$((now_epoch - status_epoch))" -lt 90 ]
