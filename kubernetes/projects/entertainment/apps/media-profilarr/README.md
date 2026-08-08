# Profilarr

Profilarr manages Radarr and Sonarr quality profiles, custom formats, and media
management settings from PCD sources such as Dictionarry and TRaSH Guides.

## Runtime

- Image: `registry.home/ghcr.io/dictionarry-hub/profilarr:2.0.9`
- URL: `http://profilarr.media.home`
- Namespace: `media`
- Config PVC: `profilarr-config`
- Health endpoint: `/api/v1/health`

The parser sidecar is intentionally omitted. Upstream documents it as required
only for custom format and quality profile testing; linking and syncing profiles
to Arr instances work without it.

## Initial Setup

The app starts with `AUTH=on`. After the first GitOps deployment, open
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

The one-time profile resync performed on 2026-08-05 used a temporary Profilarr
instance and did not persist its API keys or GitHub token into GitOps.
