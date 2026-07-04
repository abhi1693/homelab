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
- Completed media: existing `media-library-nas` PVC mounted at `/data`
- Downloads: existing `media-downloads` PVC mounted at `/downloads`

## Network Boundary

Ingress is allowed from Traefik, Jellyseerr, Jellyfin, Profilarr, Prowlarr, and
the qBittorrent smart queue controller on port `7878`. Egress allows DNS,
Prowlarr, qBittorrent movie clients, Jellyfin, and external index/API traffic
outside the pod and service CIDRs.

## Operating Notes

- Prowlarr should remain the indexer source of truth.
- Keep Radarr download client and API credentials out of Git.
- Change chart configuration in `values.yaml` and let Fleet reconcile.
