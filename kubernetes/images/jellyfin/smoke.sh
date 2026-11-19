#!/usr/bin/env bash
set -euo pipefail
image=${1:?image reference required}
app_version=${3:?application version required}
name="jellyfin-smoke-${RANDOM}"
cleanup() {
  docker logs --tail 30 "$name" || true
  docker stop "$name" > /dev/null || true
}
trap cleanup EXIT
docker run --rm -d --name "$name" --user 568:568 --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:uid=568,gid=568 --tmpfs /config:uid=568,gid=568 \
  --tmpfs /data:uid=568,gid=568 --tmpfs /logs:uid=568,gid=568 \
  --tmpfs /cache:uid=568,gid=568 \
  -v "$PWD/kubernetes/images/jellyfin/required-plugin-metadata.json:/expected-plugins.json:ro" \
  -e JELLYFIN_REQUIRE_MIGRATION_RECEIPT=false "$image" > /dev/null
docker exec -i "$name" bash -s -- "$app_version" << 'BASH'
set -euo pipefail
expected=$1
test "$(id -u)" = 568
test ! -d /opt/jellyfin/plugins/PostgreSQL
for attempt in $(seq 1 90); do
  if curl -fsS --max-time 3 http://127.0.0.1:8096/System/Info/Public > /tmp/info.json \
    && jq -e --arg version "$expected" '.Version == $version and .StartupWizardCompleted == false' /tmp/info.json >/dev/null; then break; fi
  sleep 2
done
jq '{Version,StartupWizardCompleted}' /tmp/info.json
jq -e --arg version "$expected" '.Version == $version and .StartupWizardCompleted == false' /tmp/info.json
post() { curl -fsS -H 'Content-Type: application/json' -X POST "http://127.0.0.1:8096$1" --data "$2"; }
post /Startup/Configuration '{"UICulture":"en-US","MetadataCountryCode":"US","PreferredMetadataLanguage":"en"}'
curl -fsS http://127.0.0.1:8096/Startup/User >/dev/null
post /Startup/User '{"Name":"migration-smoke","Password":"local-smoke-only-123"}'
post /Startup/RemoteAccess '{"EnableRemoteAccess":true,"EnableAutomaticPortMapping":false}'
post /Startup/Complete '{}'
curl -fsS -H 'Content-Type: application/json' \
  -H 'Authorization: MediaBrowser Client="Smoke", Device="CI", DeviceId="smoke", Version="1.0.0"' \
  --data '{"Username":"migration-smoke","Pw":"local-smoke-only-123"}' \
  http://127.0.0.1:8096/Users/AuthenticateByName > /tmp/auth.json
token=$(jq -er .AccessToken /tmp/auth.json)
curl -fsS -H "Authorization: MediaBrowser Token=\"$token\"" http://127.0.0.1:8096/Plugins > /tmp/plugins.json
jq -e --slurpfile expected /expected-plugins.json '
  . as $plugins | $expected[0] | to_entries | all(.[];
    .value as $wanted | any($plugins[];
      (.Id | ascii_downcase | gsub("-"; "")) == ($wanted.guid | ascii_downcase | gsub("-"; ""))
      and .Version == $wanted.version
      and .Status == "Active"
    )
  )' /tmp/plugins.json
test -s /data/data/jellyfin.db
sqlite3 'file:/data/data/jellyfin.db?mode=ro' 'PRAGMA integrity_check;' | grep -x ok
/usr/lib/jellyfin-ffmpeg/ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc=size=320x180:rate=24 -f lavfi -i sine=frequency=440:sample_rate=48000 -t 2 -c:v libx264 -pix_fmt yuv420p -c:a aac /tmp/source.mp4
/usr/lib/jellyfin-ffmpeg/ffmpeg -hide_banner -loglevel error -i /tmp/source.mp4 -vf scale=160:-2 -c:v libx264 -c:a aac -f hls -hls_time 1 /tmp/stream.m3u8
/usr/lib/jellyfin-ffmpeg/ffprobe -v error -show_streams -of json /tmp/source.mp4 | jq -e '.streams | length == 2'
test -s /tmp/stream.m3u8
echo 'PASS: exact version, native SQLite, non-root read-only startup, login, all plugins active and H.264/AAC HLS transcoding'
BASH
