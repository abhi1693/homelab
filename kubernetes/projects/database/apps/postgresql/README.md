# PostgreSQL

This app owns the CloudNativePG cluster, application roles, databases, and
PgBouncer poolers used by home-lab apps.

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
| `jellyfin` | `jellyfin-rw` | implicit | 12 | 15 |
| `dispatcharr` | `dispatcharr-rw` | implicit | 6 | 8 |
| `gitrank` | `git-rank-rw` | 8 | 8 | 8 |
| `shipyardhq` | `shipyardhq-rw` | 16 | 32 | 32 |
| `harbor` | `harbor-rw` | chart-managed | 36 | 36 |
| `netbox` | `netbox-rw` | disabled | 6 | 10 |
| `registry_artifacts` | `registry-artifacts-rw` | 12 | 12 | 12 |
| `firefly` | `firefly-iii-rw` | implicit | 8 | 10 |

`shipyardhq` has database-side headroom above the normal rollout surge budget:
`3 web pods * PG_POOL_MAX 4 + 1 worker pod * PG_POOL_MAX 4 = 16`.

`registry_artifacts` uses `DB_POOL_SIZE=8` and `DB_MAX_OVERFLOW=4`, so its
maximum app-side pool demand is 12 connections.

`git-rank` uses `DB_POOL_SIZE=1` and `DB_MAX_OVERFLOW=1`, keeping the API, two
worker pods, and one scheduled trigger pod aligned with the `gitrank` role
limit during normal operation.

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
exports the top 25 normalized query families by cumulative execution time. The
slow-query table ranks the execution time added during the selected Grafana time
range, so old cumulative-heavy query families drop out when they are no longer
active in that window.
