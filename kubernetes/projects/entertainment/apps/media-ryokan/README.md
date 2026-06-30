# Ryokan

Ryokan replaces the old Sonarr Anime instance as the anime-only PVR.

The web UI is available at `http://ryokan.media.home`.

## First-run setup

1. Open `http://ryokan.media.home` and create the admin account.
2. In Settings -> Download Clients, add qBittorrent:
   - URL: `http://qbittorrent-anime.media.svc.cluster.local:8080`
   - Category: `anime`
   - Download path as Ryokan sees it: `/downloads`
3. In Settings -> General, set the media root to `/media/anime`, enable
   post-processing, and set the file operation mode to `Move` so completed
   anime is copied to the NAS-backed library and removed from downloads.
4. In Settings -> Indexers, add the anime Prowlarr Torznab feeds. The live
   cluster uses `Bangumi Moe`, `Nyaa.si`, `SubsPlease`, `Shana Project`,
   `Tokyo Toshokan`, and `AnimeTosho`.
5. In Settings -> Integrations, configure Jellyfin:
   - URL: `http://jellyfin.media.svc.cluster.local:8096`
   - API key: use an active Jellyfin API key from the Jellyfin database/UI.
   Ryokan uses this for Jellyfin server checks, targeted lookups, and library
   refreshes after imports.
6. In Settings -> Connections, enable the Seerr API shims:
   - Sonarr API Compatibility uses the existing `SONARR_ANIME_API_KEY` from
     `arr-api-keys`; Seerr should point its anime Sonarr entry at
     `http://ryokan.media.svc.cluster.local:8978`.
   - Radarr API Compatibility uses the existing `RADARR_API_KEY` from
     `arr-api-keys`; Seerr should point its anime-movie Radarr entry at
     `http://ryokan.media.svc.cluster.local:8978` with URL Base `/radarr`.

Ryokan mounts `/downloads` so it can read qBittorrent's reported anime torrent
paths, and `/media/anime` as the NAS-backed anime library.
