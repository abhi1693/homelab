# Radarr

This bundle installs Radarr through a Fleet `HelmOp` for movie library
automation.

Runs continuously with one replica managed by Git/Fleet. Configuration, queues
and media remain on their existing persistent storage.

## Runtime Shape

- Namespace: `media`
- Chart: TrueCharts `radarr`
- Release: `radarr`
- Internal URL: `http://radarr.media.home`
- Ingress class: `traefik`
- Image: Harbor proxy path for `oci.trueforge.org/containerforge/radarr`

Radarr is ARM64-pinned and uses the shared `heavy-media` topology spread group.

CPU requests are `75m`, with no CPU limit (`resources.limits.cpu: 0` disables
the TrueCharts default). Imports may burst above the request. Resource changes roll the
singleton; deploy through Fleet during a quiet import window.

## Storage

- Config: Longhorn PVC with retained bound volume
- Completed media: existing `media-library-unas` PVC mounted at `/data`
- Downloads: existing `media-downloads-unas` PVC mounted at `/downloads`

Use `/data/movies` as the normal movie root and `/data/anime` as the anime
movie root. Anime movie records remain managed by Radarr, but their files live
in the shared anime directory so Shoko and the Jellyfin Anime library discover
them alongside anime series.

## Network Boundary

Ingress is allowed from Traefik, Jellyseerr, Jellyfin, Prowlarr, and
the qBittorrent smart queue controller on port `7878`. Egress allows DNS,
Prowlarr, the single qBittorrent service, Jellyfin, and external index/API traffic
outside the pod and service CIDRs.

## Operating Notes

- Prowlarr should remain the indexer source of truth.
- Keep `Default` as the automatic request profile. Allow HD and UHD quality
  upgrades through the highest 2160p cutoff so Radarr does not replace existing
  UHD files with lower-resolution 1080p releases. Keep CAM, telesync, SD/DVD,
  raw-HD, BR-DISK, and other low-quality sources disabled for normal automatic
  requests.
- Keep anime movies on the dedicated anime quality profile and `/data/anime`
  root; do not import them into `/data/movies`.
- Keep Radarr download client and API credentials out of Git.
- Change chart configuration in `values.yaml` and let Fleet reconcile.
- For completed movies blocked by identity parsing or custom-format upgrade
  rejection, follow the
  [completed torrent import recovery runbook](../../../../../docs/runbooks/completed-torrent-import-recovery.md).

## Resource sizing

See [kustomization.yaml](kustomization.yaml), [values.yaml](values.yaml) for the configured resources and [the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review) for the historical measurements.

## Replacement safety

Application media-management settings use `/data/movies/.recycle` with 14-day
retention as of 2026-10-28. The directory resides on the existing NAS media
mount and is writable by the app UID. These app settings persist in its
configuration PVC. Verify this setting after restoring application state; a
blank recycle path makes normal upgrade replacements permanent.
