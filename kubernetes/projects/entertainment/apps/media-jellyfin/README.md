---
# Jellyfin

Fleet-managed Jellyfin media server.

Jellyfin runs as one replica using native SQLite on Longhorn block storage.
Required images, retained PVCs, and runtime Secrets must exist before Fleet
can start a replacement pod.

## Runtime

The main container requests `100m` CPU and `768Mi` memory, with a `4Gi`
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
  `registry.home/ghcr.io/abhi1693/home-lab-jellyfin:12.4-sqlite-1@sha256:a49d52d6b1e4bfe6463c1b9e2aa8297bffce08fdd3131ea62b04ef733dac8991`
- Plugin binaries: baked into the image from
  `kubernetes/images/jellyfin/required-plugins.txt`
- Episeerr playback events: official Webhook plugin `22.0.0.0`, configured
  from the `media-jellyfin-episeerr-webhook` ConfigMap
- Database: native SQLite at `/data/data/jellyfin.db` on the 8Gi
  `jellyfin-sqlite-data` Longhorn RWO PVC.
- Persistent configuration: 1Gi `jellyfin-sqlite-config` Longhorn RWO PVC.
- The original PostgreSQL database and role remain retained for rollback.

Jellyfin **12.4** uses unchanged upstream server/web files on Ubuntu 26.04
with official Jellyfin FFmpeg 8.1.3. The image contains no PostgreSQL provider
or patched Jellyfin core. Plugin builds are pinned for Jellyfin 12, including
upstream Shokofin dev.40 (`6.0.5.4012`). Its GUID is unchanged; future stable
adoption explicitly replaces the image lock rather than rely on numeric
automatic-update ordering.

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

The deployment keeps `/config` and `/data` on Longhorn RWO PVCs and runs one
replica with `Recreate`. SQLite is never placed on NFS.

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

The SOPS resources provide configuration seeds, plugin credentials and API
keys. The PostgreSQL credential is used only by the one-time conversion init
container while migration tooling is retained; the Jellyfin process does not
receive it.

The image pull credential is the namespace-scoped `harbor-registry`
dockerconfigjson Secret for `registry.home`, backed by
`robot-namespace-media`.

```sh
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

Keep Jellyfin as one replica. Shared storage does not provide coordination
for concurrent scans, configuration writes, playback sessions, or transcodes.
Active-active deployment requires application changes, not a replica increase.

For a pod blocked before initialization by recursive NFS ownership processing,
follow
[`docs/runbooks/storage/nfs-csi-volume-ownership-storms.md`](../../../../../docs/runbooks/storage/nfs-csi-volume-ownership-storms.md).

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `media/jellyfin/jellyfin` | 220m → 100m | 900Mi → 768Mi | 4Gi → 4Gi |

## SQLite migration and rollback

The isolated candidate passed database row checksums, foreign-key/integrity
checks, matching server identity, all four users/permissions, all item counts,
and identical watched/resume API results on 10.11.8. The temporary candidate and its database access rule have been removed
through Git after validation.

Production's migration init container waits for all other Jellyfin pods to
stop, creates `/data/migration-backup/postgres-final.dump`, and exports a fresh
read-only repeatable-read snapshot. It preserves SQLite EF history, converts
all application rows and verifies counts/checksums, foreign keys and integrity.
A cutover receipt prevents starting from the older qualification snapshot;
future init runs retain the accepted SQLite database. Config snapshots remain
SOPS-encrypted in Git and private in the retained data-volume backup.

Rollback across the provider boundary requires scaling Jellyfin to zero in Git,
restoring the old PostgreSQL image/entrypoint and its pod-local config/data
settings from commit `cf47806b5`, then starting it through Fleet. PostgreSQL has
not been changed by the converter. Writes made after SQLite cutover require a
separate reconciliation before reverting to PostgreSQL; do not discard them.

See the [migration tool](../../../../images/jellyfin-sqlite-migrator/README.md)
for schema and validation details. The migrator ServiceAccount can only list
pods; it cannot change Kubernetes resources. The temporary candidate database
network rule is removed when qualification resources are retired.

The migration entrypoint ConfigMap is retained in both `media` and
`fleet-local` while the rollback boundary is open. Declaring the earlier
namespace explicitly keeps Fleet inventory consistent after qualification.

Before the 12.4 rollout, a separate init container uses
`backup-before-upgrade.py` to make a SQLite online-backup copy after the old
server stops, verify its integrity/foreign keys, and archive configuration,
plugin settings and library/VFS definitions without following media symlinks.
The immutable rollback point is retained at `/data/pre-upgrade-12.4`; reruns
verify and retain it rather than overwrite it with an upgraded database.

The pre-12.4 backup contains the matching SQLite database, configuration,
plugin settings and library/VFS definitions. To roll back the server upgrade,
stop Jellyfin in Git, restore `/data/pre-upgrade-12.4/jellyfin.db` and the
matching configuration archive while the server is stopped, then restore the
10.11.8 SQLite values from commit `56f341f4b` through Fleet. Never run 10.11.8
against the migrated 12.4 database. The independent PostgreSQL rollback boundary
and dump remain retained; do not revert across post-cutover user writes.

Startup/readiness probes require the public system API to report the existing
completed setup wizard; the basic health endpoint alone can become available
before startup finishes. Liveness continues to use the lightweight health probe.

## Daily SQLite backups

`jellyfin-sqlite-backup` runs daily at **04:15 Asia/Kolkata**, retaining seven
validated recovery points under `/shared-data/sqlite-backups` on the retained
NAS. A Fleet-managed bootstrap Job proves the same backup path immediately.
PostgreSQL backups no longer contain Jellyfin's live state, and Longhorn has no
active backup target; these NAS copies provide the ongoing database recovery
path after the migration.

The backup pod must share the singleton's node for RWO mounts. It mounts the
SQLite/config volumes read-only, uses SQLite's online Backup API (including
committed WAL), checks integrity and foreign keys, then archives live config,
plugin settings, server identity, splashscreen and the migration receipt needed
for startup after a full-volume restore, without following symlinks into media.
A checksum receipt is published atomically with each complete snapshot.
NAS-mapped ownership `977:988`, directory mode `0770`, file mode `0660`, and
supplemental group `988` follow the existing private media-backup convention.
These are private NAS copies; encryption at rest is not claimed. The pod has
no service-account token and denies all network ingress/egress; volume traffic
is provided by the node's mounted filesystem. No media files are copied.

## 2026-11-13 stalled replica recovery

The SQLite data volume retained a deleted failed-replica address in its engine,
while a replacement on `k8s-rpi7` held the rebuild slot without becoming writable.
Two healthy writable replicas remained. After active playback ended, Jellyfin
was temporarily paused through Fleet. CSI released both claims and both
Longhorn engines reached stopped with no node assignments. Jellyfin resumes
at one replica. Offline rebuilding was temporarily
disabled in the maintenance-policy bundle to prevent its controller from
holding these attachments. Preserve both PVCs and their replicas; do not clear
finalizers or promote failed copies. Resume one replica after full engine
shutdown, then verify database health, API readiness, and replica rebuilding.
Offline rebuilding is restored to its inventory default after recovery.
