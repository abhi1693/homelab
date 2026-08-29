# Jellyseerr

This bundle installs the media request portal through a Fleet `HelmOp`.

## Runtime Shape

- Namespace: `media`
- Chart: Seerr `seerr-chart`
- Release: `jellyseerr`
- Internal URL: `http://requests.media.home`
- Ingress class: `traefik`
- Image: Harbor proxy path for `ghcr.io/seerr-team/seerr:v3.4.1`
- Service: ClusterIP on port `10241`

The workload runs as a non-root user with a retained config PVC.

## Storage

`jellyseerr-config` is a 128Mi Longhorn RWO PVC with a retained bound volume.
The chart is configured to use this existing claim for application state.

## Network Boundary

The network policy is managed in the separate
`media-jellyseerr-networkpolicy` bundle. It allows ingress from Traefik,
Jellyfin, Episeerr, and the Home Assistant request bridge, and egress to DNS,
Jellyfin, Sonarr, Radarr, Ryokan, Episeerr, and external
metadata/API traffic outside the pod and service CIDRs.

## Operating Notes

- Keep Jellyfin, Sonarr, Radarr, and Ryokan API credentials out of Git.
- Seerr's administrator API key is copied into Home Assistant's encrypted
  SopsSecret for the request bridge. Rotate both in one GitOps change.
- Episeerr's bootstrap also stores that key in its encrypted SopsSecret and
  idempotently adds `episeerr_default` plus `episeerr_delay` to the default
  non-4K Sonarr server. It configures Jellyseerr's otherwise-unused singleton
  webhook for approved TV requests and refuses to replace a different webhook
  destination. Include the key copy in API-key rotations.
- Review the separate network-policy bundle when adding integrations.
- Change chart configuration in `values.yaml` and let Fleet reconcile.
