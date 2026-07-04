# Prowlarr

This bundle installs Prowlarr through a Fleet `HelmOp` for media indexer
management.

## Runtime Shape

- Namespace: `media`
- Chart: TrueCharts `prowlarr`
- Release: `prowlarr`
- Internal URL: `http://prowlarr.media.home`
- Ingress class: `traefik`
- Image: Harbor proxy path for `oci.trueforge.org/containerforge/prowlarr`

Fleet orders Prowlarr after FlareSolverr because indexer configuration can use
the FlareSolverr service for browser-challenge handling.

## Storage

Prowlarr uses a retained Longhorn config PVC. It does not mount the shared media
library or downloads PVCs.

## Network Boundary

Ingress is allowed from Traefik, Sonarr, Radarr, and Ryokan on port `9696`.
Egress allows DNS, FlareSolverr on port `8191`, Sonarr, Radarr, qBittorrent,
and external index/API traffic outside the pod and service CIDRs.

## Operating Notes

- Keep indexer credentials and app API keys out of Git.
- Use Prowlarr as the normal source of truth for Sonarr and Radarr indexers.
- Change chart configuration in `values.yaml` and let Fleet reconcile.
