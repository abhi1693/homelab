# Jellyseerr

This bundle installs the media request portal through a Fleet `HelmOp`.

## Runtime Shape

- Namespace: `media`
- Chart: Seerr `seerr-chart`
- Release: `jellyseerr`
- Internal URL: `http://requests.media.home`
- Ingress class: `traefik`
- Image: Harbor proxy path for `ghcr.io/seerr-team/seerr`, pinned in `values.yaml`
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

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `media/jellyseerr/jellyseerr` | 50m → 25m | 369Mi → 320Mi | 432Mi → 432Mi |
