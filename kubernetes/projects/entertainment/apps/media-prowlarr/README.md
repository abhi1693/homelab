# Prowlarr

This bundle installs Prowlarr through a Fleet `HelmOp` for media indexer
management.

## Runtime Shape

- Namespace: `media`
- Chart: TrueCharts `prowlarr`
- Release: `prowlarr`
- Internal URL: `http://prowlarr.media.home`
- Ingress class: `traefik`
- Image: Harbor proxy path for `oci.trueforge.org/containerforge/prowlarr:2.6.2`

Fleet orders Prowlarr after FlareSolverr because indexer configuration can use
the FlareSolverr service for browser-challenge handling.

## Storage

Prowlarr uses a retained Longhorn config PVC. It does not mount the shared media
library or downloads PVCs.

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
- Use Prowlarr as the normal source of truth for Sonarr and Radarr indexers.
- Ryokan replaces the former Sonarr Anime instance. Do not retain a Prowlarr
  application targeting `sonarr-anime.media.svc.cluster.local`; Ryokan manages
  its anime indexers directly.
- Change chart configuration in `values.yaml` and let Fleet reconcile.
