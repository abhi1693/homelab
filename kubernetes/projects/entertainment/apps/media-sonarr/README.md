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

- Config: 1Gi Longhorn PVC with retained bound volume
- Completed media: existing `media-library-nfs-csi` PVC mounted at `/data`
- Downloads: existing `media-downloads-nfs-csi` PVC mounted at `/downloads`

Keep downloads and completed library paths separate so importers never expose
partial downloads as completed media.
The config PVC carries Sonarr's database, logs, backups, and media cover cache;
keep enough free space for startup write checks and routine metadata growth.

## Network Boundary

Ingress is allowed from Traefik, Jellyseerr, Jellyfin, Prowlarr, and
the qBittorrent smart queue controller on port `8989`. Egress allows DNS,
Prowlarr, qBittorrent, Jellyfin, and external index/API traffic outside the pod
and service CIDRs.

## Operating Notes

- Prowlarr should remain the indexer source of truth.
- Keep `[TV] WEB-1080p` as the default automatic request profile, allow quality
  upgrades through `Bluray-1080p`, and leave every quality above 1080p
  disabled in that profile. Retain separate 2160p profiles only for explicit
  manual selection; do not assign them to the default Seerr request mapping.
- Keep application API keys out of Git.
- Change chart configuration in `values.yaml` and let Fleet reconcile.
