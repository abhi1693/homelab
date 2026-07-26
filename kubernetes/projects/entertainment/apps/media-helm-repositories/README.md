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

The `seerr-team` repository keeps the most recent `spec.forceUpdate` timestamp
in Git. It was last advanced after an ISP outage left Rancher's OCI download
condition stuck on a transient CoreDNS failure even after external DNS
recovered. Advance that timestamp only to retry a failed repository download
after connectivity has been restored.

Shared chart repositories live in their owning project-specific
`*-helm-repositories` bundles.
