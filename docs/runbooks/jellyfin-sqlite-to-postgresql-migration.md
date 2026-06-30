# Jellyfin SQLite To PostgreSQL Migration

This runbook is for the experimental PostgreSQL-backed Jellyfin image.

## Snapshot

The live SQLite database is stored at `/data/data/jellyfin.db`. Take the final
snapshot only after Jellyfin writes are stopped or quiesced. A hot snapshot is
acceptable for migration rehearsal, but not for the final cutover.

Also copy these plugin databases for reference:

- `/data/data/playback_reporting.db`
- `/data/data/introskipper/introskipper.db`
- `/data/data/introskipper/introskipper-cache.db`

The core pgloader path migrates `jellyfin.db` only.

## Required Order

1. Start the custom `jellyfin` image once against an empty config directory and
   the empty PostgreSQL database. This seeds schema and
   `__EFMigrationsHistory`.
2. Stop that seed instance.
3. Run pgloader with the prepared `jellyfindb.load` against the checkpointed
   SQLite copy.
4. Restore or mount remaining non-database state, including plugin
   configuration, metadata/generated assets, and any required Secrets.
5. Start Jellyfin with the PostgreSQL-backed image.

If the pgloader run reports a missing `__EFMigrationsHistory` table, the
PostgreSQL-backed image was not started once against an empty database before
loading data.

## Local Rehearsal

Generated migration prep directories live under `.local/jellyfin-migration/`
and are intentionally ignored by Git because they contain live application data.

With a prepared snapshot directory:

```sh
cd .local/jellyfin-migration/<timestamp>
kubectl -n postgresql port-forward svc/postgresql-pooler-jellyfin-rw 15432:5432
```

In another shell:

```sh
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=15432
export POSTGRES_DB=jellyfin
export POSTGRES_USER=jellyfin
export POSTGRES_PASSWORD='<password>'
./pgloader/run-pgloader-docker.sh
```

This assumes the Jellyfin PostgreSQL role, database, pooler, and secrets already
exist and that the target database has been seeded by the PostgreSQL-backed
Jellyfin image once.
