# Profilarr

Profilarr manages Radarr and Sonarr quality profiles and custom formats from
the Dictionarry database.

## Access

- `http://profilarr.media.home`
- Internal service: `http://profilarr.media.svc.cluster.local:6868`

## Initial Setup

Connect the existing Servarr instances with their in-cluster URLs:

- Radarr: `http://radarr.media.svc.cluster.local:7878`
- Sonarr: `http://sonarr.media.svc.cluster.local:8989`

After first start, open `Settings > Onboarding` in Profilarr to link the
Dictionarry database, add the Arr instances, and configure sync.

Use Dictionarry v2 as the source for movie and TV quality profiles, custom
formats, delay profiles, media-management naming, quality definitions, and
miscellaneous media-management settings instead of manually recreating guide
profiles in each Arr app.

The bundled parser sidecar is enabled for custom format and quality profile
testing. Normal database linking, config syncing, and upgrades can run without
the parser, but keeping it available makes Profilarr's test tooling usable.

Profilarr is the only declared profile/custom-format manager for Radarr and
Sonarr in this repo. Do not add a separate guide-sync service for the same
scope.
