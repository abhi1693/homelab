# Shoko

Shoko is the anime-only metadata and library manager for this stack.

The deployment runs as a single replica with persistent configuration and
library mounts.

It retains two ReplicaSet revisions; Git and Fleet history remain the primary
rollback path.

The `media-anime` recommendation profile observes CPU and memory usage every
five minutes and retains learning history for right-sizing. Resource and
replica changes remain disabled while initial library scans establish the
normal idle and scan baseline.

The server runs at `http://anime.media.home` and listens in-cluster at
`http://shoko.media.svc.cluster.local:8111`.

## GitHub API access

Shoko uses the GitHub API to check the latest compatible server and WebUI
versions. The `shoko-github` SopsSecret provides `GITHUB_TOKEN` to avoid the
low unauthenticated API limit surfacing as `WebUI/LatestVersion` and
`WebUI/LatestServerVersion` errors. Keep the token encrypted in
`secrets.sops.yaml`; its `data` value must remain base64-encoded before SOPS
encryption. Never store the token in the ConfigMap or Deployment.

## Storage

- Config and Shoko database: `shoko-config` mounted at `/home/shoko/.shoko`
- Anime library: `media-library-unas` subPath `anime` mounted read-only at
  `/media/anime`
- Legacy compatibility mount: `/mnt/anime`

Shoko should be configured to import or scan `/media/anime` so the path matches
Jellyfin's Anime library path for Shokofin. The mount is
read-only so Shoko cannot move or rewrite the NAS library; change that only if
you intentionally want Shoko to manage files directly.

Before Shoko starts, an idempotent init container ensures the `.recycle`
directory is present in `Import.Exclude`. This keeps both folder scans and the
live file watcher from scheduling files held there while preserving the other
settings on the configuration volume.

## Jellyfin

Install the Shokofin Jellyfin plugin, point it at
`http://shoko.media.svc.cluster.local:8111`, and use it only for the Jellyfin
Anime library. Normal TV stays in Sonarr; anime TV requests and downloads are
handled by Ryokan.

For Jellyfin 10.11, add the `Shokofin Stable` plugin repository:

`https://raw.githubusercontent.com/ShokoAnime/Shokofin/metadata/stable/manifest.json`

Shoko does not replace a downloader. Ryokan downloads anime TV into the NAS
anime folder, then Shoko/Shokofin handles the Jellyfin metadata layer.

For moving anime that was stored under the Movies or TV roots, rescanning the
anime folder, and repairing AniDB hash misses, follow the
[anime library relocation and Shoko recovery runbook](../../../../../docs/runbooks/storage/anime-library-relocation-and-shoko-recovery.md).
