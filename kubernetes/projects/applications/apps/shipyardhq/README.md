# ShipyardHQ

Fleet-managed deployment for ShipyardHQ.

The public hostnames are `shipyardhq.dev`, `www.shipyardhq.dev`, and
`img.shipyardhq.dev`, exposed through the Cloudflare Tunnel ingress controller.

The app-owned Cloudflare Tunnel ingress and service are both named `shipyardhq`
in the `shipyardhq` namespace. Cloudflare serves public HTTPS, the tunnel
transport is encrypted, and the final in-cluster hop to the app pods uses HTTP:

```text
http://shipyardhq.shipyardhq.svc.cluster.local:3000
```

Required out-of-band secrets:

The image pull credential is the namespace-scoped `harbor-registry`
dockerconfigjson Secret for `registry.home`, backed by
`robot-namespace-shipyardhq`.

```bash
kubectl create namespace shipyardhq --dry-run=client -o yaml | kubectl apply -f -

kubectl -n shipyardhq create secret generic shipyardhq-runtime \
  --from-env-file=/path/to/shipyardhq/production.env

kubectl -n shipyardhq create secret generic shipyardhq-local-database \
  --from-literal=username=shipyardhq \
  --from-literal=password='<shared-postgresql-password>' \
  --from-literal=dbname=shipyardhq
```

The `shipyardhq-local-database` secret backs the runtime PostgreSQL connection.

The Git-tracked `shipyardhq` ConfigMap declares these Valkey/Sentinel values.
DB `20` is reserved for ShipyardHQ; NetBox uses DBs `1` and `2`.

```env
REDIS_SENTINEL_NAME=valkey
REDIS_SENTINEL_NODES=valkey.valkey.svc.cluster.local:26379
REDIS_DB=20
```

Keep these values out of `shipyardhq-runtime` when recreating the Secret.

Set these Cloudflare R2 secret values in the runtime env file. The bucket,
endpoint, and public base URL are declared in the `shipyardhq` ConfigMap.

```env
R2_ACCESS_KEY_ID=<cloudflare-r2-access-key-id>
R2_SECRET_ACCESS_KEY=<cloudflare-r2-secret-access-key>
```

Only the R2 credentials above are required for Shipyard media storage.

## Database

ShipyardHQ runtime pods use the shared local PostgreSQL cluster through
`postgresql-pooler-shipyardhq-rw.postgresql.svc.cluster.local`. Do not commit
database credentials.

The application image uses the normal Prisma PostgreSQL adapter path. A
`postgres://` or `postgresql://` URL with `sslmode=require` is supported by the
underlying `pg` connection parser.

The `shipyard-next-build` Job owns the Next.js production build. Fleet runs it
as a Helm pre-install/pre-upgrade hook; it is not created manually. The hook
delete policy removes any previous hook Job before creating a new one and cleans
up the Job after a successful build, which keeps the fixed Job name reusable.
The Job uses the runtime environment and the app-specific PostgreSQL pooler,
applies Prisma migrations, writes an immutable versioned tarball to the
`shipyardhq-next-build-cache` RWX Longhorn PVC, and exits after the artifact
exists. The builder uses a smaller PostgreSQL client pool, a longer connection
wait timeout, and lower Next.js static-generation concurrency so DB-backed
prerendering does not overload the local database. It also sets the supported
Next.js `staticPageGenerationTimeout` option to five minutes before hashing and
building the release source so slower DB-backed pages do not fail the production
build at the default 60-second limit. The builder Job is explicitly single-pod
(`parallelism: 1`, `completions: 1`) and has no schedule. Web pods do not build;
their `restore-next-build` init container waits for the matching artifact,
extracts it into a pod-local `emptyDir`, and then starts
`.next/standalone/server.js`. Running web pods keep using their local extracted
bundle if a newer artifact is later written to the PVC; new artifacts are
consumed through normal Deployment rollouts.

The cache key includes source files, build-time environment, and a cache-format
version. The `shipyardhq-next-build-cache-cleanup` CronJob recomputes the
current cache key every three days, verifies that the matching `.tar.gz` and
`.ready` files exist, and then removes only non-current cached build artifacts.

Product detail routes keep the application default prerender list so hot product
pages are generated during the first build for a release, while ISR and
`dynamicParams` still allow long-tail pages to render and refresh on demand. The
web container then starts `.next/standalone/server.js` directly, bypassing the
image entrypoint's runtime build path.

The web startup probe allows up to 20 minutes for the application process to
start, then readiness and liveness continue probing `GET /robots.txt`.

The runtime build uses `NEXT_PUBLIC_R2_PUBLIC_BASE_URL` for managed media image
optimization.

## Availability

The public web and imgproxy Deployments run two replicas with `maxUnavailable:
0`, PodDisruptionBudgets requiring both replicas to stay available, and the
`shipyardhq-critical` PriorityClass. That priority stays below system, Rancher,
and Longhorn priorities but above normal application pods.

The web pod's `next-build` `emptyDir` is sized for transient Next.js build
output, not just the final restored artifact. Keep its ephemeral-storage
requests and limits aligned with the `emptyDir` size when changing build
behavior.

## Background Worker

The `shipyardhq-worker` Deployment runs `npm run worker` from the same
application image. It consumes BullMQ event envelopes and owns scheduled jobs
declared in ShipyardHQ source, replacing the legacy curl CronJobs.

The worker does not run Prisma migrations. Its `wait-for-web-rollout` init
container follows the NetBox chart worker pattern and waits for
`deployment/shipyardhq` to finish rolling out before starting the worker.

Secret runtime env is stored in the `shipyardhq-runtime` Kubernetes Secret. Do
not commit secret runtime environment values.

## Image Proxy

The `shipyardhq-imgproxy` Deployment serves signed imgproxy image URLs from
`img.shipyardhq.dev`. It is configured to fetch source images only from the
existing public R2 media origin:

```env
IMGPROXY_ALLOWED_SOURCES=https://media.shipyardhq.dev/
```

The imgproxy signing key and salt are stored in the `shipyardhq-imgproxy`
SopsSecret. ShipyardHQ source code must generate signed image URLs server-side
before the public imgproxy endpoint is useful. Do not expose the key or salt to
client-side code.
The web container imports that same Secret for server-side signing and uses
`IMGPROXY_ENDPOINT=https://img.shipyardhq.dev` from the `shipyardhq` ConfigMap
so generated URLs are browser-reachable.

The ConfigMap keeps production imgproxy controls explicit:

- source fetching is restricted to `https://media.shipyardhq.dev/` with private,
  loopback, and link-local source addresses blocked;
- URL processing options are limited to the signed options ShipyardHQ emits
  today: `rs`, `q`, `sm`, and `f`;
- cache validation uses imgproxy ETag and Last-Modified support with a one-year
  `Cache-Control` TTL;
- source/result size limits, redirect limits, queue limits, and client limits
  are set to bound CPU, memory, and outbound traffic;
- detailed development errors, cookie passthrough, security-option overrides,
  unlimited PNG/SVG parsing, SSL verification bypass, and attachments are kept
  disabled.
- ShipyardHQ `v1.4.29` caches transformed managed-media responses back into R2
  under `image-cache/imgproxy/` through the web application route
  `/api/images/cache`.

The Deployment uses imgproxy's built-in `GET /health` endpoint for startup,
readiness, and liveness probes on the main `http` port. imgproxy returns `200 OK`
from this endpoint after the server has successfully started.

Prometheus metrics are enabled on the separate `:9090` metrics listener with the
`imgproxy` metric namespace. The `shipyardhq-imgproxy` Service exposes this as
the `metrics` port, and the ServiceMonitor scrapes `/metrics` from
`cattle-monitoring-system`. NetworkPolicy only allows the public image endpoint
from the Cloudflare tunnel and the metrics endpoint from Rancher Monitoring.
The `shipyardhq-imgproxy-dashboard` ConfigMap is labeled for Rancher Grafana
sidecar discovery in `cattle-dashboards`.

## OpenTelemetry

The web and worker pods send OTLP metrics and traces to the local
`opentelemetry-collector` service over HTTP/protobuf. Metrics are exported from
the collector to Prometheus; traces are exported to the local Tempo service and
shown in Grafana's Lightweight APM for OpenTelemetry dashboard. Trace batching
is capped with a smaller queue and export batch size so low-volume tracing does
not add unbounded memory pressure.
