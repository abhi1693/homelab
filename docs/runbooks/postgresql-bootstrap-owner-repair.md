# PostgreSQL bootstrap owner repair

## Cause and desired state

CNPG's generated `postgresql-app` secret contains the bootstrap username `app`.
Setting `cluster.initdb.owner: postgres` leaves that existing secret unchanged,
so the primary repeatedly rejects the username during password reconciliation.
The desired state is bootstrap owner/database `app`, an explicitly managed
non-superuser `app` role using the existing secret, and a retained `app` Database.
Keep `enableSuperuserAccess: false` and all existing application credentials.

## Staged GitOps rollout

Use two Git revisions, allowing Fleet to reconcile each before the next.
Do not publish the final bootstrap switch before the prerequisite checks pass.

1. Confirm the latest Backup completed, continuous WAL archiving works, and all
   three instances are healthy. Verify `postgresql-app` still has username
   `app` without printing its password. Check that no workloads use this secret
   as credentials for a different account.
2. Publish the new `cluster.roles` entry for `app` and `databases` entry for
   `app`, leaving `cluster.initdb.database` and `cluster.initdb.owner` at
   `postgres` for this first revision. Keep the existing secret intact.
   CNPG 1.30 reconciles managed roles before bootstrap credentials; the existing
   mismatch can therefore continue while the prerequisite role is created.
3. Wait for `postgresql-app` Database `.status.applied: true`, and verify the
   `app` role is login-enabled and non-superuser and owns the `app` database.
   The Kubernetes Secret and Database share a name but are different kinds.
4. Publish the final `cluster.initdb.database: app` and `owner: app` values.
   This changes reconciliation and the monitoring connection target; it does
   not initialize the existing data directory again.

Find the primary before running the read-only SQL check:

```sh
kubectl -n postgresql get cluster postgresql
kubectl -n postgresql get database postgresql-app -o yaml
kubectl -n postgresql exec <primary-pod> -c postgres -- psql -X -d postgres -c \
  "SELECT rolname, rolsuper, rolcanlogin FROM pg_roles WHERE rolname = 'app';
   SELECT datname, pg_get_userbyid(datdba) AS owner
   FROM pg_database WHERE datname IN ('app', 'postgres');"
```

## Verification

- Fleet's desired and applied bundle IDs match for the PostgreSQL release.
- All three instances remain Ready and restart counts do not increase.
- `app` exists on the primary and both replicas; SQL connection to it succeeds.
- Fresh primary logs no longer report the bootstrap username mismatch.
- `cnpg_last_error` is zero on each instance and all three expose
  `cnpg_pg_stat_database_xact_commit` after multiple scrapes.
- Application health checks and their existing database credentials still work.
- Streaming replication and WAL archiving remain healthy.

## Rollback

If the monitoring switch fails, revert only `cluster.initdb.database` to
`postgres` through Git while retaining owner `app`, the managed role/database,
and the existing secret. This restores the prior monitoring target without
reintroducing the username mismatch. This is an interim state, not a bootstrap
configuration for a new cluster. Investigate the `app` database connection
failure before restoring the final configuration.

Do not set `ensure: absent`, change database ownership for existing application
databases, delete or regenerate secrets, recreate the Cluster, or remove PVCs
as part of this repair. Retain the new database during any rollback.

The controller ordering and secret-preservation behavior were checked against
[CNPG 1.30 instance reconciliation](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.30.0/internal/management/controller/instance_controller.go)
and [credential secret reconciliation](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.30.0/internal/controller/cluster_create.go).
