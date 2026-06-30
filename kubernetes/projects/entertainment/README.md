# Entertainment Project

Fleet tracks Entertainment workloads from `kubernetes/projects/entertainment/apps/*`
with the `home-lab-entertainment` GitRepo.

The Rancher project object is tracked separately from
`kubernetes/projects/entertainment/_project` by `home-lab-rancher-projects`.
Project metadata uses non-forcing drift correction because Rancher `Project`
objects include immutable fields.

## Bundles

| Path | Bundle | Type | Notes |
|------|--------|------|-------|
| `apps/media-helm-repositories` | `media-helm-repositories` | GitOps | Registers Rancher chart repositories used by the media stack. |
| `apps/media-storage` | `media-storage` | GitOps | Owns the media namespace, shared NAS PV/PVC, downloads PVC, and storage helper resources. |
| `apps/media-metube` | `media-metube` | GitOps | Browser UI for yt-dlp downloads into the Jellyfin YouTube library. |
| `apps/media-*` | `media-*` / app name | GitOps/HelmOps | Media stack applications and their app-specific network policy bundles. |

Chart-based media apps use Fleet HelmOps. The GitOps wrapper bundle keeps a
`-helmop` suffix, such as `jellyfin-helmop`, and creates a child HelmOps bundle
named for the app, such as `jellyfin`. Helm releases and workloads keep the same
upstream service names, such as `jellyfin`, `sonarr`, and `radarr`.

## Reconcile Order

`rancher-project-entertainment`, `media-helm-repositories`, and
`media-storage` must be ready before the other media stack bundles. Application
dependencies are encoded in each app's `fleet.yaml`.

## Operating Model

Make desired-state changes in Git and let Fleet reconcile them. Direct cluster
changes should be limited to resources Fleet cannot own, such as manually
provisioned secrets, retained PV claim metadata, or ownership metadata needed
for Fleet adoption.
