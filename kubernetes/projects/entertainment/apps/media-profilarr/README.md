# Profilarr

Profilarr manages Radarr and Sonarr quality profiles, custom formats, and media
management settings from PCD sources such as Dictionarry and TRaSH Guides.

Runs continuously with one replica managed by Git/Fleet. Configuration, queues
and media remain on their existing persistent storage.

## Runtime

- Image: `registry.home/ghcr.io/dictionarry-hub/profilarr`, pinned in `deployment.yaml`
- URL: `http://profilarr.media.home`
- Namespace: `media`
- Config PVC: `profilarr-config`
- Health endpoint: `/api/v1/health`

The parser sidecar is intentionally omitted. Upstream documents it as required
only for custom format and quality profile testing; linking and syncing profiles
to Arr instances work without it.

## Upgrade to 2.3.1

The 2.3 release changes authentication and migrates the application database.
Retain a full application backup and a consistent online SQLite snapshot before
the rollout. An isolated restored-copy rehearsal of 2.3.1 migrated this instance
from schema 70 to 76, passed SQLite integrity checks and HTTP health checks, and
retained existing users, Arr connections, profile settings and database edits.
Existing API-key hashes migrate to full-access default keys. Production remains
on `AUTH=on`; the removed local-authentication bypass is not used.

After Fleet applies the pinned ARM64 image, check the health endpoint, login
protection and both Arr connections. If a migration must be rolled back, restore
the pre-upgrade database and matching data directory before starting the old
image; changing the image alone does not reverse the schema migration.

## Initial Setup

The app starts with `AUTH=on`. After the first
GitOps deployment, open
`http://profilarr.media.home`, create the local admin account, and link:

- Dictionarry: `https://github.com/Dictionarry-Hub/database`
- TRaSH Guides PCD: `https://github.com/Dictionarry-Hub/trash-pcd`
- Radarr URL: `http://radarr:7878`
- Radarr external URL: `http://radarr.media.home`
- Sonarr URL: `http://sonarr:8989`
- Sonarr external URL: `http://sonarr.media.home`

Use the TRaSH Guides database for quality-definition configs:

- Radarr: `Movie`
- Sonarr: `Series`

## Resource sizing

See [deployment.yaml](deployment.yaml), [pvc.yaml](pvc.yaml) for the configured resources and [the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review) for the historical measurements.
