---
# Database Project

Fleet-managed shared database infrastructure.

| Path | Bundle | Type | Notes |
|------|--------|------|-------|
| `apps/database-helm-repositories` | `database-helm-repositories` | GitOps | Registers Rancher chart repositories used by shared database infrastructure. |
| `apps/cnpg-operator` | `cnpg-operator` | Helm | Installs the cluster-wide CloudNativePG operator in `cnpg-system`. |
| `apps/postgresql` | `postgresql-helmop` | GitOps wrapper | Creates `HelmOp/postgresql` and `ConfigMap/postgresql-values`. |
| `apps/postgresql` | `postgresql` | HelmOps | Deploys the shared CloudNativePG PostgreSQL cluster with R2-backed physical backups. |
| `apps/postgresql-networkpolicy` | `postgresql-networkpolicy` | Raw YAML | Restricts shared PostgreSQL access to app-specific poolers. |
| `apps/postgresql-pooler-pdb` | `postgresql-pooler-pdb` | Raw YAML | Keeps at least one PgBouncer pod available per app during voluntary disruption. |
| `apps/valkey` | `valkey-helmop` | GitOps wrapper | Creates `HelmOp/valkey` and `ConfigMap/valkey-values`. |
| `apps/valkey` | `valkey` | HelmOps | Deploys the Bitnami Valkey chart as the shared Sentinel service. |
| `apps/valkey-networkpolicy` | `valkey-networkpolicy` | Raw YAML | Restricts Valkey/Sentinel access to approved app clients. |

HelmOps apps use the app name for the `HelmOp`, Helm release, and workload.
The GitOps wrapper bundle keeps the `-helmop` suffix because Fleet also creates
a child bundle with the app name.

`database-helm-repositories` must be ready before Database Helm and HelmOps
bundles.

## PostgreSQL HA Contract

The shared PostgreSQL cluster runs three CNPG instances with required quorum
synchronous replication: every acknowledged commit must reach one standby, and
quorum failover must confirm that committed data is present before promoting a
replica. This favors consistency over accepting writes when no synchronous
standby is available.

Applications must connect only through their own RW PgBouncer pooler service,
never directly to `postgresql-rw`. Each app gets its own database, login role,
Secret, RW pooler, NetworkPolicy, and pooler PodDisruptionBudget.

Poolers are spread by hostname with hard per-revision scheduling rules. The
`pod-template-hash` match key lets a new Deployment revision roll out without
being blocked by old-revision pods, while still preventing same-revision pooler
pods from landing on the same node. The pinned `cloudnative-pg/cluster` chart
does not render CNPG `serviceTemplate`, so service-level locality settings such
as `internalTrafficPolicy` remain deferred until the chart supports them or the
poolers move to explicit Pooler manifests.

Active app-owned databases are `dispatcharr`, `gitrank`, `jellyfin`, `netbox`,
and `shipyardhq`.

For each new app:

1. Add one managed role with `login: true`, no elevated privileges, and a
   bounded `connectionLimit`.
2. Add one database owned by that role with `databaseReclaimPolicy: retain`.
3. Add one RW pooler with at least two instances, `poolMode: session` unless the
   app is verified safe for transaction pooling, and hard per-revision topology
   spread by hostname.
4. Keep the role `connectionLimit` above the total pooler server pool size, with
   headroom for migrations, while leaving capacity reserved for other apps and
   operator maintenance.
5. Add a matching NetworkPolicy that allows only that app namespace to reach its
   pooler.
6. Add a matching pooler PDB with `minAvailable: 1`.

PostgreSQL physical backups use CloudNativePG's chart-supported
`barmanObjectStore` configuration and write WAL/base backups to Cloudflare R2 at
`s3://home-lab-postgresql/`. The credential Secret is intentionally not stored
in Git; `Secret/postgresql-r2-backup` must exist in the `postgresql` namespace
with `ACCESS_KEY_ID` and `ACCESS_SECRET_KEY` keys.

The scheduled backup is daily at midnight using CNPG's six-field cron syntax,
with a 30-day recovery-window retention policy. R2 encrypts objects at rest
automatically, so per-object S3 encryption headers are disabled for R2
compatibility.

Before this database is considered disaster-recovery complete, perform and
document a restore test into a separate namespace or cluster.
