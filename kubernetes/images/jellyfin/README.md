---
# Jellyfin Image

ARM64 Jellyfin image with the live Jellyfin plugin set and the experimental
PostgreSQL database provider built in. The upstream published PostgreSQL
provider image is currently amd64-only, while this cluster is ARM64.

The image also carries repo-owned Jellyfin core patches under `patches/` for
state that must be shared between replicas before upstream Jellyfin supports
this deployment model directly.

This image intentionally keeps plugin assemblies as an image concern. Runtime
database, pooler, credentials, plugin configuration, and migration ordering
remain Kubernetes and Fleet concerns.

## Build Inputs

- Base server image: `jellyfin/jellyfin:10.11.8`
- Jellyfin plugins: pinned in `required-plugins.txt`
- Jellyfin plugin metadata: pinned in `required-plugin-metadata.json`
- PostgreSQL provider source: `JPVenson/Jellyfin.Pgsql` tag `10.11.8-1`
- Jellyfin core patch: `patches/001-device-manager-db-source-of-truth.patch`
- Published image tag family: `ghcr.io/abhi1693/home-lab-jellyfin:*`

## Runtime Contract

The container requires:

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`

Optional:

- `POSTGRES_SSLMODE`
- `POSTGRES_TRUSTSERVERCERTIFICATE`
- `JELLYFIN_CONFIG_SOURCE_DIRS`
- `JELLYFIN_DATA_SOURCE_DIRS`
- `JELLYFIN_ENHANCED_AUTO_SKIP_OUTRO`
- `JELLYFIN_SHARED_DATA_DIR`
- `JELLYFIN_SHARED_DATA_PATHS`
- `JELLYFIN_DISABLE_TRICKPLAY_AND_CHAPTER_IMAGES`
- `JELLYFIN_SERVER_ID`

The image stores baked plugins under `/opt/jellyfin/plugins/<PluginName>`.
At startup, it syncs those baked plugins into
`$JELLYFIN_PLUGIN_DIR`, defaulting to `/data/plugins`, creates or updates
`$JELLYFIN_DATABASE_CONFIG`, defaulting to `/config/database.xml`, and then
starts Jellyfin. Every replica therefore starts from the same image-defined
plugin set.

The patched `Jellyfin.Server.Implementations.dll` makes `DeviceManager`
read device sessions and access-token lookups from PostgreSQL instead of only
the local process cache populated at startup. It also makes device token
updates and deletes idempotent at the database layer so concurrent replicas do
not fail when they touch the same device session. This keeps browser and API
auth tokens portable across active Jellyfin pods.

Plugin auto-updates are disabled in baked `meta.json` files so running replicas
do not drift. Update `required-plugins.txt` and rebuild the image to change the
fleet plugin set.

Plugin configuration is runtime state, not image content. Mount ConfigMaps and
Secrets into either of these default source directories:

- `/opt/jellyfin/plugin-config`
- `/opt/jellyfin/plugin-secrets`

The entrypoint overlays those files into `/data/plugins/configurations` before
starting Jellyfin. Override `JELLYFIN_PLUGIN_CONFIG_SOURCE_DIRS` with a
colon-separated directory list if the chart uses different mount paths.

Set `JELLYFIN_ENHANCED_AUTO_SKIP_OUTRO=false` to force Jellyfin Enhanced's
`AutoSkipOutro` setting off after plugin configuration overlays are copied. The
entrypoint patches only that field in existing Jellyfin Enhanced XML and user
settings files.

Server configuration can be seeded the same way with
`JELLYFIN_CONFIG_SOURCE_DIRS`. The entrypoint copies those files into
`/config` before writing the PostgreSQL database configuration.

Set `JELLYFIN_SERVER_ID` to a fixed 32-character hex value to keep
`/data/data/device.txt` stable across pod replacement. Without this, a pod-local
data directory can generate a new public server ID during failover or rollout,
which breaks Jellyfin web clients that have cached the previous selected server.

For active-active pods, keep `/config` and `/data` pod-local and mount shared
metadata/artwork state separately. Set `JELLYFIN_SHARED_DATA_DIR` to the shared
mount path and the entrypoint will replace selected data paths with symlinks.
The default shared paths are:

- `/data/metadata`
- `/data/data/collections`
- `/data/data/subtitles`
- `/data/data/livetv`
- `/data/data/playlists`
- `/data/data/imdb-ratings-cache`
- `/data/root`
- `/data/Shokofin`

Override `JELLYFIN_SHARED_DATA_PATHS` with a colon-separated relative path list
when changing the shared state contract.

Set `JELLYFIN_DISABLE_TRICKPLAY_AND_CHAPTER_IMAGES=true` to force existing
library option files under `/data/root` to disable trickplay image extraction,
trickplay extraction during scans, chapter image extraction, and chapter image
extraction during scans before Jellyfin starts.

The baked plugin set currently includes:

- AniDB `11.0.0.0`
- Collection Sections `2.3.8.0`
- Custom Tabs `0.2.8.0`
- DLNA `10.0.0.0`
- File Transformation `2.5.9.0`
- Home Screen Sections `2.5.9.0`
- IMDb Ratings `1.0.0.19`
- JavaScript Injector `3.4.0.0`
- Jellyfin Enhanced `11.9.0.0`
- Media Bar `2.4.10.0`
- Merge Versions `10.11.0.1`
- Plugin Pages `2.4.9.0`
- Shoko `6.0.5.11`
- TMDb Box Sets `13.0.0.0`
- Trakt `29.0.0.0`
- YouTube Metadata `1.0.3.15`

## Risk

The PostgreSQL provider is experimental upstream. Treat this image as the
foundation for a lab cutover and fork hardening, not as a drop-in production
replacement for SQLite. The device-token patch intentionally changes Jellyfin
core behavior and must be reviewed when Jellyfin or the PostgreSQL provider is
updated.
