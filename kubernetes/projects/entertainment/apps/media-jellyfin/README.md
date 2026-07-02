---
# Jellyfin

Fleet-managed Jellyfin media server.

The Fleet values now point Jellyfin at the custom image and PostgreSQL pooler.
The release is still intentionally gated by runtime secrets so it does not roll
successfully until the image is published, the database exists, and the
migration has been loaded.

## Runtime Direction

The target is not multiple pods sharing the same SQLite PVC. Jellyfin currently
runs as a single replica on the custom image backed by the shared PostgreSQL
cluster:

- Image:
  `registry.home/ghcr.io/abhi1693/home-lab-jellyfin:10.11.8-pgsql.10.11.8-1-cf39083`
- Plugin binaries: baked into the image from
  `kubernetes/images/jellyfin/required-plugins.txt`
- Device auth token lookup: patched in `Jellyfin.Server.Implementations.dll`
  so sessions are read from PostgreSQL instead of only local startup cache.
- Database: `jellyfin`
- Role: `jellyfin`
- Pooler:
  `postgresql-pooler-jellyfin-rw.postgresql.svc.cluster.local:5432`

The database project declares the Jellyfin role, database, RW pooler,
NetworkPolicy, and pooler PDB. The image build lives under
`kubernetes/images/jellyfin`.

On startup, the custom image replaces a SQLite `database.xml` with a PostgreSQL
provider config and keeps a one-time backup at
`/config/database.xml.sqlite-provider-backup`.

Plugin settings and credentials should not be baked into the image. Mount
non-secret plugin XML/JSON as a ConfigMap and credentials as a Secret at the
entrypoint defaults:

- `/opt/jellyfin/plugin-config`
- `/opt/jellyfin/plugin-secrets`

Those mounts are copied into `/data/plugins/configurations` on startup so the
pod starts with the same plugin settings without committing secrets.

Jellyfin Enhanced auto-skip outro is disabled in Git. An init container copies
the secret-backed Jellyfin Enhanced XML into `/opt/jellyfin/plugin-overrides`,
sets only `AutoSkipOutro=false`, and the main entrypoint applies that override
after the original plugin settings. The main container also sets
`JELLYFIN_ENHANCED_AUTO_SKIP_OUTRO=false` for images that support the same
patch directly in the entrypoint.

The YouTube library is reconciled from Git by
`jellyfin-youtube-library-reconciler`. The CronJob uses the existing
`arr-api-keys` Secret and reads `JELLYFIN_API_KEY`, falling back to
`QBT_TV_WATCH_JELLYFIN_API_KEY`. It ensures a `musicvideos` Jellyfin library
named `YouTube` exists at `/media/youtube/videos`, enables the baked
`YoutubeMetadata` provider for `MusicVideo` items, and triggers a library
refresh only when it changed Jellyfin configuration.

The same CronJob mounts `media-library-nas` at `/media` and reconciles
Jellyfin `.ignore` files under `/media/youtube/videos`. Directories with no
media files anywhere below them get a `.ignore` file so empty channel folders
do not appear in Jellyfin. If media later appears in an ignored directory, the
CronJob removes the stale `.ignore` file before refreshing Jellyfin.

Configured playlist-style shows are also reconciled by the same CronJob. The
`The Nation Wants to Guess` playlist remains downloaded under
`/media/youtube/videos/The Nation Wants to Guess`, but numbered media files are
hardlinked into
`/media/youtube/shows/The Nation Wants to Guess/Season 01/S01E## - ...` and a
separate Jellyfin `tvshows` library named `YouTube Shows` is managed at
`/media/youtube/shows`.

Episode numbers are parsed from the downloaded title when possible, so
newest-first playlist positions do not become TV episode numbers. Titles like
`EP12` and `EP 1` become `S01E12` and `S01E01`; a `Finale` entry without an
explicit episode number is placed after the highest explicit episode number.

Those show entries are hardlinks, not media copies, so they do not consume a
second copy of the video data on the NAS. If hardlinking fails, the reconciler
exits instead of falling back to a copy. The source playlist directory is kept
with a `.ignore` file so Jellyfin does not show the same episodes in both the
`YouTube` music-video library and the `YouTube Shows` TV library.

The reconciler also hardlinks downloaded YouTube artwork into Jellyfin's local
metadata image names for the show library. Playlist artwork is exposed as
series/season cover-style images, and per-video `.webp` thumbnails are exposed
as `<episode filename>-thumb.webp` files. This is only normal metadata artwork;
trickplay and chapter image extraction remain disabled for the managed YouTube
libraries.

The deployment keeps `/config` and `/data` pod-local with `emptyDir` and runs a
single Jellyfin replica.

Shared generated state is mounted at
`/shared-data` from the `jellyfin-shared-data` RWX PVC and symlinked back into
Jellyfin's expected paths by the image entrypoint. The current shared paths are
metadata, collections, subtitles, live TV state, playlists, IMDb rating cache,
trickplay data, root profile data, and Shokofin state.
The PVC is sized for metadata growth and should only be expanded, not shrunk,
after it has been created.

The deployment leaves `JELLYFIN_DISABLE_TRICKPLAY_AND_CHAPTER_IMAGES=false` so
Jellyfin's API-managed trickplay library options are preserved across pod
restart. The managed YouTube library options keep trickplay and chapter image
extraction disabled because downloaded 4K AV1 videos are too expensive for the
ARM64 media nodes to process reliably.

TrueCharts default PVC affinity remains disabled for this app, and the pod is
restricted to ARM64 nodes. Rollouts use `Recreate` so upgrades do not run two
Jellyfin pods at the same time.

## Required Secrets

Create the PostgreSQL role secret first so the database project can reconcile.
Use the same generated password for the media app secret later. The
`media/postgresql-app` secret is the release gate; creating it lets Jellyfin
start against PostgreSQL.

The image pull credential is the namespace-scoped `harbor-registry`
dockerconfigjson Secret for `registry.home`, backed by
`robot-namespace-media`.

```sh
kubectl -n postgresql create secret generic jellyfin-postgresql-app \
  --type=kubernetes.io/basic-auth \
  --from-literal=username=jellyfin \
  --from-literal=password='<generated-password>'

kubectl -n media create secret generic postgresql-app \
  --from-literal=username=jellyfin \
  --from-literal=password='<generated-password>' \
  --from-literal=dbname=jellyfin

kubectl -n media create secret generic arr-api-keys \
  --from-literal=SONARR_API_KEY='<sonarr-api-key>' \
  --from-literal=RADARR_API_KEY='<radarr-api-key>' \
  --from-literal=SONARR_ANIME_API_KEY='<sonarr-anime-api-key>' \
  --from-literal=JELLYFIN_API_KEY='<jellyfin-api-key>'

kubectl -n media create secret generic jellyfin-config-seed \
  --from-file=encoding.xml \
  --from-file=livetv.xml \
  --from-file=logging.default.json \
  --from-file=metadata.xml \
  --from-file=network.xml \
  --from-file=system.xml \
  --from-file=aspnet-data-protection-key.xml

kubectl -n media create secret generic jellyfin-plugin-config-seed \
  --from-file='<plugin-config-directory>'
```

## Cutover Outline

1. Publish the ARM64 Jellyfin image from GitHub Actions.
   Deploy only release tags through Renovate-managed values.
2. Create the PostgreSQL role Secret in `postgresql`.
3. Let Fleet reconcile the shared PostgreSQL role, database, pooler,
   NetworkPolicy, and PDB.
4. Quiesce Jellyfin, back up the current Jellyfin PVCs, and export a final copy
   of `/data/data/jellyfin.db`.
5. Convert the required live plugin configuration files under
   `/data/plugins/configurations` into ConfigMaps and Secrets.
6. Migrate SQLite data into PostgreSQL with the prepared `pgloader` wrapper or
   a disposable migration pod.
7. Create `media/postgresql-app`; the registry pull credential comes from the
   namespace-scoped `harbor-registry` Secret.
8. Seed `jellyfin-shared-data` from the current `/data` PVC.
9. Let Fleet roll Jellyfin on the custom image.
10. After login, libraries, playback progress, artwork, and integrations are
   verified, keep Jellyfin as one replica unless active-active support is
   completed later.

## Remaining No-Compromise Work

PostgreSQL is necessary, but not enough by itself. A real active-active Jellyfin
fork also needs:

- Leader election or PostgreSQL advisory locks for migrations, library scans,
  scheduled tasks, and metadata writes.
- Shared, mounted, or database-backed runtime configuration instead of
  pod-local mutable XML files.
- Continue validating auth/session behavior across browser and API clients
  without sticky routing.
- Distributed playback/session notifications.
- A transcode design where segment requests can survive pod loss without
  depending only on sticky sessions.

Until those are implemented, keep Jellyfin as a single replica.
