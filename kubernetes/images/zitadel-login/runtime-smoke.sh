#!/usr/bin/env bash
set -euo pipefail

image=${1:?image reference required}
platform=${2:?platform required}
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
runtime_policy=$(cat "$script_dir/runtime-policy.json")

# Inspect the candidate's actual runtime and its configured trust pool, which
# uses OpenSSL's system bundle rather than Node's bundled roots.
docker run --rm -i --read-only --network=none --cap-drop=ALL \
  --security-opt=no-new-privileges --entrypoint node \
  -e RUNTIME_POLICY_JSON="$runtime_policy" -e EXPECTED_PLATFORM="$platform" \
  "$image" --input-type=module - << 'JS'
import assert from 'node:assert/strict';
import { X509Certificate } from 'node:crypto';
import { accessSync, constants, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { getCACertificates } from 'node:tls';

const policy = JSON.parse(process.env.RUNTIME_POLICY_JSON);
function assertVersion(actual, floor, name) {
  assert.match(actual, /^\d+\.\d+\.\d+$/, `${name} must be a stable release`);
  const current = actual.split('.').map(Number);
  const minimum = floor.split('.').map(Number);
  assert.equal(current[0], minimum[0], `review policy before changing ${name} major`);
  assert.ok(current[1] > minimum[1] ||
    (current[1] === minimum[1] && current[2] >= minimum[2]), `${name} security floor`);
}
assertVersion(process.versions.node, policy.minimumNodeVersion, 'Node');
const require = createRequire('/app/apps/login/server.js');
const nextVersion = require('next/package.json').version;
assertVersion(nextVersion, policy.minimumNextVersion, 'Next.js');
assert.equal(`linux/${process.arch === 'x64' ? 'amd64' : process.arch}`,
  process.env.EXPECTED_PLATFORM);
assert.equal(process.getuid(), 1001, 'runtime must be non-root');
for (const tool of ['npm', 'corepack']) {
  assert.equal(existsSync(`/usr/local/lib/node_modules/${tool}`), false);
}
assert.match(process.env.NODE_OPTIONS, /--use-openssl-ca(?:\s|$)/);
accessSync(process.env.SSL_CERT_FILE, constants.R_OK);
// Node issue #64258: "default" omits OpenSSL's lazy store. Enumerate the
// configured system store explicitly as well as any extra default roots.
const roots = [...getCACertificates('system'), ...getCACertificates('default')];
assert.ok(roots.length > 0, 'configured trust store must not be empty');
const fingerprints = new Set(roots.map(pem =>
  new X509Certificate(pem).fingerprint256.replaceAll(':', '').toLowerCase()));
for (const denied of policy.distrustedCaSha256) {
  assert.equal(fingerprints.has(denied), false, `distrusted CA ${denied}`);
}
console.log(`PASS: Node ${process.versions.node}, Next.js ${nextVersion}, ` +
  `${process.arch}, uid 1001, ` +
  `${roots.length} trusted roots; distrusted roots absent`);
JS

name="zitadel-login-smoke-${RANDOM}"
cleanup() {
  docker logs --tail 30 "$name" || true
  docker stop "$name" > /dev/null || true
}
trap cleanup EXIT

# No identity credentials or external network: startup must work, liveness must
# pass, and readiness must reject the missing backend configuration.
docker run --rm -d --name "$name" --read-only --network=none --cap-drop=ALL \
  --user 1000:1000 \
  --security-opt=no-new-privileges --no-healthcheck \
  --tmpfs /tmp:uid=1000,gid=1000 \
  --tmpfs /app/apps/login/.next/cache:uid=1000,gid=1000 \
  -e OTEL_SDK_DISABLED=true "$image" > /dev/null
docker exec -i "$name" node --input-type=module - << 'JS'
import assert from 'node:assert/strict';
import { setTimeout } from 'node:timers/promises';

let healthy = false;
for (let attempt = 0; attempt < 60; attempt++) {
  try {
    const response = await fetch('http://127.0.0.1:3000/ui/v2/login/healthy', {
      signal: AbortSignal.timeout(2000),
    });
    await response.arrayBuffer();
    if (response.status === 200) {
      healthy = true;
      break;
    }
  } catch {}
  await setTimeout(1000);
}
assert.ok(healthy, 'server liveness did not become healthy');
const readiness = await fetch('http://127.0.0.1:3000/ui/v2/login/ready', {
  signal: AbortSignal.timeout(5000),
});
await readiness.arrayBuffer();
assert.equal(readiness.status, 503, 'unconfigured backend must not be ready');
console.log('PASS: read-only non-root startup, liveness and fail-closed readiness');
JS
