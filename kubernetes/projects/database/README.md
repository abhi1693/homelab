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
| `postgresql-pooler-pdb` | PDBs for app poolers. | Keeps at least one pooler pod available during voluntary disruption. |
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
6. one pooler PDB.

This pattern keeps shared PostgreSQL efficient while preserving app-level
boundaries.

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
| `jellyfin` | `jellyfin-rw` | implicit | 12 | 15 |
| `dispatcharr` | `dispatcharr-rw` | implicit | 6 | 8 |
| `gitrank` | `git-rank-rw` | 8 | 8 | 8 |
| `shipyardhq` | `shipyardhq-rw` | 16 | 32 | 32 |
| `harbor` | `harbor-rw` | chart-managed | 36 | 36 |
| `netbox` | `netbox-rw` | disabled | 6 | 10 |
| `firefly` | `firefly-iii-rw` | implicit | 8 | 10 |

## Valkey Contract

Valkey provides shared Redis-compatible queues and caches through Sentinel.
Apps should use app-specific logical DB indexes or explicit key namespaces and
should document those choices in their app README.

## Backups and Recovery

PostgreSQL physical backups use CloudNativePG's chart-supported object-store
configuration. Credentials are intentionally not stored as plaintext. Before a
database setup is considered complete, restore testing should be documented in
a runbook.
