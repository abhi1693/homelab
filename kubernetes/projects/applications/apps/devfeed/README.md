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

Imgproxy v4.0.23 runs one ARM64 replica with two processing workers, a bounded queue,
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

## Browser telemetry

The 0.1.6 applications remove Faro browser collection. DevFeed no longer mounts
its browser key, sets its runtime flags or advertises a collector endpoint.
Backend tracing, logs, profiling and application analytics remain enabled.

## Resource sizing

See [bundle manifests](.) for the configured resources and [the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review) for the historical measurements.

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
importing the full analytics worker; repeated worker imports exceeded the probe
deadline despite advancing historical checkpoints.

After historical import completes, the same process continues bounded
current-state reconciliation. It reserves 500m CPU and permits bursts up to one
core, with the existing 256Mi memory request and 512Mi limit. Current card pages stay
bounded to 100 identities and overview pages to 1,000 source records, with one
coordinator and the existing builder, fence and advisory-lock rules. Validate
resource changes against source mutations or dirty work remaining, acknowledged
page progress and whole-set coverage, and paired PostgreSQL and ClickHouse work
measurements while preserving interactive workload health. An old coverage
timestamp alone does not prove stale data when its source has not changed.

The importer reads AI enablement, full automation, the Codex model and server URL
from `devfeed-automation`, matching the administration API's policy inputs. It
does not receive Codex credentials or execute inference. Policy-specific card
pages must be complete before readiness advances; during the October recovery,
the separate cards-only warmup completed all five sources before these inputs
were aligned. Historical checkpoints and the original capture boundary remain
unchanged.
