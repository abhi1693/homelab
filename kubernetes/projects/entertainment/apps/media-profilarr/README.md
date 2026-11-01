# Profilarr

Profilarr manages Radarr and Sonarr quality profiles, custom formats, and media
management settings from PCD sources such as Dictionarry and TRaSH Guides.

The [acquisition schedule](../media-acquisition-schedule/README.md) runs one
replica from 22:00–10:00 Asia/Kolkata (IST), on nights starting Monday–Friday;
Friday night continues until Saturday at 10:00. Git keeps a paused baseline of
zero replicas, and the schedule owns only the runtime replica field. Outside
the window the pod stops while queued work and configuration PVCs remain
retained. FlareSolverr stays online because DevFeed uses it.

## Runtime

- Image: `registry.home/ghcr.io/dictionarry-hub/profilarr`, pinned in `deployment.yaml`
- URL: `http://profilarr.media.home`
- Namespace: `media`
- Config PVC: `profilarr-config`
- Health endpoint: `/api/v1/health`

The parser sidecar is intentionally omitted. Upstream documents it as required
only for custom format and quality profile testing; linking and syncing profiles
to Arr instances work without it.

## Initial Setup

The app starts with `AUTH=on`. During an acquisition window after the first
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

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `media/profilarr/profilarr` | 50m → 10m | 256Mi → 448Mi | 1Gi → 1Gi |
