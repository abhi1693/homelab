# PostgreSQL

CloudNativePG injects a `bootstrap-controller` init container into each Pooler
Deployment without exposing a Pooler-specific resource field. The namespace
`LimitRange` supplies missing `10m` CPU and `32Mi` memory requests plus a
`128Mi` memory limit. Explicit PostgreSQL and PgBouncer resources are unchanged.

This app owns the CloudNativePG cluster, application roles, databases, and
PgBouncer poolers used by home-lab apps.

## Monitoring collector database

The cluster explicitly uses the required `postgres` database as its
`cluster.initdb.database` and owner. CloudNativePG runs monitoring queries
without an explicit `target_databases` list against that bootstrap database,
so it must remain present for the default SQL-derived metric families.

The custom Prometheus rules alert when `cnpg_last_error` remains non-zero and
when fewer ready PostgreSQL instances expose
`cnpg_pg_stat_database_xact_commit`. These checks detect partial exporter
failure even when the metrics endpoint and Prometheus target remain up.

## Storage redundancy

The three PostgreSQL instances are hard-spread across nodes and synchronously
replicate database state. Each instance has separate 4Gi data and WAL PVCs.
Those six Longhorn volumes use one storage replica through the scoped
`longhorn-volume-overrides` Fleet bundle, reducing scheduled block capacity
from 72Gi to 24Gi while the cluster still maintains three database copies.

A one-replica Longhorn volume cannot survive loss of its backing disk by
itself; availability comes from CloudNativePG failover to another instance.
Continuous WAL archiving and daily object-store backups remain the independent
recovery path. New or replacement PVCs must be added to the scoped Longhorn
override before they are treated as single-replica volumes.

## PgBouncer connection budgets

Keep each pooler's backend capacity at or below the matching PostgreSQL role
`connectionLimit`:

```text
backend capacity = pooler instances * default_pool_size
```

For apps with explicit DB pool settings, keep backend capacity aligned with the
declared app-side maximum connection demand.

| Role | Pooler | App-side budget | Backend capacity | Role limit |
| --- | --- | ---: | ---: | ---: |
| `jellyfin` | `jellyfin-rw` | implicit | 14 | 15 |
| `shipyardhq` | `shipyardhq-rw` | 16 | 28 | 32 |
| `harbor` | `harbor-rw` | chart-managed | 24 | 36 |
| `netbox` | `netbox-rw` | disabled | 0 | 10 |
| `wardn_hub` | `wardn-hub-rw` | implicit | 12 | 12 |
| `wardn_ai` | `wardn-ai-rw` | implicit | 6 | 12 |
| `firefly` | `firefly-iii-rw` | disabled | 0 | 10 |
| `zitadel` | `zitadel-rw` | 16 | 32 | 32 |
| `music_assistant` | direct | 2 | 2 | 4 |

`shipyardhq` has database-side headroom above the normal runtime budget:
`3 web pods * PG_POOL_MAX 4 + 1 worker pod * PG_POOL_MAX 4 = 16`.
The release builder uses `PG_POOL_MAX=1` in each of its two Next.js workers,
limiting its direct connection path to two sessions. Even if the 28 pooler
backend slots are all occupied, two role connections remain available for
short-lived build and reconnect activity.
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

The requests use the latest available seven-day p95/p99 review with burst
headroom. `wardn-hub-rw` requests 50m CPU per replica, `jellyfin-rw` requests
15m, and the other active poolers request 10m. Every active pooler requests 56Mi
memory and retains its 192Mi memory limit. With the NetBox and Firefly poolers
paused, the scheduler reserves 185m CPU and 560Mi memory across 10 active
replicas.
Wardn Hub's two replicas used 16m at p95 and 39m at p99 in aggregate, with a
123m maximum. Their combined 100m request therefore preserves p99 headroom
while CPU remains unlimited for short bursts. Revisit the requests if sustained
CPU usage or pool queueing rises. The `pgbouncer-dashboard` exposes both
signals.

Only poolers with at least two replicas have a `minAvailable: 1` PDB. Paused
and single-replica poolers intentionally have no PDB because one would either
remain permanently unhealthy or block all voluntary disruption.

Poolers rely on CloudNativePG's generated TCP readiness probe against the
local PgBouncer port 5432 and intentionally have no backend-coupled liveness
probe. A backend DNS, connection, or PostgreSQL availability interruption must
not restart an otherwise healthy proxy. The ShipyardHQ override that ran
`pg_isready` directly against `postgresql-rw` was removed after it restarted
PgBouncer during a backend interruption.

Each PostgreSQL instance uses a 250m CPU request. In the latest available
seven-day window, per-instance p95 ranged from 104m to 172m and p99 ranged from
159m to 220m. CPU remains unlimited so short bursts, including the observed
1.05-core maximum on the primary, can exceed the scheduler reservation. Its
896Mi memory request remains based on the prior memory review; the 1Gi memory
limit is unchanged.

## PostgreSQL runtime tuning

The connection and memory settings are sized for the shared 1Gi PostgreSQL pod
and the 12 active PgBouncer replicas:

| Parameter | Value | Rationale |
| --- | ---: | --- |
| `max_connections` | 160 | The 14-day maximum was 104 and p99 was 90. The modeled pooler, control, replication, monitoring, and direct-client ceiling is about 132. |
| `shared_buffers` | 256MiB | Retains the 25% memory allocation; per-database cache-hit ratios remain between 98.7% and 99.99%. |
| `effective_cache_size` | 768MiB | Gives the planner a realistic 75% cache hint for the 1Gi cgroup; it does not allocate memory. |
| `work_mem` | 4MiB | Avoids multiplying a larger allocation across concurrent sort and hash operations. Expensive maintenance queries must use statement-local overrides. |
| `wal_buffers` | 16MiB | The previous automatic 8MiB allocation recorded about 1.27 million buffer-full events over 14 days. |
| `checkpoint_timeout` | 15 minutes | Almost all checkpoints were time-driven while checkpoint writes totaled about 26.8GiB over 14 days. The 1GiB WAL ceiling remains unchanged. |
| `autovacuum_vacuum_scale_factor` | 0.1 | Vacuums changing tables when dead tuples reach about 10% of the last analyzed row estimate. |
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

| Table | Rows after analyze | Dead rows | Vacuum trigger | Analyze trigger |
| --- | ---: | ---: | ---: | ---: |
| `wardn_hub.public.event_records` | 74,737 | 29 | about 1,545 | about 798 |
| `shipyardhq.public."EventEnvelope"` | 23,352 | 0 | about 518 | about 284 |

These figures were measured immediately after the controlled July 22, 2026
`VACUUM (ANALYZE)` run. Before it, `EventEnvelope` had inconsistent estimates:
`pg_stat_user_tables` reported 54 live and 297 dead rows while `pg_class`
estimated 22,572 rows. The analyze corrected the live estimate to 23,352, so
the apparent 84.6% dead-row ratio was stale-statistics distortion rather than
the table's actual composition.

[`autovacuum-high-churn-tables.sql`](autovacuum-high-churn-tables.sql) is the
idempotent source for the table storage parameters and the controlled vacuum.
It uses a five-second lock timeout, ten-minute statement timeout, and a 2ms
vacuum cost delay. Reapply it as the PostgreSQL superuser if a migration
recreates one of the tables, then remeasure `n_live_tup`, `n_dead_tup`,
`n_mod_since_analyze`, and the last vacuum/analyze timestamps in
`pg_stat_user_tables`.

Changing `max_connections` or `wal_buffers` requires a PostgreSQL restart. A
decrease to a hot-standby-sensitive parameter makes CloudNativePG restart the
primary in place before its replicas. Chart 0.7.0 does not expose the Cluster's
`smartShutdownTimeout`, so session-mode pooler backends can hold the default
smart shutdown open for its full 180 seconds before CNPG escalates to a fast
shutdown. Schedule those parameter changes as a write-maintenance event; the
reload-only parameters above do not have that interruption.

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
