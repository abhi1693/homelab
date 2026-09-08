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

Direct PostgreSQL access is explicitly scoped for NetBox, Music Assistant, and
application migration/build jobs. Runtime clients otherwise use their dedicated
poolers. Each direct path still needs a bounded role and matching network policy.

## PgBouncer Connection Budgets

Keep aggregate backend capacity within the matching PostgreSQL role's
`connectionLimit`, including headroom for direct migration/build connections.
Single-replica poolers have no PDB; redundant poolers use `minAvailable: 1`.

The [PostgreSQL app reference](apps/postgresql/README.md) owns the per-app
connection budgets, resources, runtime tuning, and validation details. Keep
those values aligned with the manifests rather than duplicating them here.

## Valkey Contract

Valkey provides shared Redis-compatible queues and caches through Sentinel.
Apps should use app-specific logical DB indexes or explicit key namespaces and
should document those choices in their app README.

## Backups and Recovery

PostgreSQL physical backups use CloudNativePG's chart-supported object-store
configuration. Credentials are intentionally not stored as plaintext. Before a
database setup is considered complete, restore testing should be documented in
a runbook.
