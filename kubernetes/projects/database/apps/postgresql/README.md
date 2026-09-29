# PostgreSQL

CloudNativePG injects a `bootstrap-controller` init container into each Pooler
Deployment without exposing a Pooler-specific resource field. The namespace
`LimitRange` supplies missing `10m` CPU and `32Mi` memory requests plus a
`128Mi` memory limit. Explicit PostgreSQL and PgBouncer resources are unchanged.

This app owns the CloudNativePG cluster, application roles, databases, and
PgBouncer poolers used by home-lab apps.

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
replicate database state. Each instance has a separate 20Gi data PVC and 4Gi WAL
PVC.
Those six Longhorn volumes each use three storage replicas, for 216Gi of
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

`backup-20260916.yaml` requests a one-off full physical backup through Fleet
after the September 16 reduction to seven days. Its fixed resource name prevents
ordinary reconciliations from requesting another backup. Check the Backup's
`status.phase` and instance logs for completion and retention cleanup; old
Kubernetes Backup records alone do not prove that their remote objects remain.
The `-retry` request prefers a standby after a primary OOM and failover aborted
the original attempt's PostgreSQL backup session.

## PgBouncer connection budgets

Every pooler sets `min_pool_size: 1` and `server_idle_timeout: 120` to preserve
a warm backend per database/user pool while retiring excess unused connections
after two minutes instead of the ten-minute default. The minimum is a retention
floor, not an eagerly allocated reservation for every possible database; PgBouncer
only replenishes it for pools with a connected client or forced database user. A September 2026
sample showed 135 of 160 PostgreSQL connections while PgBouncer held 94 unused
backends and only 33 client-attached backends. Authentication pools also retain
connections and must be counted alongside application pools.

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
| `devfeed` | `devfeed-rw` | 13 steady processes; one connection each | 20 | 24 |
| `devfeed_chimely` | `devfeed-rw` | Chimely-managed | 20 | 24 |
| `jellyfin` | `jellyfin-rw` | 14 | 30 | 32 |
| `shipyardhq` | `shipyardhq-rw` | 20 | 28 | 32 |
| `launchboard` | `launchboard-rw` | 4 | 8 | 10 |
| `harbor` | `harbor-rw` | chart-managed | 24 | 36 |
| `netbox` | direct | implicit | n/a | 10 |
| `wardn_hub` | `wardn-hub-rw` | implicit | 12 | 12 |
| `wardn_ai` | `wardn-ai-rw` | paused | 0 | 12 |
| `wardn_license` | `wardn-license-rw` | implicit | 8 | 12 |
| `firefly` | `firefly-iii-rw` | implicit | 4 | 10 |
| `zitadel` | `zitadel-rw` | 16 | 32 | 32 |
| `music_assistant` | direct | 2 | 2 | 4 |
| `home_assistant` | `home-assistant-rw` | implicit | 10 | 12 |

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
limiting its direct connection path to two sessions. Even if the 28 pooler
backend slots are all occupied, two role connections remain available for
short-lived build and reconnect activity.
`launchboard` has a dedicated retained database and role; it does not read or
write ShipyardHQ's database. Its two session-mode poolers expose eight backend
slots against a four-connection app pool, leaving two direct role connections
for migrations and reconnect activity.
ZITADEL caps each of its two replicas at eight open connections. Each
session-pool replica can therefore absorb the full 16-connection steady-state
budget even when service load balancing is uneven. The two poolers expose 32
backend slots in aggregate, matching the role limit; connections are opened on
demand, so the normal app budget still leaves 16 role connections available.
Music Assistant connects directly to the read-write service because its
YouTube Music cache catalog uses a two-connection `asyncpg` pool with durable
row leases and `FOR UPDATE SKIP LOCKED` claims. Its role limit of four preserves
reconnect headroom without allocating another PgBouncer deployment. The
`music_assistant` database is retained if its declarative Database resource is
removed. Its Cilium ingress policy permits the cluster's `host` and
`remote-node` identities on PostgreSQL port 5432 because Music Assistant
requires host networking for player discovery. This covers both a primary on
the same node and primary failover to another trusted K3s node.

## PgBouncer resource reservations

Pooler request and replica settings are declared in `values.yaml`. Review
them against sustained usage and queueing in the `pgbouncer-dashboard`.
NetBox and Music Assistant connect directly and do not add poolers.

Only poolers with at least two replicas have a `minAvailable: 1` PDB.
Single-replica poolers intentionally have no PDB because one would either remain
permanently unhealthy or block all voluntary disruption.

Poolers rely on CloudNativePG's generated TCP readiness probe against the
local PgBouncer port 5432 and intentionally have no backend-coupled liveness
probe. A backend DNS, connection, or PostgreSQL availability interruption must
not restart an otherwise healthy proxy.
Each PostgreSQL instance requests `250m` CPU and `3Gi` memory, with a `3Gi`
memory limit. The three instances reserve `9Gi` in total so every replica has
capacity to become primary. CPU is uncapped, so the pods remain Burstable.
The previous `1536Mi` limit caused primary OOMs with roughly 140 client
connections; observed working-set peaks reached 1533Mi. Preserve the added
headroom for connection memory, startup, replication, and maintenance.
After a resource change, verify Fleet convergence, all three instances' live
resources and readiness, streaming replication, application database access,
and memory usage through a complete workload and backup cycle.

## PostgreSQL runtime tuning

The connection and memory settings are sized for the shared PostgreSQL pod
and the 18 active PgBouncer replicas:

| Parameter | Value | Rationale |
| --- | ---: | --- |
| `max_connections` | 160 | The 14-day maximum was 104 and p99 was 90. Adding Wardn License Server raises the modeled pooler, control, replication, monitoring, and direct-client ceiling to about 148. |
| `shared_buffers` | 256MiB | Preserves the existing buffer allocation so the larger pod budget provides connection and maintenance headroom. |
| `effective_cache_size` | 768MiB | Preserves the conservative planner cache hint; it does not allocate memory. |
| `work_mem` | 4MiB | Avoids multiplying a larger allocation across concurrent sort and hash operations. Expensive maintenance queries must use statement-local overrides. |
| `wal_buffers` | 16MiB | The previous automatic 8MiB allocation recorded about 1.27 million buffer-full events over 14 days. |
| `checkpoint_timeout` | 15 minutes | Almost all checkpoints were time-driven while checkpoint writes totaled about 26.8GiB over 14 days. The 1GiB WAL ceiling remains unchanged. |
| `autovacuum_vacuum_scale_factor` | 0.1 | Vacuums changing tables when dead tuples exceed 50 plus 10% of the last analyzed row estimate, unless a table overrides these settings. |
| `autovacuum_analyze_scale_factor` | 0.02 | Refreshes stale row estimates sooner after bulk deletes so vacuum thresholds reflect current table size. |
| `idle_in_transaction_session_timeout` | 5 minutes | Releases locks and snapshots abandoned inside transactions without terminating ordinary idle pooled sessions. |

`log_lock_waits` is enabled to make waits longer than the existing one-second
`deadlock_timeout` visible in PostgreSQL logs. Do not set a global
`statement_timeout` or `idle_session_timeout`: migrations and maintenance can
legitimately run for longer, and session-mode PgBouncer intentionally keeps
ordinary backend sessions idle.

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
primary in place before its replicas. Cluster chart 0.8.1 exposes `stopDelay`,
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

## September 2026 data-volume headroom

Increase the retained data claims from 10Gi to 20Gi through CNPG/Fleet; WAL remains
4Gi. The latest scheduled backup completed before this change and each Longhorn
node had over 250Gi free. Verify all three PVC capacities and in-pod filesystem
sizes after reconciliation, then check replication and the low-disk alert.
Volume expansion cannot be rolled back by shrinking the PVC. Retain all claims
and database records; this change does not introduce an analysis-history deletion policy.
