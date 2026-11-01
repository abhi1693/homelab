# PostgreSQL

CloudNativePG injects a `bootstrap-controller` init container into each Pooler
Deployment without exposing a Pooler-specific resource field. The namespace
`LimitRange` supplies missing `10m` CPU and `32Mi` memory requests plus a
`128Mi` memory limit. The defaults leave explicitly configured PostgreSQL and
PgBouncer resources intact.

This app owns the CloudNativePG cluster, application roles, databases, and
PgBouncer poolers used by home-lab apps.

Private client-specific database contracts and credentials are documented in
their private deployment bundles.

## PostgreSQL image catalog

The chart creates the namespaced `ImageCatalog` named `postgresql` from
`imageCatalog.images` in `values.yaml`. The cluster selects it through
`cluster.imageCatalogRef`, using `version.postgresql` as the major version.
All three PostgreSQL instances use the selected catalog image. The catalog
pins the PostgreSQL 17.11 Bookworm image by multi-platform OCI index digest,
including Linux ARM64. Verify GHCR/Harbor index parity before changing it.
The exact `tag@sha256` reference is declared once in `values.yaml`.
Update that entry through Git and Fleet to roll out future image changes;
do not also set `cluster.imageName`. PgBouncer images remain configured separately.
### Bookworm collation maintenance

Image changes can update collation libraries independently of PostgreSQL.
Wait for Fleet convergence, three healthy instances on the intended digest,
streaming replication, continuous archiving and application access before
separately authorized database maintenance.

All database defaults use `C` collation. NetBox additionally uses the ICU
`public.natural_sort` collation (`und-u-kn`), including indexes in its branch
schemas. A library upgrade can change its sort order even though PostgreSQL's
version is unchanged. Run the checked-in maintenance script on the current
primary after the rollout:

```sh
primary=$(kubectl --context local -n postgresql get cluster postgresql -o jsonpath='{.status.currentPrimary}')
kubectl --context local -n postgresql exec -i "$primary" -c postgres -- \
  psql -X -U postgres -d netbox -v ON_ERROR_STOP=1 \
  < kubernetes/projects/database/apps/postgresql/netbox-collation-maintenance.sql
```

The script skips an already-matching collation version. Otherwise it rebuilds
every index using `public.natural_sort` concurrently, checks index validity, and
only then refreshes the recorded collation version. It stops on errors; inspect
any invalid concurrent-build leftovers before retrying. Never refresh the
version merely to suppress a warning. Check NetBox health and collation versions
on every instance afterwards. Database maintenance is an explicitly authorized
operator action, not an automatic Fleet reconciliation hook.

Rolling back the image also rolls back the collation libraries: repeat the
collation check and rebuild on the restored image before refreshing its version.
Reverting the image alone does not undo indexes built with newer ICU libraries.

## Monitoring collector database

The cluster uses `app` as its `cluster.initdb.database` and owner, matching
CNPG's existing generated `postgresql-app` secret. The role is explicitly
managed without superuser privileges, and the database has a `retain` reclaim
policy. Keep both present: CloudNativePG runs monitoring queries without an
explicit `target_databases` list against the bootstrap database. The custom
`pg_stat_statements_top` query continues to target `postgres` explicitly.

Changing the bootstrap owner to `postgres` does not update an existing
generated secret. It causes repeated `wrong username 'app' in secret, expected
'postgres'` reconciliation errors. Do not rename the secret's user to
`postgres`: bootstrap-owner password reconciliation is separate from
`enableSuperuserAccess: false`.

For an existing cluster where `app` was removed, follow the staged
[bootstrap owner repair](../../../../../docs/runbooks/postgresql-bootstrap-owner-repair.md).
Adding the managed role and retained database repairs the existing cluster;
changing `initdb` alone does not run bootstrap again.

The custom Prometheus rules alert when `cnpg_last_error` remains non-zero and
when fewer ready PostgreSQL instances expose
`cnpg_pg_stat_database_xact_commit`. These checks detect partial exporter
failure even when the metrics endpoint and Prometheus target remain up.

## Storage redundancy

The three PostgreSQL instances are hard-spread across nodes and synchronously
replicate database state. Each instance has a separate 32Gi data PVC and 4Gi WAL
PVC.
Those six Longhorn volumes each use three storage replicas, for 324Gi of
nominal scheduled block capacity beneath the three application-level database
copies. This intentionally accepts compounded storage and write amplification
so every individual PVC can tolerate replica loss at the block layer.

Continuous WAL archiving and daily object-store backups remain the independent
recovery path. New or replacement PVCs inherit the same three-replica policy
from the Longhorn StorageClass.

Remote backups in Cloudflare R2 use `backups.retentionPolicy: 3d`, providing a
three-day recovery window. CloudNativePG removes obsolete backups after a
successful backup completes. A base backup older than three days and the WAL
needed to recover from it may remain to cover the start of that window.

Use the ScheduledBackup and current Backup status plus remote object inventory
to establish recovery coverage. A retained Kubernetes Backup object does not
prove its remote data is still available. Do not rerun dated one-shot Backup
manifests as a recurring schedule.

## PgBouncer connection budgets

Every pooler sets `min_pool_size: 1` and `server_idle_timeout: 120` to preserve
a warm backend per database/user pool while retiring excess unused connections
after two minutes instead of the ten-minute default. The minimum is a retention
floor, not an eagerly allocated reservation for every possible database; PgBouncer
only replenishes it for pools with a connected client or forced database user.
Count authentication-pool connections alongside application pools when reviewing
PostgreSQL headroom.

This timeout applies only after a backend is returned to the unused pool. It
does not kill running queries, long transactions, or idle sessions still attached
to a client in session mode. `client_idle_timeout` remains disabled and existing
SQL statement/transaction timeout policies are unchanged. CNPG reloads these
PgBouncer parameters without restarting pods. Keep the default 3600-second
server lifetime; do not use `server_lifetime: 0`, which disables backend reuse.
Validate the effective value with
`SHOW CONFIG`, then confirm lower backend counts, no queued clients, no new
restarts, and successful application access. Keep a client connected for longer
than 120 seconds and verify its backend PID survives both a running query and a
client-idle interval. Revert the parameter through Git if a rollback is needed.

Keep each pooler's backend capacity at or below the matching PostgreSQL role
`connectionLimit`:

```text
backend capacity = pooler instances * default_pool_size
```

For apps with explicit DB pool settings, keep backend capacity aligned with the
declared app-side maximum connection demand.

| Role | Pooler | App-side budget | Backend capacity | Role limit |
| --- | --- | ---: | ---: | ---: |
| `devfeed` | `devfeed-rw` | Interactive APIs and ordinary background workers | 20 | 40 |
| `devfeed_chimely` | `devfeed-rw` | Chimely-managed | 20 | 24 |
| `jellyfin` | `jellyfin-rw` | 14 | 30 | 32 |
| `shipyardhq` | `shipyardhq-rw` | 20 | 30 | 32 |
| `harbor` | `harbor-rw` | chart-managed | 24 | 36 |
| `netbox` | direct | implicit | n/a | 10 |
| `wardn_hub` | `wardn-hub-rw` | implicit | 12 | 12 |
| `wardn_ai` | `wardn-ai-rw` | paused | 0 | 12 |
| `wardn_license` | `wardn-license-rw` | paused | 0 | 12 |
| `firefly` | `firefly-iii-rw` | implicit | 4 | 10 |
| `zitadel` | `zitadel-rw` | 16 | 32 | 32 |
| `home_assistant` | `home-assistant-rw` | implicit | 10 | 12 |

DevFeed preserves its twenty interactive slots. The finite analytics importer uses
a separately bounded direct writer connection, below the shared role limit of forty.
The retired pipeline/report projector pooler and access policies are removed after
producer handoff. The role ceiling does not reserve global PostgreSQL capacity.
Recheck live global headroom, include authentication connections, and follow
the [migration maintenance gates](../../../applications/apps/devfeed/migrations.md#maintenance-gates)
before changing the application schema.

`wardn-ai-rw` is paused at zero instances alongside Wardn AI. Its database and
role remain retained in the shared cluster. Restoring its single instance
provides six backend slots.

Jellyfin caps its Npgsql pool at 14 connections. Each session-mode PgBouncer
replica has 15 backend slots, so either replica can absorb the application's
entire connection budget even if Service hashing is uneven. The two replicas'
30-slot theoretical backend capacity remains below the role limit of 32.

`shipyardhq` has database-side headroom above the normal runtime budget:
`3 web pods * PG_POOL_MAX 4 + 2 worker pods * PG_POOL_MAX 4 = 20`.
The release builder uses `PG_POOL_MAX=1` in each of its two Next.js workers,
limiting its direct connection path to two sessions. Each session-mode pooler
provides 15 backend slots after one 14-slot instance showed waiting clients
while PostgreSQL sessions were idle during the 28 October recovery. The two
poolers expose 30 backend slots, leaving two role connections for the direct
build path within the unchanged limit of 32. Pool mode and app-side limits
remain unchanged.
ZITADEL caps each of its two replicas at eight open connections. Each
session-pool replica can therefore absorb the full 16-connection steady-state
budget even when service load balancing is uneven. The two poolers expose 32
backend slots in aggregate, matching the role limit; connections are opened on
demand, so the normal app budget still leaves 16 role connections available.
## PgBouncer resource reservations

Pooler request and replica settings are declared in `values.yaml`. Review
them against sustained usage and queueing in the `pgbouncer-dashboard`.
NetBox connects directly and does not add a pooler.

Only poolers with at least two replicas have a `minAvailable: 1` PDB.
Single-replica poolers intentionally have no PDB because one would either remain
permanently unhealthy or block all voluntary disruption.

Poolers rely on CloudNativePG's generated TCP readiness probe against the
local PgBouncer port 5432 and intentionally have no backend-coupled liveness
probe. A backend DNS, connection, or PostgreSQL availability interruption must
not restart an otherwise healthy proxy.
Each PostgreSQL instance requests `750m` CPU and `5Gi` memory, with a `5Gi`
memory limit. The three instances reserve `2.25` CPU cores and `15Gi` in total
so every replica has capacity to become primary. CPU is uncapped, so the pods
remain Burstable. The CPU request protects scheduling share under contention;
it does not reduce the amount of database work.
Budget memory for connection state, filesystem cache, startup, replication and
maintenance. Check cgroup reclaim/refault activity as well as working-set usage
before changing the resource allocation.

Changing cluster resources through Fleet triggers CloudNativePG's normal
rolling update: replicas are replaced one at a time, then the existing
`unsupervised` / `switchover` policy promotes an updated replica before replacing
the former primary. Expect interrupted database connections for applications
sharing this cluster; Kubernetes in-place resize support does not make this a
restart-free change. Confirm node reservation headroom and healthy, caught-up
replicas before merging the resource change.
After a resource change, verify Fleet convergence, all three instances' live
resources and readiness, streaming replication, application database access,
and memory usage through a complete workload and backup cycle. Compare fresh
cgroup reclaim/refault deltas and normal report-publisher query durations after
the cache warms, rather than treating a ready pod as performance recovery.

## PostgreSQL runtime tuning

The connection and memory settings are sized for the shared PostgreSQL pod
and the declared PgBouncer connection budgets:

| Parameter | Value | Rationale |
| --- | ---: | --- |
| `max_connections` | 160 | Bounds aggregate pooler, direct-client, monitoring, control and replication demand; review headroom before enabling paused clients. |
| `shared_buffers` | 512MiB | Adds buffer capacity while retaining filesystem-cache, connection and maintenance headroom within the 5GiB container budget. |
| `effective_cache_size` | 3GiB | Models shared buffers and usable filesystem cache for query planning; it does not allocate or reserve memory. |
| `work_mem` | 4MiB | Avoids multiplying a larger allocation across concurrent sort and hash operations. Expensive maintenance queries must use statement-local overrides. |
| `wal_buffers` | 16MiB | Bounds WAL buffering independently of connection count; monitor buffer-full events. |
| `checkpoint_timeout` | 15 minutes | Allows longer checkpoint intervals with the configured 1GiB `max_wal_size` soft limit; retained WAL can exceed it. |
| `autovacuum_vacuum_scale_factor` | 0.1 | Vacuums changing tables when dead tuples exceed 50 plus 10% of the last analyzed row estimate, unless a table overrides these settings. |
| `autovacuum_analyze_scale_factor` | 0.02 | Refreshes stale row estimates sooner after bulk deletes so vacuum thresholds reflect current table size. |
| `idle_in_transaction_session_timeout` | 5 minutes | Releases locks and snapshots abandoned inside transactions without terminating ordinary idle pooled sessions. |

Changing `shared_buffers` requires a PostgreSQL restart. Reconcile buffer and
resource changes through Fleet and verify all three instances' live settings,
resources and readiness after CloudNativePG finishes its rolling update.
Compare query durations, physical reads and cgroup reclaim/refault deltas after
cache warmup. A higher buffer hit ratio or a lower CPU percentage relative to
the larger request alone does not prove lower workload demand. Keep monitoring
requested checkpoints and WAL free space with the existing 1GiB `max_wal_size`
and 4GiB WAL volume.

`log_lock_waits` is enabled to make waits longer than the existing one-second
`deadlock_timeout` visible in PostgreSQL logs. Do not set a global
`statement_timeout` or `idle_session_timeout`: migrations and maintenance can
legitimately run for longer, and session-mode PgBouncer intentionally keeps
ordinary backend sessions idle.

DevFeed's [migration hook](../../../applications/apps/devfeed/migrations.md#devfeed-jit-default)
sets `jit=off` only for the `devfeed` role in the `devfeed` database. The shared
server default and other roles/databases, including `devfeed_chimely`, stay
unchanged. Existing pooled backends inherit the default on their next PostgreSQL
connection; the hook verifies a fresh direct session without restarting the
cluster or poolers.

## Table-local autovacuum

The high-churn tables below override the cluster-wide `0.1` vacuum and `0.02`
analyze scale factors. They use `0.02` and `0.01` respectively, while retaining
PostgreSQL's fixed 50-tuple thresholds. This makes maintenance respond to each
table's change rate without increasing autovacuum frequency for the rest of the
cluster.

The SQL script targets the following high-churn tables; verify `pg_class.reloptions`
before assuming its overrides are still present after a table recreation:

- `wardn_hub.public.event_records`
- `devfeed.public.articles`, `article_analysis_jobs`,
  `research_verification_jobs`, `topic_analysis_jobs`, and
  `topic_relation_proposals`
- `harbor.public.artifact`, `artifact_blob`, `artifact_reference`, `blob`,
  `tag`, and `task`
- `shipyardhq.public."EventEnvelope"`

Use current PostgreSQL statistics to assess their effect; historical row counts
are not a tuning baseline. The CNPG custom query
`pg_stat_user_tables_autovacuum` exports the selected tables' live tuples, dead
tuples, dead-tuple ratio, modifications since analyze, and the effective dead-tuple
vacuum trigger from every CNPG
instance. The Prometheus alerts join those samples with
`cnpg_pg_replication_in_recovery` and evaluate only the current primary;
standby statistics can have small denominators and are not valid for this
ratio. Both alerts require dead tuples to exceed the effective vacuum trigger:
the table's threshold plus its scale factor times `pg_class.reltuples`, falling
back to cluster settings when table overrides are absent. The warning additionally
requires an 8% ratio for 15 minutes; critical requires 15% for 30 minutes. This
avoids warning about small tables before autovacuum is due (for example, 80 dead
rows in a 709-row table with a trigger of 120.9). The query targets PostgreSQL 17;
review its threshold calculation when upgrading PostgreSQL.

Run `python scripts/check-postgresql-observability.py` from the repository root
with `promtool` and PyYAML installed to check rule syntax and six threshold and
primary/standby scenarios. Execute the custom query read-only against both target
databases before deploying query changes.

[`autovacuum-high-churn-tables.sql`](autovacuum-high-churn-tables.sql) is the
idempotent source for the table storage parameters and the controlled vacuum.
It uses a five-second lock timeout for each table change, a ten-minute
statement timeout for the controlled vacuum, and a 2ms vacuum cost delay.
Reapply it as the PostgreSQL superuser if a migration recreates one of the
tables, then remeasure `n_live_tup`, `n_dead_tup`,
`n_mod_since_analyze`, and the last vacuum/analyze timestamps in
`pg_stat_user_tables`.

Changing `max_connections` or `wal_buffers` requires a PostgreSQL restart. A
decrease to a hot-standby-sensitive parameter makes CloudNativePG restart the
primary in place before its replicas. Cluster chart 0.9.0 exposes `stopDelay`,
which is set to 300 seconds instead of CNPG's conservative 1800-second default.
The operator's default 180-second `smartShutdownTimeout` leaves two minutes for
fast shutdown and WAL/archive completion before the kubelet's termination
deadline. This bounds voluntary eviction replacement while preserving a clean
shutdown window; `failoverDelay` remains zero and `switchoverDelay` retains the
operator's one-hour data-safety default. Schedule restart-requiring parameter
changes as a write-maintenance event; reload-only parameters do not have that
interruption.

## Grafana dashboards

Grafana auto-loads dashboards from ConfigMaps in `cattle-dashboards` with the
`grafana_dashboard: "1"` label.

- `pgbouncer-dashboard` tracks pool queueing, wait time, server slots, and
  PgBouncer CPU pressure.
- `postgresql-query-performance-dashboard` focuses on slow
  `pg_stat_statements` query families and supporting optimization signals:
  query latency, call rate, rows per call, shared block reads/dirties, temp
  block usage, and shared block I/O time. Use the CNPG dashboard for general
  cluster, backend, storage, connection, and resource panels.

The database performance dashboard uses the chart-managed
`cluster.monitoring.customQueries` entry named `pg_stat_statements_top`, which
exports the top 25 query IDs by cumulative execution time. It reads
`pg_stat_statements(false)` so statement text is not materialized or exported
as a high-cardinality Prometheus label, limits the working set before ranking,
and uses a statement-local 16MiB `work_mem` guard so replicas near the
10,000-statement tracking limit do not spill the function result to temporary
storage. The setting reverts at the end of each collector query; global
`work_mem` remains 4MiB. The slow-query table ranks the execution time added
during the selected Grafana time range, so old cumulative-heavy query families
drop out when they are no longer active in that window.

## Data-volume headroom

Each instance declares a 32Gi data claim and a separate 4Gi WAL claim.
Monitor capacity, WAL growth and object-store backup health. Expand through
CNPG/Fleet; verify all three PVC capacities, in-pod filesystem sizes, replication
and disk alerts after reconciliation. PVCs cannot shrink, so volume expansion
has no capacity rollback. Retain claims and database records during recovery.

`wardn-license-rw` is operator-paused at zero instances alongside its API and
console. Its database, role and credentials are retained; its dedicated PDB is
omitted until the [application resumption procedure](../../../applications/apps/wardn-license-server/README.md#shutdown-state)
is explicitly requested.

## Resource review — 28 October 2026

Each PostgreSQL instance reserves `2560Mi`, preserving the `5Gi` limit,
`750m` CPU request, burstable CPU, shared buffers, connection limits, and
three-instance synchronous topology. The follow-up fourteen-day review measured
a `2357Mi` per-container working-set peak with no recorded OOM events. Reducing
the request from `3Gi` releases `1536Mi` across three instances while retaining
the existing burst allowance. This changes scheduler reservations, not cache
allocation; CPU remains sized for primary failover.

Existing poolers with sufficient history reserve 96Mi instead of 56Mi because
observed working-set peaks were 55–77Mi. The busy DevFeed pooler reserves 100m
CPU; Wardn Hub and Jellyfin poolers reserve 10m and remain CPU-burstable. The
new commerce pooler is unchanged because its history is too short.

The CNPG operator performs the existing sequential rollout;
verify 3/3 Ready, streaming replication, archiving, and unchanged PVC identities.

## Retired app poolers — 28 October 2026

Hyperlocal Kitchen, Launchboard, Wardn AI and Wardn License Server pooler
definitions were removed after app retirement. They already had zero
instances. Their PostgreSQL databases, roles and credentials remain retained;
shared cluster sizing and active application poolers are unchanged.

The Training instructor uses the retained `netbox_instructor` database and its own non-superuser role, limited to ten connections. Credentials are SOPS-managed independently of production NetBox.
