# Radarr

This bundle installs Radarr through a Fleet `HelmOp` for movie library
automation.

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
- Completed media: existing `media-library-nfs-csi` PVC mounted at `/data`
- Downloads: existing `media-downloads-nfs-csi` PVC mounted at `/downloads`

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
- Keep anime movies on the dedicated anime quality profile and `/data/anime`
  root; do not import them into `/data/movies`.
- Keep Radarr download client and API credentials out of Git.
- Change chart configuration in `values.yaml` and let Fleet reconcile.
