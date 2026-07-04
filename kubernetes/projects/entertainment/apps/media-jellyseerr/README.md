# Jellyseerr

This bundle installs the media request portal through a Fleet `HelmOp`.

## Runtime Shape

- Namespace: `media`
- Chart: Seerr `seerr-chart`
- Release: `jellyseerr`
- Internal URL: `http://requests.media.home`
- Ingress class: `traefik`
- Image: Harbor proxy path for `docker.io/seerr/seerr`
- Service: ClusterIP on port `10241`

The workload runs as a non-root user with a retained config PVC.

## Storage

`jellyseerr-config` is a 128Mi Longhorn RWO PVC with a retained bound volume.
The chart is configured to use this existing claim for application state.

## Network Boundary

The network policy is managed in the separate
`media-jellyseerr-networkpolicy` bundle. It allows ingress from Traefik and
Jellyfin, and egress to DNS, Jellyfin, Sonarr, Radarr, Ryokan, and external
metadata/API traffic outside the pod and service CIDRs.

## Operating Notes

- Keep Jellyfin, Sonarr, Radarr, and Ryokan API credentials out of Git.
- Review the separate network-policy bundle when adding integrations.
- Change chart configuration in `values.yaml` and let Fleet reconcile.
