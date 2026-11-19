# Episeerr

Fleet-managed season-ahead automation for the standard Sonarr library.

Runs continuously with one replica managed by Git/Fleet. Configuration, queues
and media remain on their existing persistent storage.

Episeerr is available at
`http://episodes.media.home`. Authentication is
enabled, the username is `asaharan`, and the configured password is stored only
in the encrypted `media-episeerr` SopsSecret.

## Download Policy

The seeded `season_binger` rule is the default:

- `always_have: s1` searches the complete requested starting season for a new
  series;
- `get_type: seasons` with `get_count: 1` keeps the complete current season
  available and searches the next complete season when aggregate playback
  reaches 25 percent of the current season;
- `keep_type: all` never removes downloaded episodes;
- global and environment cleanup dry-run controls remain enabled as a second
  deletion guard.

Jellyseerr's default, non-4K Sonarr server is bootstrapped with
`episeerr_default` and `episeerr_delay`. A dedicated Sonarr delay profile holds
the request before Sonarr can grab every monitored season. Jellyseerr's
otherwise-unused singleton webhook sends manually and automatically approved
requests to Episeerr so the requested starting season is retained. Episeerr
then receives the Sonarr series-add event, changes monitoring to the rule-owned
season, and removes the transient delay tag. Bootstrap refuses to overwrite a
different Jellyseerr webhook destination.

Bootstrap removes references to deleted Sonarr tags from Jellyseerr's request
defaults while preserving valid user tags. This prevents new requests from
inheriting orphan tag IDs after tags are deleted or recreated. The long delay
is intentional; repair an unresolved rule assignment rather than shortening
the delay profile. Existing series retain their own settings until explicitly
repaired through the application API or UI. See the
[download recovery runbook](../../../../../docs/runbooks/media-download-recovery.md).

Fleet rollout does not automatically bulk-migrate existing Sonarr series.
Assign one through the Episeerr UI, or add both `episeerr_default` and
`episeerr_delay` before triggering the Episeerr Sonarr webhook. A one-time
queue migration may instead add the resolved rule tag without firing a search.
For managed series, set Sonarr's new-item policy to `none` and leave seasons
beyond the playback gate unmonitored so RSS cannot grab them first.

## Playback Automation

The custom Jellyfin image includes the official Webhook plugin `21.0.0.0`.
Fleet seeds a generic destination for episode `PlaybackStart` and
`PlaybackStop` events. Episeerr polls Jellyfin every 60 seconds after playback
starts and combines the current episode position with its playback percentage.
For the `asaharan` user, it advances the season rule as soon as aggregate
season progress reaches 25 percent. Jellyfin episode events are fail-closed to
the standard TV media root (`/media/tv`); Anime library items are ignored. The
next season is not searched again once all of its episodes are already monitored.
When the threshold is crossed, Episeerr first monitors the exact selected
episodes and then searches only missing files. Complete missing seasons use
`SeasonSearch`, including the complete next season; partially downloaded
seasons use `EpisodeSearch` for the missing episode IDs. Repeated watch events
do not search episodes already on disk.

The retained 50 percent episode setting is only a compatibility sampling
fallback if Jellyfin-to-Sonarr season-position resolution is unavailable. The
next-season decision still uses the separate 25 percent aggregate-season gate.

## Runtime Shape

- Image: `registry.home/ghcr.io/abhi1693/home-lab-episeerr:4.0.5-1@sha256:3ebfce67d5cb6c99d220b12c89480f5ceeb1d04821ddc9db0cb90835306d0e42`
- Upstream release: `vansmak/episeerr:4.0.5`, pinned by digest in the image
  Dockerfile
- Service: `episeerr.media.svc.cluster.local:5002`
- Config and SQLite state: retained 1Gi Longhorn PVC
- Ephemeral logs, activity payloads, and temp files: bounded `emptyDir` volumes
- Pod user: UID/GID `1000`, read-only root filesystem, dropped capabilities,
  RuntimeDefault seccomp, and no service-account token

The `4.0.5-1` image copies the pinned upstream application onto a pinned
Python 3.15 Alpine runtime with locked Python dependencies. It applies an
assertion-guarded season-progress patch with behavioral tests during the
build. Native ARM64 vulnerability/secret scanning and non-root, read-only
authentication smoke tests must pass before the workflow publishes the tag.
The init and application containers use the same immutable digest. Gunicorn
workers recycle after 2,000 requests plus up to 200 requests of jitter, matching
upstream 4.x. The control socket is disabled for the read-only root filesystem.

## Network Boundary

The separate `media-episeerr-networkpolicy` bundle allows:

- ingress from Traefik, Sonarr, Jellyfin, and Jellyseerr on TCP `5002`;
- egress to Sonarr `8989`, Jellyfin `8096`, Jellyseerr `5055`, DNS, and public
  HTTPS outside cluster pod/service CIDRs.

The matching caller and callee policies are declared in the Sonarr, Jellyfin,
and Jellyseerr bundles.

## Credentials

The SopsSecret stores the generated UI password, Flask session key, and the
Jellyseerr API key copied from the current service. Sonarr and Jellyfin API keys
are referenced from the existing `media-jellyfin-arr-api-keys` Secret and are
not duplicated.

After reconciliation, retrieve the UI password when needed:

```sh
kubectl -n media get secret media-episeerr \
  -o go-template='{{index .data "AUTH_PASSWORD" | base64decode}}{{"\n"}}'
```

## Validation

```sh
kubectl apply --dry-run=server \
  -f kubernetes/projects/entertainment/apps/media-episeerr/
kubectl apply --dry-run=server \
  -f kubernetes/projects/entertainment/apps/media-episeerr-networkpolicy/
```

After Fleet reconciles, verify the image is available, the config-seeding init
container completed, the startup log reports `Episeerr integrations configured`,
the Jellyfin Webhook plugin is active, and a test request carries both transient
Episeerr tags before using the policy for existing series.

## Resource sizing

See [deployment.yaml](deployment.yaml), [pvc.yaml](pvc.yaml) for the configured resources and [the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review) for the historical measurements.

## 2026-11-12 attachment recovery

Episeerr's pod was blocked before initialization: CSI requested the config
volume on `k8s-rpi5` while its engine still ran on `k8s-rpi9`. Longhorn reported
`engine is on node k8s-rpi9 vs volume on , must detach first`. Two replicas
remained writable; the third was failed. No application pod had mounted the
volume. A private full-volume recovery copy was taken before reconciliation.

Fleet paused the deployment at zero replicas. CSI released its old attachment
and Longhorn stopped the stale engine without deleting storage objects or
clearing finalizers. Longhorn then attached the volume on `k8s-rpi5` with two
writable replicas and scheduled a replacement third replica on `k8s-rpi7`.
That rebuild initially queued behind Jellyfin under the one-rebuild-per-node
policy. Episeerr resumes at one replica using the two writable copies and the
verified recovery backup; this does not claim full storage redundancy.

For a recurrence, pause the single client through Fleet, verify CSI releases
its ticket and the stale engine stops, and allow Longhorn to reconcile its
attachment before resuming. Inspect attachment tickets for Longhorn's offline
rebuild controller as well as CSI: an offline rebuild can legitimately reattach
the volume after application detachment. Never promote a failed replica or
remove a storage finalizer to bypass this sequence. Verify the existing PVC
and database, application readiness, login protection, integrations, and the
three-replica storage target separately after resuming.

The first resumed pod scheduled on `k8s-rpi4`, but the offline-rebuild ticket
continued to own the attachment on `k8s-rpi5` while its third replica waited
for the rebuild slot on `k8s-rpi7`. A temporary Fleet hostname selector restored
service on `k8s-rpi5`; CSI then owned the attachment and the offline-rebuild
ticket was removed. The temporary selector was removed on 2026-11-13 at the
operator's request. Scheduling is again ARM64-only without a hostname pin.
Storage redundancy and rebuild completion remain separate acceptance gates;
do not infer three healthy replicas from application readiness.
