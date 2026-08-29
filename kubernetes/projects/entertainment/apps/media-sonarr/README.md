# Sonarr

This bundle installs Sonarr through a Fleet `HelmOp` for TV library automation.

## Operational state

Sonarr is intentionally stopped with zero replicas while the qBittorrent
download stack is disabled. Its retained config and media PVCs are unchanged.
Restore it to one replica together with qBittorrent and the other download
automation workloads.

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
- Completed media: existing `media-library-unas` PVC mounted at `/data`
- Downloads: existing `media-downloads-unas` PVC mounted at `/downloads`

Keep downloads and completed library paths separate so importers never expose
partial downloads as completed media.
The config PVC carries Sonarr's database, logs, backups, and media cover cache;
keep enough free space for startup write checks and routine metadata growth.

## Network Boundary

Ingress is allowed from Traefik, Jellyseerr, Jellyfin, Episeerr, Prowlarr, and
the qBittorrent smart queue controller on port `8989`. Egress allows DNS,
Prowlarr, qBittorrent, Jellyfin, Episeerr webhooks, and external index/API
traffic outside the pod and service CIDRs.

## Operating Notes

- Prowlarr should remain the indexer source of truth.
- Keep `Default` as the automatic request profile. Allow HD and UHD quality
  upgrades through the highest 2160p cutoff so Sonarr does not replace existing
  UHD files with lower-resolution 1080p releases. Keep CAM, telesync, SD/DVD,
  raw-HD, and other low-quality sources disabled for normal automatic requests.
- Keep application API keys out of Git.
- Episeerr owns the `episeerr_default`, `episeerr_delay`, and
  `episeerr_select` tags plus its dedicated delay profile and webhook. Do not
  add unrelated tags to that profile.
- Change chart configuration in `values.yaml` and let Fleet reconcile.
- For completed packs where only the title-encoded episode imported, follow the
  [completed torrent import recovery runbook](../../../../../docs/runbooks/completed-torrent-import-recovery.md)
  and map every remaining file to one exact episode.
