#!/usr/bin/env bash
set -euo pipefail

image=${1:?immutable official image reference required}
[[ $image =~ ^docker.io/sonarsource/sonarqube-mcp@sha256:[a-f0-9]{64}$ ]]
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workdir=$(mktemp -d)
name="sonarqube-mcp-qualification-${RANDOM}"
cleanup() {
  docker logs --tail 40 "$name" 2>/dev/null || true
  docker stop "$name" >/dev/null 2>&1 || true
  rm -rf -- "$workdir"
}
trap cleanup EXIT

javac --release 17 -d "$workdir" "$script_dir/TrustCheck.java"
chmod 755 "$workdir"
blocked=(86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4)
docker pull --platform linux/arm64 "$image"
docker run --rm --platform linux/arm64 --network=none --read-only \
  --cap-drop=ALL --security-opt=no-new-privileges \
  --mount "type=bind,source=$workdir,target=/qualification,readonly" \
  --entrypoint java "$image" -cp /qualification TrustCheck "${blocked[@]}"
docker run --rm -i --platform linux/arm64 --network=none --read-only \
  --cap-drop=ALL --security-opt=no-new-privileges --entrypoint node \
  "$image" --input-type=module - <<'JS'
import assert from 'node:assert/strict';
import { X509Certificate } from 'node:crypto';
import { getCACertificates } from 'node:tls';
assert.equal(process.arch, 'arm64');
const [major, minor, patch] = process.versions.node.split('.').map(Number);
assert.equal(major, 24);
assert.ok(minor > 22 || (minor === 22 && patch >= 1), 'Node 24.22.1 floor');
const roots = [...getCACertificates('default'), ...getCACertificates('system')];
assert.ok(roots.length > 0);
const fingerprints = new Set(roots.map(pem => new X509Certificate(pem).fingerprint256.replaceAll(':', '').toLowerCase()));
for (const denied of ['86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b', 'd7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4']) {
  assert.equal(fingerprints.has(denied), false, 'Distrusted CA remains trusted');
}
console.log(`PASS: Node ${process.versions.node}, ${process.arch}, ${roots.length} roots; distrusted fingerprints absent`);
JS

docker run --rm -d --name "$name" --platform linux/arm64 --network=none \
  --read-only --cap-drop=ALL --security-opt=no-new-privileges \
  --user 100:101 --tmpfs /tmp:uid=100,gid=101 \
  --tmpfs /app/storage:uid=100,gid=101 --tmpfs /home/appuser:uid=100,gid=101 \
  -e SONARQUBE_TRANSPORT=http -e SONARQUBE_HTTP_HOST=0.0.0.0 \
  -e SONARQUBE_HTTP_PORT=8080 -e SONARQUBE_ORG=abhi1693 \
  -e SONARQUBE_READ_ONLY=true \
  -e SONARQUBE_TOOLSETS=issues,rules,sources,quality-gates,measures,coverage,duplications,security-hotspots \
  -e SONARQUBE_LOG_TO_FILE_DISABLED=true "$image" >/dev/null
docker exec -i "$name" node --input-type=module - <<'JS'
import assert from 'node:assert/strict';
import { setTimeout } from 'node:timers/promises';
let healthy = false;
for (let attempt = 0; attempt < 90; attempt++) {
  try {
    const response = await fetch('http://127.0.0.1:8080/health', { signal: AbortSignal.timeout(2000) });
    if (response.ok) { healthy = true; break; }
  } catch {}
  await setTimeout(1000);
}
assert.ok(healthy, 'Server did not become healthy');
const info = await fetch('http://127.0.0.1:8080/info');
assert.equal(info.status, 200);
const response = await fetch('http://127.0.0.1:8080/mcp', {
  method: 'POST',
  headers: {'Content-Type': 'application/json', Accept: 'application/json, text/event-stream'},
  body: JSON.stringify({jsonrpc: '2.0', id: 1, method: 'initialize', params: {protocolVersion: '2025-03-26', capabilities: {}, clientInfo: {name: 'qualification', version: '1'}}}),
  signal: AbortSignal.timeout(5000),
});
assert.equal(response.status, 401, 'Unauthenticated MCP request must be rejected');
console.log('PASS: non-root read-only startup, health/info and unauthenticated MCP rejection');
JS
