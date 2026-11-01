# DevFeed

Fleet-managed developer news platform in the `devfeed` namespace. The manifests
target application **0.1.8** with immutable ARM64 digests and schema **0039**.
Images, configuration, replica counts and resource reservations
are owned by the manifests in this directory.

The pinned **0.1.8** cohort comes from [Release run 41063918969](https://github.com/abhi1693/devfeed.tech/actions/runs/41063918969),
attempt 1, at source [`7439405b`](https://github.com/abhi1693/devfeed.tech/commit/7439405bb165430a5809bfcfad86af45596b5f7a).
All twelve published images passed ARM64 platform and source/version-label
checks, GHCR/Harbor manifest-byte and digest parity, and signed provenance
verification against the pinned shared build workflow. The manifests use ten
components from that cohort; general workers use the full backend image.
The analytics process uses the existing Redis-client network label for its
shared catalog cache, alongside direct PostgreSQL and schema-owner ClickHouse access.
The completed [priority-queue cutover](migrations.md#016-priority-queues-and-current-analytics)
preserved all 805 queued deliveries and 29 historical failed records. Two stale
list pointers were removed only after their durable jobs were verified complete.
The temporary cleanup and transport hooks are retired; subsequent upgrades run
the ongoing schema hook, which rejects an installed image outside the 0.1.8 /
0039 cohort.

This compatible update keeps queue snapshots fresh, fixes card-recovery page
selection, and loads the reader Columns workspace only when opened. It uses the
normal rolling lifecycle. After convergence, confirm fresh, advancing queue and
card coverage, completed retained-source recovery, matching publication counts and
useful background completions.

## Access and authentication

| Entry point | Exposure | Purpose |
| --- | --- | --- |
| `https://devfeed.tech` | Cloudflare Tunnel | Reader frontend |
| `https://partners.devfeed.tech` | Cloudflare Tunnel | Partner frontend |
| `https://admin.devfeed.home` | Internal Traefik and home CA | Administration |

Reader and partner requests reach private APIs through their frontend. Account
APIs, administration, Typesense, Chimely and Codex have no direct public ingress.
Zitadel at `https://auth.devfeed.tech` provides OIDC with PKCE; administration
requires the `superuser` role. Keep the separate reader, partner and admin
client IDs, callback URLs and signing secrets aligned with their manifests.
Provider IDs are declared in the `devfeed-oidc-providers` ConfigMap in
`configmap.yaml`. Roll the consuming APIs when
OIDC configuration changes. Internal clients must trust the home CA.

## Services and automation

The reader, admin and partner frontends, public/user/admin/partner APIs and MCP
server each declare two replicas with disruption protection. Independent
`high`, `default` and `low` pools declare two, two and one consumers. Fresh
article work and interactive feed preparation use `high`; routine work shares
`default`; notifications use `low`. Images and solver retain one isolated
consumer each. The scheduler, search indexer, analytics process, Typesense,
Chimely, imgproxy and Codex are singletons. Read the Deployment manifests for
the exact commands and resources.

`DEVFEED_JOB_QUEUE_OVERRIDES` in the shared `devfeed` ConfigMap is the routing
source for every publisher and consumer. Its default is `{}`. A custom physical
destination needs its own matching consumer. Routing changes require a separately
reviewed offline migration. Ordinary image upgrades do not replay the completed
queue cutover. Images and solver must never share their
physical destinations or privileged credentials with a priority pool.

`configmap.yaml` owns automation policy. Full automation and adaptive source
polling are enabled; article-derived topic proposals are disabled. There is no
AI content-date cutoff. Source approval, article page-kind classification,
validated evidence, provider cooldowns and quota admission still gate processing.
Missing or uncertain page-kind classifications block publication.

Luna is configured for fast analysis and research, with Astra for baseline and
escalation. Verify model availability and successful inference through the
production Codex account before changing routing. Account login alone does not
prove model access. Keep consumer rollout annotations aligned with ConfigMap
changes. Feed responses are bounded to 20 MB, including expanded gzip content.

Workers use the packaged native health command. Scheduler, analytics and indexer
probes check their private heartbeat files. Preserve the bounded probe commands and
normal failure thresholds when changing startup behavior.

## Data and secrets

CloudNativePG owns the retained `devfeed` and `devfeed_chimely` databases and
roles. Interactive traffic uses twenty pooler backend slots. The analytics
process and schema hook use the direct writer connection; current-state
reconciliation requires session advisory coordination and cannot use transaction
pooling.
Python services use SQLAlchemy NullPool so closing a session returns its
connection to PgBouncer. Preserve global PostgreSQL headroom when changing
replicas or connection settings.

Shared Valkey Sentinel uses set `valkey`, database **10**, through
`valkey.valkey.svc.cluster.local:26379`. Network policies restrict access.
Typesense is internal-only on its retained Longhorn claim; query clients receive
restricted search credentials and only the indexer receives the management key.
The declared image is `30.2-arm64-lg-page16`; verify kernel-page compatibility
with the selected image before changing it. PostgreSQL remains the durable
source for rebuilding the search index.

Chimely credential volumes are retained NFS claims. All three priority pools
receive notification delivery credentials because routing overrides can move
notifications between them. APIs receive only their audience's signing credentials.
SOPS Secrets Operator owns service, database, registry, analytics and storage
secrets. Keep credentials out of ConfigMaps, browser bundles and plaintext Git.

Codex keeps authentication on its own Longhorn PVC. On an empty volume, read
`chatgpt-login` init logs and complete device authorization. Runtime SQLite state
uses a bounded `emptyDir`; its retention sidecar limits diagnostic logs and does
not mount authentication storage. Keep runtime state and credentials separate.
Validate the sidecar after Codex upgrades because its SQLite schema is internal.

## Search and solver operation

The indexer consumes the PostgreSQL search outbox and publishes a heartbeat.
Missing, stale or future-dated heartbeat files fail its probes. Preserve search
keys when replacing the rebuildable index.

Only the solver worker consumes `solver` and receives the FlareSolverr endpoint.
Ordinary enrichment workers hand off recognized browser challenges. The existing
browser service runs in `media`; browsers are not installed in ordinary workers.
Unsupported challenges remain errors rather than being accepted as article text.

## Availability

Frontend/API replica pairs tolerate one replica failure while shared dependencies
remain available. PostgreSQL and Valkey provide application-level replication;
Codex, Typesense, the scheduler, publishers, Chimely and NFS credential storage
remain shared dependencies. Asynchronous Valkey failover can lose unreplicated
writes. This deployment does not provide end-to-end high availability.

Worker placement uses eligible ARM64 nodes and workload spreading, with no
hostname-specific preferences. Priority pools use a zero-unavailable rolling
strategy and a 1,560-second graceful termination period. Drain all old consumers
before the first routing change; a normal rolling overlap is unsafe for that
one-time migration.

For a ClickHouse resource rollout, use temporary Kustomize replica overrides to
drain ordinary workers before their solver dependencies. Keep ClickHouse ready
until paid calls, delivery buffers, transport registries and live job leases are
drained. Pause API writers only for the database serving gap, then restore the
exact original replicas in dependency order. Retain queued identities, payloads,
retry counts and absolute expiry timestamps; a resize does not authorize replaying
paid inference. See the [maintenance gates](migrations.md#maintenance-gates).

## Validation and rollout

Keep all twelve application image components, init containers and the migration
hook on a verified release cohort. Renovate groups stable release tags and
immutable digests; release tests, native ARM64 scans, attestations and GHCR/Harbor
digest parity remain separate checks before accepting new pins.

The Helm pre-upgrade migration hook runs against the direct PostgreSQL writer.
A failed hook blocks rollout. Successful hooks are cleaned up; verify Helm
history and the database revision instead of requiring a retained completed Job.
The hook also enforces `jit=off` for the `devfeed` role in the `devfeed` database
and verifies the default on a fresh direct connection. Other roles and databases,
including `devfeed_chimely`, retain their existing settings. Existing pooled
backends pick up the default when they reconnect; this change does not restart
PostgreSQL or its poolers. See the [JIT rollout and rollback](migrations.md#devfeed-jit-default).
Keep schema 0039 and recover with compatible images. An image-only downgrade
cannot reverse queue routing and cannot restore deleted retention payloads.

Compatible patches use rolling upgrades. Policy/schema changes need a reviewed
maintenance plan: stop admissions, drain actual workers and dependencies, apply
migrations, validate core/analytics health and resume only the owned pause.
Stopping the scheduler alone does not stop queue consumption. See
[migration lifecycle](migrations.md)
and [queue maintenance tests](../../../../../scripts/devfeed-maintenance/README.md).

Verify Fleet desired/applied equality, actual image IDs, readiness, queue
processing, current-view reconciliation coverage and zero new restarts. A Ready
analytics process alone does not prove fresh reports. Retain PVCs and credentials
during recovery and reconcile changes through Git/Fleet.

```sh
kubectl kustomize kubernetes/projects/applications/apps/devfeed
python3 -m unittest discover -s kubernetes/projects/applications/apps/devfeed/tests -v
node --test kubernetes/projects/applications/apps/devfeed/codex-log-retention.test.cjs
python3 scripts/check-devfeed-observability.py
kubectl get pods,deploy,job,pvc,ingress -n devfeed
```

## Observability

APIs, workers, scheduler and indexer expose native OpenTelemetry metrics;
frontends expose Node metrics. Metrics stay private on port 9100. The
`devfeed-operations` Grafana dashboard covers HTTP health, replicas, scrapes,
reader latency/errors, search lag, delivery activity and background freshness.
Delivery counts do not establish successful editorial outcomes; use the admin
UI for durable job results and retries.

Alloy/Loki, OpenTelemetry/Tempo and Pyroscope provide shared logs, traces and
profiles. Verify actual delivery and public isolation after
telemetry changes. Shared backend retention is documented in the owning system
app READMEs rather than duplicated here.

## Browser extensions

The web gateway and user API allow these exact DevFeed extension IDs:

- Chrome Web Store: `iihaipjedchahiehignbngclgpklbddo`.
- Microsoft Edge: `hliakjocndflpkmfajndigbpngfcekdm` (owner-supplied; also the
  stable unpacked development ID).

Session and CSRF validation remain required. Keep `DEVFEED_USER_EXTENSION_IDS`
in both deployments synchronized if store IDs change; never use a wildcard
origin. Website GA4 uses `G-N4V5CW5C0M` and starts after interaction. Extension
Measurement Protocol uses the separate `G-Y1MNJGMGCD` stream. The web deployment
requires `devfeed-extension-analytics/DEVFEED_EXTENSION_GA_API_SECRET`, provisioned
as a SOPS-encrypted secret before reconciliation. Edit
`analytics-secrets.sops.yaml` with `sops` and set
`spec.secretTemplates[0].stringData.DEVFEED_EXTENSION_GA_API_SECRET`; the initial
empty value keeps the relay disabled. Never place that secret in a
ConfigMap, extension bundle, or plaintext Git file. The public relay configuration
at `/api/v1/extension/analytics` reports enabled only when all required values are
present. Roll back by disabling `DEVFEED_EXTENSION_ANALYTICS_ENABLED` through GitOps.
Store submission is independent of the application rollout.

## Managed article images

The dedicated Images worker downloads originals through the application's SSRF-safe
fetcher, stores them in one production R2 bucket, asks the internal
`http://devfeed-imgproxy:8080` service for responsive WebP thumbnails, and uploads
those thumbnails to the same bucket. Readers load the resulting objects from
`https://images.devfeed.tech`; imgproxy has no ingress and no S3 credentials.
The bucket custom domain must serve `originals/` and `thumbnails/` over HTTPS.
The Images worker and user API receive bucket-scoped read/write credentials from
`image-storage-secrets.sops.yaml`. The user API stores profile avatars as five square
WebP variants under fixed per-account `avatars/` keys; replacements overwrite those
keys, and removal deletes them. The public bucket domain must also serve `avatars/`. Edit that file with SOPS; the endpoint is the
account origin without a bucket suffix. The worker and proxy share signing values
from `imgproxy-secrets.sops.yaml`, independently generated for DevFeed.

Imgproxy v4.0.17 runs one ARM64 replica with two processing workers, a bounded queue,
100m CPU/256Mi memory requested, and 1 CPU/512Mi memory limits. Its source allowlist
contains only the production bucket's `originals/` prefix. Network policies allow
only the Images worker to reach its HTTP port; proxy downloads use public HTTPS.
The private `metrics` port on `:9090` is scraped every 60 seconds by the dedicated
`devfeed-imgproxy` ServiceMonitor. Only Rancher Prometheus pods can reach it.
The shared **imgproxy / Overview** dashboard (UID `shipyardhq-imgproxy`, maintained
in the ShipyardHQ bundle) compares both applications and supports Application and
Instance filters; it keeps each application's metrics separate when All is selected.
Originals and thumbnails persist in R2; no new PVC or public proxy route is needed.

Topic and source logos use the managed-image pipeline. Keep the bucket CORS
policy and public response headers compatible with browser canvas exports.
Validate ordinary and Origin-bearing image responses after storage/CDN changes.

## Resource review — 28 October 2026

The first sizing batch uses fourteen days of workload-owned Prometheus history,
with recent 24-hour/three-day sustained CPU checked separately from one-minute
burst peaks. CPU requests for background workers cover observed mean demand
plus headroom; their uncapped CPU policy permits the measured bursts. Memory
limits remain above historical working-set peaks, with at least 512Mi for the
resized analysis workers. Short-lived init-container reservations are preserved.

| Container | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `chimely` | 75m → 25m | 128Mi → 64Mi | 512Mi → 128Mi |
| `mcp` | 50m → 10m | 128Mi → 128Mi | 512Mi → 256Mi |
| `partner-api` | 100m → 25m | 256Mi → 256Mi | 1Gi → 512Mi |
| `article-enrichment-worker` | 500m → 200m | 256Mi → 384Mi | 1Gi → 1Gi |
| `images-worker` | 350m → 150m | 256Mi → 256Mi | 1Gi → 512Mi |
| `topic-analysis-worker` | 250m → 100m | 256Mi → 256Mi | 1Gi → 512Mi |
| `research-verification-worker` | 250m → 100m | 256Mi → 256Mi | 1Gi → 512Mi |
| `relationships-worker` | 250m → 125m | 256Mi → 256Mi | 1Gi → 512Mi |
| `source-discovery-worker` | 100m → 100m | 256Mi → 128Mi | 1Gi → 512Mi |

## Resource review — reservation and memory safety batch

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `devfeed/devfeed-admin/admin` | 100m → 25m | 128Mi → 256Mi | 512Mi → 512Mi |
| `devfeed/devfeed-admin-api/admin-api` | 100m → 25m | 256Mi → 256Mi | 1Gi → 1536Mi |
| `devfeed/devfeed-partner/partner` | 100m → 25m | 128Mi → 224Mi | 512Mi → 512Mi |
| `devfeed/devfeed-user-api/user-api` | 100m → 50m | 256Mi → 256Mi | 1Gi → 512Mi |
| `devfeed/devfeed-worker-ai/ai-worker` | 250m → 200m | 256Mi → 384Mi | 1Gi → 768Mi |
| `devfeed/devfeed-worker-article-analysis/article-analysis-worker` | 300m → 200m | 256Mi → 640Mi | 1Gi → 1Gi |
| `devfeed/devfeed-worker-ingestion/ingestion-worker` | 400m → 250m | 256Mi → 384Mi | 1Gi → 1Gi |
| `devfeed/devfeed-worker-notification/notification-worker` | 400m → 325m | 256Mi → 256Mi | 1Gi → 512Mi |
| `devfeed/devfeed-worker-source-enrichment/source-enrichment-worker` | 100m → 100m | 256Mi → 160Mi | 1Gi → 768Mi |
| `devfeed/devfeed-search-indexer/indexer` | 100m → 125m | 256Mi → 192Mi | 1Gi → 512Mi |
| `devfeed/devfeed-typesense/typesense` | 100m → 50m | 512Mi → 768Mi | 2Gi → 2Gi |
| `devfeed/sonarqube-mcp-server/server` | 100m → 25m | 256Mi → 320Mi | 768Mi → 768Mi |

## Resource review — sustained demand and burst envelopes

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `devfeed/devfeed-api/api` | 100m → 200m | 256Mi → 320Mi | 1Gi → 768Mi |
| `devfeed/devfeed-web/web` | 100m → 250m | 128Mi → 384Mi | 512Mi → 512Mi |
| `devfeed/devfeed-scheduler/scheduler` | 500m → 750m | 256Mi → 1152Mi | 1Gi → 1536Mi |
| `devfeed/devfeed-codex/codex` | 100m → 150m | 512Mi → 384Mi | 2Gi → 3072Mi |
| `devfeed/devfeed-codex/log-retention` | 25m → 10m | 64Mi → 32Mi | 128Mi → 128Mi |
| `devfeed/devfeed-worker-solver/solver-worker` | 100m → 100m | 256Mi → 416Mi | 1Gi → 1Gi |
| `devfeed/devfeed-probes/probes` | 10m → 10m | 32Mi → 64Mi | 128Mi → 128Mi |


### Browser telemetry

The 0.1.6 applications remove Faro browser collection. DevFeed no longer mounts
its browser key, sets its runtime flags or advertises a collector endpoint.
Backend tracing, logs, profiling and application analytics remain enabled.

## Final resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `devfeed/devfeed-imgproxy/imgproxy` | 100m → 10m | 256Mi → 96Mi | 512Mi → 256Mi |

## Public probe ownership

`cloudflare-public-http` probes active application endpoints only. The retired
Wardn AI website (`wardnai.dev`) was removed from this list on 2026-10-28;
Wardn Hub (`hub.wardnai.dev`) remains monitored. When retiring an app, remove
its dedicated public probe target along with its ingress so expected DNS
removal does not produce a false critical availability alert.

### Probe execution during recovery

Priority pools use the native health command with a five-second execution
budget, avoiding Python startup in every probe. Images retains its existing
15-second execution budget. These budgets do not extend heartbeat freshness
or diagnose a node outage.

## Direct analytics rollout (0.1.5)

The shared [ClickHouse service](../../../database/apps/clickhouse/README.md) lives
in its own `clickhouse` namespace. DevFeed uses the private endpoint
`http://clickhouse.clickhouse.svc.cluster.local:8123`, its own database and scoped
SOPS-encrypted credentials. No browser database UI is deployed.
No ClickHouse backup CronJob is deployed; operator-managed backups must include
the migration journal, historical import checkpoints and readiness state.

The 0.1.5 handover ran PostgreSQL 0038 followed by versioned ClickHouse upgrades.
It retired both old read-model projectors and their alerts, then enabled the
finite importer after the old producers drained. That completed importer
permanently retired PostgreSQL analytics history after acknowledged import.
An image downgrade cannot restore it.

Importer probes read the packaged private heartbeat helper directly. They avoid
importing the full analytics worker under its half-CPU budget; repeated worker
imports exceeded the probe deadline despite advancing historical checkpoints.

The importer reads AI enablement, full automation, the Codex model and server URL
from `devfeed-automation`, matching the administration API's policy inputs. It
does not receive Codex credentials or execute inference. Policy-specific card
pages must be complete before readiness advances; during the October recovery,
the separate cards-only warmup completed all five sources before these inputs
were aligned. Historical checkpoints and the original capture boundary remain
unchanged.

## Priority worker resource review — 30 October 2026

The 30 October review reduced fifteen workers reserving 2,450m CPU and 5,312Mi
memory to eleven workers reserving 1,950m CPU and 4,000Mi memory. On 31 October,
the high and default pools were temporarily reduced from four to two replicas
each. The current seven-worker layout reserves 1,150m CPU and 2,464Mi memory,
including the unchanged Images and solver consumers:

| Pool | Replicas | CPU request per pod | Memory request per pod | Memory limit |
| --- | ---: | ---: | ---: | ---: |
| High | 2 | 200m | 384Mi | 1Gi |
| Default | 2 | 200m | 384Mi | 1Gi |
| Low | 1 | 100m | 256Mi | 1Gi |
| Images | 1 | 150m | 256Mi | 512Mi |
| Solver | 1 | 100m | 416Mi | 1Gi |

The preceding 24 hours of five-minute samples included active processing before
quota pacing paused AI. Busy general workers had approximately 0.28–0.41-core
CPU percentiles; their largest memory 95th percentile was 382Mi and observed
peak was 506Mi. The 1Gi limits retain peak headroom, while CPU remains uncapped.
Notification memory stayed below 178Mi at the 95th percentile. Changing routing
overrides changes the work mix and may require new sizing.

Lower reservations do not establish lower CPU usage or faster inference. After
rollout, compare useful completions, queue age, working sets, probe failures and
restarts through representative active processing. Daily quota pacing remains
an independent admission policy.
