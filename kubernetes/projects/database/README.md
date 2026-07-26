# Database Project

The Database project owns shared database and cache infrastructure for the lab:
CloudNativePG, PostgreSQL, PgBouncer-style poolers, Valkey Sentinel, database
network policy, and related dashboards.

Fleet tracks this project through the `home-lab-database` GitRepo.

## Why This Project Exists

Small clusters do not have unlimited CPU, memory, or storage. Instead of
running a separate PostgreSQL and Redis-compatible service per app, this project
centralizes those services and gives applications isolated roles, databases,
poolers, logical DBs, and network access.

The benefit is efficient shared infrastructure. The cost is that database and
cache changes have a wider blast radius, so connection limits, pooler budgets,
PDBs, backups, and monitoring are treated as first-class configuration.

## App Catalog

| App | What it does | Why it matters |
| --- | --- | --- |
| `database-helm-repositories` | Registers chart repositories. | Makes database charts available to Rancher/Fleet. |
| `cnpg-operator` | Installs CloudNativePG operator and CRDs. | Enables PostgreSQL `Cluster`, backups, monitoring, and poolers. |
| `postgresql` | Shared PostgreSQL cluster, roles, databases, poolers, custom queries, and dashboards. | Primary relational database for many apps. |
| `postgresql-networkpolicy` | Restricts database access. | Keeps apps on their approved pooler paths. |
| `postgresql-pooler-pdb` | PDBs for multi-replica app poolers. | Keeps at least one redundant pooler pod available during voluntary disruption. |
| `valkey` | Shared Valkey replication and Sentinel. | Queues and caches for apps. |
| `valkey-networkpolicy` | Restricts Valkey/Sentinel access. | Keeps cache/queue access explicit. |

## PostgreSQL Contract

Applications should connect through their own RW pooler service rather than
directly to the PostgreSQL primary. Each app should have:

1. one login role with a bounded `connectionLimit`;
2. one database owned by that role;
3. one app-specific Secret contract;
4. one RW pooler with at least two instances when the app needs availability;
5. one NetworkPolicy allowing only the app namespace to reach that pooler;
6. one `minAvailable: 1` pooler PDB when the pooler has at least two replicas.

This pattern keeps shared PostgreSQL efficient while preserving app-level
boundaries.

The ShipyardHQ release-builder Job is the only direct-client exception. Its
long-running prerender step connects to `postgresql-rw` so a PgBouncer
backend-DNS cache failure cannot abort a release. Paired NetworkPolicies select
only `shipyardhq` pods with component `next-builder` and PostgreSQL instance
pods on TCP 5432; ShipyardHQ runtime pods continue to use their RW pooler.

## PgBouncer Connection Budgets

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
| `firefly` | `firefly-iii-rw` | implicit | 4 | 10 |
| `zitadel` | `zitadel-rw` | implicit | 16 | 24 |

Paused and single-replica poolers intentionally have no PDB. A
`minAvailable: 1` budget is useful only when another replica can remain
available during a voluntary disruption.

PostgreSQL itself is tuned for the 1Gi instance limit and the bounded pooler
fleet. The cluster allows 160 connections, keeps 256MiB of shared buffers and
4MiB of global per-operation memory, uses a 768MiB planner cache hint, and
spreads routine checkpoints across a 15-minute interval. See the PostgreSQL
app README for the measured connection, WAL, checkpoint, and autovacuum
rationale.

## Valkey Contract

Valkey provides shared Redis-compatible queues and caches through Sentinel.
Apps should use app-specific logical DB indexes or explicit key namespaces and
should document those choices in their app README.

## Backups and Recovery

PostgreSQL physical backups use CloudNativePG's chart-supported object-store
configuration. Credentials are intentionally not stored as plaintext. Before a
database setup is considered complete, restore testing should be documented in
a runbook.
