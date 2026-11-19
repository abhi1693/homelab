# Jellyfin image

ARM64 Jellyfin **12.4** with its native SQLite provider and a checksum-pinned
upstream plugin bundle. The official server base is pinned by digest in both
the Dockerfile and workflow. The unchanged upstream server and web files run
on digest-pinned Ubuntu 26.04, with checksum-pinned official Jellyfin FFmpeg
8.1.3 for Ubuntu, to replace the Debian image’s unpatched dependencies.
No PostgreSQL provider or patched Jellyfin core
assembly is included. Security updates are applied during the build.

`required-plugins.txt` locks download URLs and SHA-256 hashes;
`required-plugin-metadata.json` locks plugin identities, versions and ABI
requirements. Plugin binaries are refreshed from the image on startup while
persistent configurations remain in `/data/plugins/configurations`.

Shokofin **6.0.5-dev.40** (plugin version `6.0.5.4012`) is the upstream Jellyfin
12 build. It retains the stable plugin GUID. Its numeric version can exceed
some future stable builds, so stable adoption must explicitly replace the
pinned artifact and metadata rather than depend on automatic plugin updates.
This is the same image deployment procedure used for every other plugin.

The singleton uses Longhorn RWO volumes for `/config` and `/data`; SQLite is at
`/data/data/jellyfin.db`. Media and generated metadata retain their existing
NFS paths. The entrypoint preserves the server ID, seeds declared config
sources, links shared metadata, and disables costly trickplay/chapter jobs when
requested. Config and plugin credentials remain in SOPS-backed Secrets.

Production startup requires the PostgreSQL conversion receipt in
`/data/sqlite-migration.receipt.json`, with `mode=cutover`, a quiesced source
and successful integrity checks. Set `JELLYFIN_REQUIRE_MIGRATION_RECEIPT=false`
only for a new empty server such as the isolated CI smoke fixture. Qualification
uses `JELLYFIN_QUALIFICATION=true` with the separate candidate database.

The image workflow publishes `12.4-sqlite-1` after native ARM64 build, security
scans and smoke checks for the exact server version, read-only root filesystem,
SQLite creation, administrator authentication and every pinned plugin loading.
Runtime rollout additionally requires data-preservation and API checks.

For rollback, stop the singleton through Fleet, restore the matching pre-upgrade
SQLite/configuration backup, and restore the matching image through Git. Do not
start an older Jellyfin against a database upgraded by a newer server. The
original PostgreSQL database and pre-cutover dump remain retained for the
separate provider-migration rollback boundary.
