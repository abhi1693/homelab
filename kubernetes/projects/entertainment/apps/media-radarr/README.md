# Radarr

This bundle installs Radarr through a Fleet `HelmOp` for movie library
automation.

## Operational state

Radarr is intentionally stopped with zero replicas while the qBittorrent
download stack is disabled. Its retained config and media PVCs are unchanged.
Restore it to one replica together with qBittorrent and the other download
automation workloads.

## Runtime Shape

- Namespace: `media`
- Chart: TrueCharts `radarr`
- Release: `radarr`
- Internal URL: `http://radarr.media.home`
- Ingress class: `traefik`
- Image: Harbor proxy path for `oci.trueforge.org/containerforge/radarr`

Radarr is ARM64-pinned and uses the shared `heavy-media` topology spread group.

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
