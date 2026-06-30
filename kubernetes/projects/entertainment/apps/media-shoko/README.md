# Shoko

Shoko is the anime-only metadata and library manager for this stack.

The server runs at `http://anime.media.home` and listens in-cluster at
`http://shoko.media.svc.cluster.local:8111`.

## Storage

- Config and Shoko database: `shoko-config` mounted at `/home/shoko/.shoko`
- Anime library: `media-library-nas` subPath `anime` mounted read-only at
  `/media/anime`
- Legacy compatibility mount: `/mnt/anime`

Shoko should be configured to import or scan `/media/anime` so the path matches
Jellyfin's Anime library path for Shokofin. The mount is
read-only so Shoko cannot move or rewrite the NAS library; change that only if
you intentionally want Shoko to manage files directly.

## Jellyfin

Install the Shokofin Jellyfin plugin, point it at
`http://shoko.media.svc.cluster.local:8111`, and use it only for the Jellyfin
Anime library. Normal TV stays in Sonarr; anime TV requests and downloads are
handled by Ryokan.

For Jellyfin 10.11, add the `Shokofin Stable` plugin repository:

`https://raw.githubusercontent.com/ShokoAnime/Shokofin/metadata/stable/manifest.json`

Shoko does not replace a downloader. Ryokan downloads anime TV into the NAS
anime folder, then Shoko/Shokofin handles the Jellyfin metadata layer.
