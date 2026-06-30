# Media Helm Repositories

This bundle registers Rancher `ClusterRepo` resources used only by the
Entertainment media stack.

It owns:

- `oci://ghcr.io/seerr-team/seerr/seerr-chart`
- `oci://oci.trueforge.org/truecharts/flaresolverr`
- `oci://oci.trueforge.org/truecharts/jellyfin`
- `oci://oci.trueforge.org/truecharts/prowlarr`
- `oci://oci.trueforge.org/truecharts/qbittorrent`
- `oci://oci.trueforge.org/truecharts/radarr`
- `oci://oci.trueforge.org/truecharts/sonarr`

Shared chart repositories live in their owning project-specific
`*-helm-repositories` bundles.
