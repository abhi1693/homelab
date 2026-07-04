# Sonarr

This bundle installs Sonarr through a Fleet `HelmOp` for TV library automation.

## Runtime Shape

- Namespace: `media`
- Chart: TrueCharts `sonarr`
- Release: `sonarr`
- Internal URL: `http://sonarr.media.home`
- Ingress class: `traefik`
- Image: Harbor proxy path for `oci.trueforge.org/containerforge/sonarr`

Sonarr is ARM64-pinned and participates in the `heavy-media` topology spread
group so large media workloads avoid piling onto one node.

## Storage

- Config: Longhorn PVC with retained bound volume
- Completed media: existing `media-library-nas` PVC mounted at `/data`
- Downloads: existing `media-downloads` PVC mounted at `/downloads`

Keep downloads and completed library paths separate so importers never expose
partial downloads as completed media.

## Network Boundary

Ingress is allowed from Traefik, Jellyseerr, Jellyfin, Profilarr, Prowlarr, and
the qBittorrent smart queue controller on port `8989`. Egress allows DNS,
Prowlarr, qBittorrent, Jellyfin, and external index/API traffic outside the pod
and service CIDRs.

## Operating Notes

- Prowlarr should remain the indexer source of truth.
- Keep application API keys out of Git.
- Change chart configuration in `values.yaml` and let Fleet reconcile.
