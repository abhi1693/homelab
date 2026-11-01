# Shared ClickHouse

Fleet owns the `clickhouse` namespace and private service
`clickhouse.clickhouse.svc.cluster.local:8123` (native port 9000).
DevFeed has its own `devfeed` database and separate public, user, partner,
admin, worker, ingestion and reader roles; grants are confined to that database.
Server operator credentials remain in this namespace. New applications require
their own database, credentials, limits and explicit network-policy admission.

The immutable ARM64-capable ClickHouse 26.8 image uses a 50 GiB Longhorn worker
volume and retained 100 GiB NFS backups. No scheduled ClickHouse backup Job is deployed. The NFS backup volume is retained
for operator-managed backups. Include migration history, checkpoints and readiness
in backups; restore the complete application database before producers resume.

Budgets: 1 CPU / 2304 MiB requests, 3 CPU / 6 GiB limits, 4.5 GiB tracked
server memory, 128 total queries, 64 SELECTs and 96 INSERTs. Admission is
shared across replicas and includes bounded replacement overlap.
A single replica provides persistent recovery, not database high availability.

Validate with `kubectl kustomize kubernetes/projects/database/apps/clickhouse`,
server dry runs, workload catalog validation and live Fleet readiness.

## Access and resource bounds

No browser UI or public ingress is deployed. HyperDX, MongoDB, CH-UI and their
application-state PVCs are removed. ClickHouse's analytical data and retained
backup storage remain separate from those retired interfaces.

Use scoped ClickHouse identities through the private HTTP/native service.
The retained operator identity is `clickhouse_operator`; its password remains
in the SOPS-managed `clickhouse-server` Secret. Application users retain their
existing table grants and bounded query profiles.

Shared admission allows 64 SELECTs, 96 INSERTs and 128 total queries. The
worker account allows 64 queries / 2 GiB combined tracked query memory. The
current 11 worker-credential pods (default/high/low/solver/images workers,
scheduler, search indexer and two MCP replicas) each admit two client operations;
64 slots cover their 22-operation baseline and a complete process-replacement
overlap with 20 slots left. The public/admin/ingestion identities each allow
eight queries, user APIs allow 16, and reader/partner identities each allow eight.
Every non-worker identity is capped at 768 MiB combined tracked query memory.
The global 128-query cap leaves room for API reads and the importer while all
44 replacement-overlap worker requests are active; INSERT admission is separate
from SELECT admission. This is bounded burst capacity, not 128 CPU threads.

Per-query memory remains 256 MiB, parallelism two threads and execution limits
20 seconds (60 for reader profiles). Worker and user profiles inherit the ingest
profile, overriding only account concurrency and, for workers, aggregate memory.
Those overrides are CONST. The 4.5 GiB tracked server ceiling sits 1.5 GiB below
the 6 GiB container limit for caches, buffers and memory outside query tracking.
The 1 CPU / 2304 MiB scheduling reservation covers observed native ARM64 demand
with headroom; the 3 CPU limit allows bursts without reserving three node cores.
Keep the 6 GiB memory limit: resident working memory and reclaimable filesystem
cache have different peaks. Recheck admission and memory
before adding more producer replicas. Raising a per-client semaphore requires
recalculating shared-account fanout; the regression tests enforce that boundary.

The ConfigMap uses `subPath` mounts, which do not receive updates in running
pods. Both the environment changes and the `clickhouse-admission-headroom-v3`
PodTemplate revision make Fleet apply this update through the existing `Recreate`
strategy. Expect a brief interruption of the singleton, while its PVC and scoped
grants are preserved. Check worker-node CPU/memory requests before merging; the
larger reservation must fit a healthy eligible ARM64 worker. There is no fixed
node pin, manual restart or live SQL settings change. After reconciliation,
verify the effective user/server limits, Code202 and Code241 rates, cgroup memory,
CPU pressure and analytics reconciliation checkpoint progress.

Before a resource change recreates the singleton, stop new processing admissions
and let active jobs and analytics publishers drain while ClickHouse stays ready.
Keep solver dependencies available until their callers have finished. Pause API
writers for the serving gap, then restore the original replica counts after
database readiness. Direct analytics retries are bounded and do not provide a
durable replay queue across an outage. Follow the application
[maintenance gates](../../../applications/apps/devfeed/migrations.md#maintenance-gates).
Lower requests alone do not establish worker-failure placement capacity.

### Reproducible admission sizing

`python scripts/benchmark-clickhouse-admission.py` runs only disposable local
Docker containers using the pinned multi-architecture image and rendered Fleet
profiles. It requires native ARM64 by default and needs no cluster access,
production credentials or production data. Local
x86 smoke checks require the explicit `--allow-other-architecture` flag and do
not establish native performance parity.

Each configuration receives three million generated retained rows, 30 rounds
of 51 concurrent steady clients, then 30 rounds of 88 concurrent burst clients.
The burst includes 60 worker writers plus API/importer writers and eight report
readers, with acknowledged asynchronous INSERTs and FINAL report reads. The old
12/8/4 server / six-worker profile must reproduce Code202 rejections. The new
configuration must complete every steady/burst request with zero errors, match
all acknowledged writes against retained rows, and avoid an OOM. A deliberate
80-worker overload must still enforce the bounded worker cap and recover without
a restart. The JSON artifact records read/write latency, throughput, errors and
container peak memory. Generated data models admission pressure and retained
row scans; it does not claim the hosted runner matches Raspberry Pi CPU speed
or the production Longhorn I/O path. Live reconciliation and representative
production traffic remain required release gates.

The database bundle owns DevFeed's hook-only cross-namespace schema egress
policy independently of application upgrades. Explicit PVC volume bindings
preserve the database through the parent GitRepo's forced reconciliation.

## Prometheus and Grafana

The native ClickHouse endpoint exposes current metrics, profile-event counters
and asynchronous metrics at `/metrics` on port 9363. A ServiceMonitor scrapes it
every 60 seconds. Profile-event counters are renamed with a `_total` suffix
during scraping to follow Prometheus naming conventions. The dashboard uses
these names for all counter rates. Historical samples under the original names
remain in storage; renamed counter series start when this change reconciles
and rates need at least two new scrapes. Network policy admits only the Rancher Prometheus pods in
`cattle-monitoring-system` to that port; no public ingress or database
credentials are required for scraping.

The Fleet-managed dashboard ConfigMap in `cattle-dashboards` provisions
**ClickHouse Overview** (UID `clickhouse-overview`). Select the Prometheus
data source to inspect compact uptime, CPU (cores), resident memory, active-query, query-rate and
failure-rate cards, plus charts for query rates and
failures, mean duration, concurrency, memory, connections, rows/bytes,
MergeTree size and parts. These are server-wide metrics, including system
activity and health probes; mean duration is not a latency percentile.
Table size is not filesystem or PVC usage.

CPU and resident-memory cards are green below their configured requests
(1 core / 2.25 GiB), yellow from request to limit and red at or above their
limits (3 cores / 6 GiB). Requests are scheduling reservations, not failure
thresholds. Keep these dashboard thresholds in sync when changing deployment
resource requests or limits. Resident process memory differs from container
working-set usage and cgroup memory accounting.

CPU, resident memory, query rate and failed-query rate cards show sparklines
over the selected dashboard time range, with the latest available value.
Queries aggregate the single ClickHouse service across pod replacements and
include only successfully scraped targets at each timestamp. Pod IP changes
therefore retain one series and one current value per card.

Metrics configuration uses the same `subPath` mount. Future ConfigMap-only
edits require an intentional PodTemplate revision change for Fleet to recreate
the single replica and load the new files; mounted ConfigMap changes alone
do not reach the existing pod.

Validate the complete bundle with `kubectl kustomize
kubernetes/projects/database/apps/clickhouse`. Server-dry-run the changed
manifests, then after Git/Fleet reconciliation verify the ServiceMonitor target
is UP and the dashboard appears at `/d/clickhouse-overview` in Grafana.

Run the profile-boundary regression with `python -m unittest discover -s
kubernetes/projects/database/apps/clickhouse/tests -v`.


## Wide diagnostic-log merges

The server supplies `vertical_merge_algorithm_min_rows_to_activate=0` as a
MergeTree default. The existing minimum column threshold still limits vertical
merges to wide tables. Without this override, small merges of the 2,112-column
`system.metric_log` peaked at about 1.3 GB and exhausted the shared 1.5 GiB limit,
rejecting small analytical reads and restarting their reconciliation cycles.

A disposable test with the pinned 26.8.35.10 image and a matching wide schema
reduced a 40,000-row merge to 36.4 MB using this setting alone. Smaller row and
compression buffers did not solve the issue. The admission update retains this vertical-merge setting, compression settings
and log retention while increasing bounded query and container headroom.
The tradeoff is extra column passes during small wide-table merges.

The pod revision changes with this ConfigMap because its subPath mount cannot
receive file updates. Fleet recreates the singleton while preserving its PVC.
After convergence, verify the live MergeTree default, retained-table counts,
merge peak memory and application error rate; allow analytical repair to resume
from its checkpoints. Do not flush, optimize or alter live tables manually.
