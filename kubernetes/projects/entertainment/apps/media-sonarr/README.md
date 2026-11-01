# Sonarr

This bundle installs Sonarr through a Fleet `HelmOp` for TV library automation.

The [acquisition schedule](../media-acquisition-schedule/README.md) runs one
replica from 22:00–10:00 Asia/Kolkata (IST), on nights starting Monday–Friday;
Friday night continues until Saturday at 10:00. Git keeps a paused baseline of
zero replicas, and the schedule owns only the runtime replica field. Outside
the window the pod stops while queues, configuration PVCs, and media remain
retained. FlareSolverr stays online because DevFeed uses it.

## Runtime Shape

- Namespace: `media`
- Chart: TrueCharts `sonarr`
- Release: `sonarr`
- Internal URL: `http://sonarr.media.home`
- Ingress class: `traefik`
- Image: Harbor proxy path for `oci.trueforge.org/containerforge/sonarr`

Sonarr is ARM64-pinned and participates in the `heavy-media` topology spread
group so large media workloads avoid piling onto one node.

CPU requests are `500m`, with no CPU limit (`resources.limits.cpu: 0` disables
the TrueCharts default). Imports may burst above the request. CPU and memory
requests are operator-managed through Git/Fleet. Review worker reservations and
heavy-media placement before changing them. This singleton rolls on resource changes;
let Fleet reconcile during a quiet import window.

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

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `media/sonarr/sonarr` | 500m → 625m | 494Mi → 640Mi | 864Mi → 864Mi |

## Replacement safety

Application media-management settings use `/data/tv/.recycle` with 14-day
retention as of 2026-10-28. The directory resides on the existing NAS media
mount and is writable by the app UID. These app settings persist in its
configuration PVC. Verify this setting after restoring application state; a
blank recycle path makes normal upgrade replacements permanent.
