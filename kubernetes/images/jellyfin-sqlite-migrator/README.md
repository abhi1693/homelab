# Jellyfin SQLite migrator

One-time PostgreSQL to SQLite conversion for Jellyfin **10.11.8**. The public
schema files contain schema and SQLite EF migration history only. User data,
configuration archives and database dumps must never enter the image or Git
unless encrypted with SOPS.

The converter reads PostgreSQL in a repeatable-read, read-only transaction,
retains SQLite's own EF migration history, maps UUIDs, booleans, binary fields
and Npgsql infinite timestamps, and verifies all application row counts and
order-independent SHA-256 row checksums. Foreign-key and integrity checks must
pass before publishing a database. Existing unrecognized databases are refused.

`prepare.py` restores encrypted configuration snapshots onto Longhorn block
volumes. Qualification uses a separate read-only media candidate. Cutover waits
for every other Jellyfin pod to stop using read-only Kubernetes API access,
takes a fresh PostgreSQL dump, converts again, and writes a cutover receipt.
Subsequent init runs retain accepted SQLite data. PostgreSQL is never mutated.
Backups remain in `/data/migration-backup`; they contain private data.

```sh
cd kubernetes/images/jellyfin-sqlite-migrator
python -B -m unittest -v test_migrate
```

The dedicated image workflow runs native ARM64 smoke tests and security scans.
Deploy only its verified immutable image digest through Fleet.
