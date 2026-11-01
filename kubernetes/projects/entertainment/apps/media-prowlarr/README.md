# Prowlarr

This bundle installs Prowlarr through a Fleet `HelmOp` for media indexer
management.

The [acquisition schedule](../media-acquisition-schedule/README.md) runs one
replica from 22:00–10:00 Asia/Kolkata (IST), on nights starting Monday–Friday;
Friday night continues until Saturday at 10:00. Git keeps a paused baseline of
zero replicas, and the schedule owns only the runtime replica field. Outside
the window the pod stops while queued work and configuration PVCs remain
retained. FlareSolverr stays online because DevFeed uses it.

## Runtime Shape

- Namespace: `media`
- Chart: TrueCharts `prowlarr`
- Release: `prowlarr`
- Internal URL: `http://prowlarr.media.home`
- Ingress class: `traefik`
- Image: Harbor proxy path for `oci.trueforge.org/containerforge/prowlarr`, pinned in `values.yaml`

Fleet orders Prowlarr after FlareSolverr because indexer configuration can use
the FlareSolverr service for browser-challenge handling.

CPU requests are `170m`, with no CPU limit (`resources.limits.cpu: 0` disables
the TrueCharts default). Indexer work may burst above the request.
Resource changes roll the singleton; deploy through Fleet in a quiet window.

## Storage

Prowlarr uses a retained 512 MiB Longhorn config PVC. The manifest preserves the
bound volume ID so Fleet expands the existing claim instead of attempting to
replace it. Prowlarr does not mount the shared media library or downloads PVCs.

## Network Boundary

Ingress is allowed from Traefik, Sonarr, Radarr, Ryokan, and qBittorrent on port
`9696`. The qBittorrent path is required because submitted download URLs point
back to Prowlarr. Egress allows DNS, FlareSolverr on port `8191`, Sonarr,
Radarr, qBittorrent, and external index/API traffic outside the pod and service
CIDRs.

## Operating Notes

- Keep indexer credentials and app API keys out of Git.
- Prowlarr reads its API key from the encrypted
  `media-jellyfin-arr-api-keys` Secret. Rotate that value and bump
  `home-lab.io/api-key-revision` in `values.yaml`; Fleet restarts Prowlarr and
  the Ryokan startup reconciler updates its configured endpoints.
- After rotating Arr credentials, update Prowlarr's Sonarr/Radarr application
  connections and force a full application/indexer sync. A normal sync can
  complete without repairing stale credentials. Verify actual searches and
  download handoff using the
  [download recovery runbook](../../../../../docs/runbooks/media-download-recovery.md).
- Use Prowlarr as the normal source of truth for Sonarr and Radarr indexers.
- Indexers that need the configured FlareSolverr proxy must carry its
  `flaresolverr` tag. Uindex was tested successfully and tagged on 2026-10-28
  after direct requests were blocked by Cloudflare; retain its Sonarr/Radarr
  synchronization tags. This application setting persists in its config PVC.
- Ryokan manages anime indexers directly; do not configure a separate Sonarr
  Anime application in Prowlarr.
- Change chart configuration in `values.yaml` and let Fleet reconcile.

## CPU reservation

CPU request is 100m; indexer work retains its uncapped CPU burst policy.
