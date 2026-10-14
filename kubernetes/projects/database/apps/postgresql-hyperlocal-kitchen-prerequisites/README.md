# Hyperlocal Kitchen PostgreSQL prerequisites

This Fleet bundle provides the SOPS-encrypted `hyperlocal-kitchen-postgresql`
basic-auth Secret for the shared CNPG cluster's retained `kitchen` role/database,
and client/pooler API-server network policies. It must reconcile before the
PostgreSQL HelmOp, which consumes that Secret through `values.yaml`.

The application bundle uses the same local database password in its encrypted
SQLAlchemy URLs, connects through `postgresql-pooler-hyperlocal-kitchen-rw`, and
uses `postgresql-rw` only for migration/schema readiness. Both namespace-side
network-policy boundaries require the `hyperlocal-kitchen-database-client`
label. No live database changes have been applied by this preparation.

See `kubernetes/projects/applications/apps/hyperlocal-kitchen/README.md` for the
image publication, authentication, migration, and Fleet rollout sequence.
