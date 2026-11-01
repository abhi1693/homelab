# Radarr

This bundle installs Radarr through a Fleet `HelmOp` for movie library
automation.

The [acquisition schedule](../media-acquisition-schedule/README.md) runs one
replica from 22:00–10:00 Asia/Kolkata (IST), on nights starting Monday–Friday;
Friday night continues until Saturday at 10:00. Git keeps a paused baseline of
zero replicas, and the schedule owns only the runtime replica field. Outside
the window the pod stops while queues, configuration PVCs, and media remain
retained. FlareSolverr stays online because DevFeed uses it.

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

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `media/radarr/radarr` | 100m → 50m | 545Mi → 512Mi | 976Mi → 1024Mi |

## Replacement safety

Application media-management settings use `/data/movies/.recycle` with 14-day
retention as of 2026-10-28. The directory resides on the existing NAS media
mount and is writable by the app UID. These app settings persist in its
configuration PVC. Verify this setting after restoring application state; a
blank recycle path makes normal upgrade replacements permanent.
