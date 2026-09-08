---
# Jellyfin

Fleet-managed Jellyfin media server.

Jellyfin runs as one replica on the custom PostgreSQL-backed image.
Required images, database objects, and runtime Secrets must exist before Fleet
can start a replacement pod.

## Runtime

The main container requests `300m` CPU and `1125Mi` memory, with a `4Gi`
memory limit and no CPU limit. TrueCharts `resources.limits.cpu: 0` explicitly
disables its inherited CPU cap. Scans and transcodes may burst above the request.
Changing resources rolls this singleton and creates a serving gap; deploy
through Fleet outside active playback, then verify playback and imports.
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
Increment `workload.main.podSpec.annotations.home-lab.io/config-seed-revision`
whenever a startup-copied config or plugin seed changes so Fleet rolls the pod
and applies the new seed.

The JavaScript Injector seed includes a `MediaBar-Exclude-Anime` filter. It is
scoped to the Media Bar plugin's random movie/series request and removes items
from the Shokofin VFS or items carrying the exact `anime` tag. This also covers
anime that still resides in the TV or Movies library without hiding it from
library pages, search, or other home-screen sections.

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

## Availability

Keep Jellyfin as one replica. Shared PostgreSQL does not provide coordination
for concurrent scans, configuration writes, playback sessions, or transcodes.
Active-active deployment requires application changes, not a replica increase.

For a pod blocked before initialization by recursive NFS ownership processing,
follow
[`docs/runbooks/storage/nfs-csi-volume-ownership-storms.md`](../../../../../docs/runbooks/storage/nfs-csi-volume-ownership-storms.md).
