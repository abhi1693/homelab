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

The main container requests `570m` CPU and `822Mi` memory, with limits of
`2500m` CPU and `4Gi` memory.
The pod keeps the chart's application group `568` and the NAS group `1000` as
supplemental groups. Its filesystem group remains compatible with the
root-owned media export; the NFS CSI driver leaves `fsGroupPolicy` unset so
Kubernetes does not recursively rewrite these `ReadWriteMany`, root-squashed
exports on every singleton restart.

- Image:
  `registry.home/ghcr.io/abhi1693/home-lab-jellyfin:10.11.8-pgsql.10.11.8-1-webhook-v21-overlay2`
- Plugin binaries: baked into the image from
  `kubernetes/images/jellyfin/required-plugins.txt`
- Episeerr playback events: official Webhook plugin `21.0.0.0`, configured
  from the `media-jellyfin-episeerr-webhook` ConfigMap
- Device auth token lookup: patched in `Jellyfin.Server.Implementations.dll`
  so sessions are read from PostgreSQL instead of only local startup cache.
- Database: `jellyfin`
- Role: `jellyfin`
- Pooler:
  `postgresql-pooler-jellyfin-rw.postgresql.svc.cluster.local:5432`
- Npgsql maximum pool size: `14`, capped below either PgBouncer replica's
  15-session backend pool so uneven Service hashing cannot queue Jellyfin's
  client connections behind idle session-bound backends.

The database project declares the Jellyfin role, database, RW pooler,
NetworkPolicy, and pooler PDB. The image build lives under
`kubernetes/images/jellyfin`.

On startup, the custom image replaces a SQLite `database.xml` with a PostgreSQL
provider config and keeps a one-time backup at
`/config/database.xml.sqlite-provider-backup`.
The current chart command also patches older published image entrypoints to
honor the same 14-connection cap; newly built images support
`POSTGRES_MAX_POOL_SIZE` directly.

Plugin settings and credentials should not be baked into the image. Mount
non-secret plugin XML/JSON as a ConfigMap and credentials as a Secret at the
entrypoint defaults:

- `/opt/jellyfin/plugin-config`
- `/opt/jellyfin/plugin-secrets`

Those mounts are dereferenced and copied into `/data/plugins/configurations` in
source order on startup, so later overlays replace duplicate files and the pod
starts with the same plugin settings without committing secrets.

The non-secret Episeerr destination is mounted separately at
`/opt/jellyfin/plugin-episeerr`. It sends episode playback start/stop events to
the in-cluster Episeerr webhook; the Jellyfin NetworkPolicy allows that egress.

Jellyfin Enhanced auto-skip outro is disabled in Git. An init container copies
the secret-backed Jellyfin Enhanced XML into `/opt/jellyfin/plugin-overrides`,
sets only `AutoSkipOutro=false`, and the main entrypoint applies that override
after the original plugin settings. The main container also sets
`JELLYFIN_ENHANCED_AUTO_SKIP_OUTRO=false` for images that support the same
patch directly in the entrypoint.

The deployment keeps `/config` and `/data` pod-local with `emptyDir` and runs a
single Jellyfin replica.

Shared generated state is mounted at
`/shared-data` from the `jellyfin-shared-data-nfs` RWX PVC, backed by the
retained NAS directory `media/jellyfin-shared-data-nfs`, and symlinked back
into Jellyfin's expected paths by the image entrypoint. The current shared paths are
metadata, collections, subtitles, live TV state, playlists, IMDb rating cache,
trickplay data, root profile data, and Shokofin state.
The PVC is sized for metadata growth and should only be expanded, not shrunk,
after it has been created.

The deployment sets `JELLYFIN_DISABLE_TRICKPLAY_AND_CHAPTER_IMAGES=true` so
Jellyfin does not restart the ARM64 ffmpeg trickplay/chapter extraction jobs
that repeatedly become unresponsive on 4K/HDR media. Existing shared trickplay
data can remain on the RWX PVC; the startup guard only prevents new failing
extraction work from being scheduled by library settings. The current values
patch the image entrypoint to follow `/data/root` through the shared-data
symlink before Jellyfin starts.

TrueCharts default PVC affinity remains disabled for this app, and the pod is
restricted to ARM64 nodes. Rollouts use `Recreate` so upgrades do not run two
Jellyfin pods at the same time.

## Home Assistant access

The Jellyfin ingress NetworkPolicy permits the Home Assistant workload in the
`home-assistant` namespace on TCP `8096`. Configure the Home Assistant Jellyfin
integration with the in-cluster endpoint:

- `http://jellyfin.media.svc.cluster.local:8096`

The matching Home Assistant Cilium policy is service-aware, so neither the
Jellyfin ClusterIP nor its pod IP is hard-coded.

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
8. Verify the seeded content on `jellyfin-shared-data-nfs` before cutover.
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

For a pod blocked before initialization by recursive NFS ownership processing,
follow
[`docs/runbooks/storage/nfs-csi-volume-ownership-storms.md`](../../../../../docs/runbooks/storage/nfs-csi-volume-ownership-storms.md).
