# Media Stack

This stack runs a Rancher/Fleet-managed media automation pipeline using
TrueCharts OCI Helm charts, the official Seerr OCI Helm chart, and raw
Kubernetes manifests for custom services.

## Architecture

- `qBittorrent`: torrent download client.
- `Prowlarr`: torrent indexer manager for Sonarr and Radarr.
- `Sonarr`: TV management.
- `Ryokan`: anime TV request and download management.
- `Radarr`: movie management.
- `Shoko`: anime metadata and library management for Jellyfin/Shokofin.
- `Jellyfin`: video, anime, and live TV media server.
- `MeTube`: browser UI for yt-dlp downloads into Jellyfin's YouTube library.
- `Seerr`: Jellyfin request portal. The Kubernetes release and internal Service
  name remain `jellyseerr` for compatibility, but the workload runs the official
  Seerr chart/image.

All app releases run in the `media` namespace, which is assigned to the Rancher
`Entertainment` project.

The completed media library is stored on the NAS NFS export
`nas.home:/nfs/media`. The storage bundle binds that export to the
`media/media-library-nas` PVC with a requested capacity of `1Ti`.

Sonarr and Radarr mount the completed-media PVC at `/data`. Jellyfin mounts the
same PVC at `/media`, while keeping its own application data under its
chart-managed `/data` PVC.

The previous Longhorn `media-library` PVC and standalone Longhorn volume are no
longer declared. Do not recreate `media-library`; the NAS-backed
`media-library-nas` PVC is the completed-media library.

Downloads are intentionally separated from the completed Jellyfin library.
The qBittorrent clients, Sonarr, Ryokan, and Radarr mount the
`media-downloads` Longhorn PVC; Jellyfin does not mount it. The qBittorrent
clients write incomplete and completed torrent payloads to `/downloads`, then
Sonarr/Radarr import finished TV and movies into `/data/tv` or `/data/movies`.
Ryokan mounts `/downloads` because qBittorrent reports anime torrent paths relative to that
root, but it only processes torrents from the anime qBittorrent client using
the `anime` category. Ryokan imports anime into `/media/anime`, which is the
NAS anime subfolder. Shoko and Jellyfin both scan the NAS anime library
read-only at `/media/anime`. This keeps Jellyfin from scanning partial
downloads and preserves the completed-media PVC as the final library only.

The qBittorrent clients stop torrents immediately after completion by using a
zero ratio and zero seeding-time limit. Sonarr and Radarr have
completed-download removal enabled, so after they successfully import a
completed item to the NAS-backed library, they remove the stopped torrent and
its payload from `/downloads`. Ryokan owns anime post-processing from the anime
qBittorrent client and uses move mode so completed anime lands in the
NAS-backed `/media/anime` library and is removed from `/downloads` after
import.

The storage bundle's keeper pod prepares the shared download category
directories (`/downloads/tv`, `/downloads/movies`, `/downloads/anime`,
`/downloads/prowlarr`, and matching `/downloads/temp/*` paths) with the media
apps' UID/GID so qBittorrent category paths and Sonarr/Radarr remote-path
health checks stay aligned.

The `media-downloads` PVC opts into Longhorn's `weekly-filesystem-trim`
RecurringJob. The job is declared in the system project and runs filesystem trim
against attached Longhorn volumes that carry the matching recurring-job label,
allowing Longhorn to reclaim blocks freed by torrent imports and cleanup.

The qBittorrent clients also auto-add the `ngosang/trackerslist`
`trackers_all.txt` public tracker fallback list to new downloads. This can help
weak public magnets discover peers for metadata, but it does not revive a dead
release with no peers on DHT or any tracker. Slow or dead torrents are ignored
for queue limits so healthier releases are not blocked behind magnets that
never fetch metadata. The `media-qbittorrent` bundle refreshes the tracker list
once daily through the `qbittorrent-tracker-refresh` CronJob; the qBittorrent
deployment does not seed or rewrite that list on pod startup.

## Rancher/Fleet Flow

Fleet watches `kubernetes/projects/entertainment/apps/*` through the
`home-lab-entertainment` GitRepo. Commit and push these app directories to the
configured Fleet branch, then Rancher reconciles one bundle per directory.

Most charts are pulled directly from TrueCharts:

`oci://oci.trueforge.org/truecharts/<chart>`

Seerr is pulled from the official Seerr chart:

`oci://ghcr.io/seerr-team/seerr/seerr-chart`

The cluster in this repo is Raspberry Pi based, so each values file overrides
TrueCharts' default `amd64` node selector with:

`kubernetes.io/arch: arm64`

## App URLs

- `http://watch.media.home`
- `http://requests.media.home`
- `http://sonarr.media.home`
- `http://radarr.media.home`
- `http://ryokan.media.home`
- `http://anime.media.home`
- `http://dispatcharr.media.home`
- `http://invite.media.home`
- `http://profilarr.media.home`
- `http://prowlarr.media.home`
- `https://qbittorrent.media.home`
- `http://youtube.media.home`

Legacy qBittorrent split-client hostnames remain as HTTP aliases to
`qbittorrent.media.home` while dependent app settings are consolidated:

- `http://qbittorrent-movies.media.home`
- `http://qbittorrent-anime.media.home`
- `http://qbittorrent-prowlarr.media.home`

qBittorrent exposes torrent TCP/UDP port `53181` through a Cilium LoadBalancer.

The app-service pool starts at `192.168.3.16`, so the TV/default qBittorrent
service is the expected first assigned IP when no other app LoadBalancer has
consumed it. If WAN inbound torrent connectivity is needed, configure matching
TCP/UDP gateway port forwards to the assigned qBittorrent LoadBalancer IP;
Fleet only declares the in-cluster service and Cilium LoadBalancer. Under ISP
CGNAT, gateway forwarding does not make qBittorrent publicly connectable; the
client still downloads over outbound peer connections, but low-health releases
are more likely to stall.

Prowlarr uses direct egress by default. Avoid putting search traffic behind free
VPN Gate endpoints; it adds latency, breaks Cloudflare flows, and causes noisy
rate-limit failures. If qBittorrent needs VPN transport, use a provider and
protocol that support stable inbound port forwarding, then wire that explicitly
instead of routing the whole media stack through a random free OpenVPN endpoint.

The live public-indexer proxy is a Squid instance on the DigitalOcean Droplet
`squid-proxy` at `157.230.236.164:3128`. Prowlarr has an HTTP indexer proxy
named `DigitalOcean Squid` with the `do-proxy` tag. The Droplet stores the proxy
credentials at `/root/prowlarr-squid-credentials.txt`. The DigitalOcean cloud
firewall allows `3128/tcp` only from the current media namespace egress IP and is
kept current by the `do-squid-firewall` CronJob. The Droplet-local UFW and Squid
rules allow authenticated proxy traffic; the cloud firewall is the dynamic source
IP allowlist.

Cloudflare-protected public indexers are routed through the in-cluster
FlareSolverr service at `http://flaresolverr.media.svc.cluster.local:8191`.
Prowlarr has a FlareSolverr indexer proxy named `FlareSolverr` with the
`flaresolverr` tag. FlareSolverr can solve normal browser checks, but some
providers still block or time out the Raspberry Pi cluster egress IP; keep those
indexers disabled until validation succeeds.

## Namespaces

- `media`

## Initial Wiring

Only configure media sources and downloads you have the right to access.
Indexer definitions, credentials, cookies, and API keys live in Prowlarr's
application PVC rather than in Git.

1. Fleet deploys one browser-facing qBittorrent WebUI at
   `https://qbittorrent.media.home` with Traefik's default self-signed
   certificate, and one in-cluster qBittorrent service at
   `http://qbittorrent.media.svc.cluster.local:8080` with categories for `tv`,
   `movies`, `anime`, and `prowlarr`.
2. qBittorrent is configured with category-specific save paths under
   `/downloads`. Legacy service names for `qbittorrent-movies`,
   `qbittorrent-anime`, and `qbittorrent-prowlarr` route to the same pod so
   existing app settings keep working during consolidation. qBittorrent WebUI
   auth is enforced for edge and in-cluster clients; keep automation
   credentials in the `qbittorrent-cleanup` Kubernetes Secret and in the
   dependent apps' own config stores.
3. Keep qBittorrent listening on fixed TCP/UDP port `53181` and configure a
   matching gateway port forward to the qBittorrent LoadBalancer IP when WAN
   inbound peer connectivity is needed.
4. Keep qBittorrent share limits set to stop completed torrents immediately:
   ratio `0`, seeding time `0` minutes, action `Stop`.
5. Enable qBittorrent's automatic tracker fallback list for new public
   downloads.
6. In Sonarr, add qBittorrent as the in-cluster HTTP service
   `http://qbittorrent.media.svc.cluster.local:8080`.
7. In Sonarr, add root folder `/data/tv`.
8. In Radarr, add qBittorrent as the in-cluster HTTP service
   `http://qbittorrent.media.svc.cluster.local:8080` with the `movies`
   category.
9. In Radarr, add root folder `/data/movies`.
10. In Prowlarr, add qBittorrent as the in-cluster HTTP service
   `http://qbittorrent.media.svc.cluster.local:8080` with the `prowlarr`
   category. This client is for manual grabs from Prowlarr.
11. In Prowlarr, connect Sonarr at
   `http://sonarr.media.svc.cluster.local:8989` and Radarr at
   `http://radarr.media.svc.cluster.local:7878`. Set the Prowlarr server URL
   seen by apps to `http://prowlarr.media.svc.cluster.local:9696`. Keep the
   Sonarr/Radarr application links enabled with full sync so Prowlarr remains
   the source of truth for normal TV and movie app indexer configuration. Route app sync with
   tags: assign `sonarr-sync` to the normal Sonarr app and TV-safe indexers,
   and `radarr-sync` to Radarr and movie-safe indexers. Use `radarr-sync` on anime movie-capable indexers
   when Radarr should search them for anime movies. Ryokan does not use
   Prowlarr's Sonarr app sync; add the
   anime Torznab feeds in Ryokan's Indexers settings and remove the old Sonarr
   Anime Prowlarr application plus `sonarr-anime-sync` tags.
   Sonarr's live Prowlarr app sync categories include `5000` for TV and `8000`
   for India/regional public indexes that only report `Other`. Radarr's live
   Prowlarr app sync categories include `8000` because LimeTorrents and some
   regional-search indexers report keywordless validation results under `Other`;
   app title matching still gates actual grabs. Current per-indexer routing
   rules:
   - Direct app-synced TV: `showRSS`.
   - Direct app-synced TV/movie: `Knaben`, `nekoBT`, `The Pirate Bay`, and
     `TorrentKitty`.
   - Direct app-synced movie: `YTS`.
   - DigitalOcean Squid app-synced TV/movie: `LimeTorrents`,
     `TorrentDownload`, and `Uindex`.
   - Anime TV for Ryokan manual Torznab/Newznab setup: `Bangumi Moe`,
     `Nyaa.si`, `SubsPlease`, `Shana Project`, `Tokyo Toshokan`, and
     `AnimeTosho`.
   - Manual-only enabled: `TorrentsCSV` direct, and `Torrent Downloads` through
     `do-proxy`. `Torrent Downloads` passed Prowlarr validation but failed
     Sonarr/Radarr validation with Cloudflare/429, so it must not have app-sync
     tags.
   - Disabled with `flaresolverr`: `1337x`, `ExtraTorrent.st`,
     `kickasstorrents.to`, and `Torrent[CORE]`.
   - Disabled with `do-proxy`: `Demonoid Clone`, `EZTV`,
     `kickasstorrents.ws`, `Magnet Cat`, `Magnetz`, and
     `TorrentGalaxyClone`.
   - Disabled direct: `Anidex` and `AniSource`.
   Disabled indexers keep `manual-only` plus their proxy route tag, and must not
   keep `sonarr-sync` or `radarr-sync`; otherwise Prowlarr will
   sync broken indexers into Sonarr/Radarr.
   Ryokan's Seerr-facing Sonarr API shim uses anibridge plus AniList/MAL
   fallback for anime requests. Shoko does not consume Prowlarr indexers or
   download media.
12. If a public indexer must use alternate egress, use the live DigitalOcean
    Squid proxy:
    add the `do-proxy` tag to specific public indexers that fail from the home
    IP. If the cluster's public egress IP changes, the `do-squid-firewall`
    CronJob updates the DigitalOcean cloud firewall rule within 15 minutes.
13. Keep Prowlarr indexers on the default `Standard` sync profile. For indexers
    with published API/query caps, set each indexer's Query Limit and Grab Limit
    from the provider's documented allowance instead of creating extra sync
    profiles.
14. Create the `arr-api-keys` Secret in the `media` namespace with
    `SONARR_API_KEY`, `RADARR_API_KEY`, and `SONARR_ANIME_API_KEY`. Ryokan's
    Seerr API shims use the anime Sonarr key plus the Radarr key. Ryokan owns
    its own anime scoring and custom formats.
15. In Sonarr, keep one qBittorrent download client using the `tv` category and
    `http://qbittorrent.media.svc.cluster.local:8080`.
    Sonarr owns normal TV only, with `/data/tv` as its only root folder and
    `[TV] WEB-1080p` as the active request profile. Keep the local quality
    policy for the active Sonarr/Radarr request profiles set so 2160p WEB and
    `Bluray-2160p` are allowed with a `Bluray-2160p` cutoff, while
    `HDTV-2160p` and 2160p Remux stay disabled. Add Sonarr's `Emby / Jellyfin`
    notification connection to
    `jellyfin.media.svc.cluster.local:8096` with `Update Library` enabled,
    import/upgrade/rename/delete triggers enabled, and path mapping
    `/data -> /media` so Jellyfin refreshes the imported TV paths immediately.
16. In Ryokan, add qBittorrent as
    `http://qbittorrent.media.svc.cluster.local:8080` using the `anime`
    category, set the qBittorrent download path to `/downloads`, and set
    the media root to `/media/anime`. Enable post-processing and set the file
    operation mode to `Move` so completed anime is removed from downloads after
    import to the NAS. Install Ryokan's bundled anime custom format defaults
    from the Custom Formats settings. Add the enabled anime Prowlarr Torznab
    feeds and enable RSS for them. Configure Ryokan's Jellyfin integration with
    `http://jellyfin.media.svc.cluster.local:8096` and an active Jellyfin API key
    so Ryokan can validate the server connection and request library refreshes
    after imports. Enable Ryokan's Seerr Sonarr API compatibility with
    `SONARR_ANIME_API_KEY` and Radarr API compatibility with `RADARR_API_KEY`;
    the Radarr-compatible Seerr entry must use URL Base `/radarr`.
    Shoko/Shokofin still owns anime metadata in Jellyfin after files are
    imported.
17. In Profilarr, connect Radarr at
    `http://radarr.media.svc.cluster.local:7878` and Sonarr at
    `http://sonarr.media.svc.cluster.local:8989`. Use `Settings > Onboarding`
    to link the Dictionarry v2 database and configure sync. Manage normal movie
    and TV quality profiles, custom formats, delay profiles, media-management
    naming, quality definitions, and miscellaneous media-management settings
    through Profilarr instead of manually recreating guide profiles in each Arr
    app.
    Keep Radarr's built-in Propers/Repacks preference set to
    `Do Not Prefer` so profile-managed Repack/Proper custom formats control
    that behavior. Add Radarr's `Emby / Jellyfin` notification connection to
    `jellyfin.media.svc.cluster.local:8096` with `Update Library` enabled,
    import/upgrade/rename/delete triggers enabled, and path mapping
    `/data -> /media` so Jellyfin refreshes imported movie paths immediately.
18. In Radarr, use a separate anime movie profile instead of changing the normal
    movie profile. Manage that profile through Profilarr/Dictionarry as well,
    using the anime movie profile and custom formats that match the live stack's
    scoring policy. Use this profile only for anime movies unless a second
    anime-only Radarr instance is added later.
19. In Shoko, complete first-run setup at `http://anime.media.home` and add
    `/media/anime` as the anime import folder. This mount is read-only in
    Kubernetes so Shoko can scan metadata without moving or rewriting files.
20. In Dispatcharr, complete first-run setup at
    `http://dispatcharr.media.home`, add the public India M3U playlist
    `https://iptv-org.github.io/iptv/countries/in.m3u`, add the XMLTV guide
    `https://iptv-epg.org/files/epg-in.xml`, and create the channels Jellyfin
    should see. Jellyfin Live TV should point at Dispatcharr's filtered `EPG`
    profile, where channels with zero XMLTV program rows or dead upstream
    streams are disabled:
    `http://dispatcharr.media.svc.cluster.local:9191/hdhr/EPG` and
    `http://dispatcharr.media.svc.cluster.local:9191/output/epg/EPG`.
21. In Jellyfin, add libraries:
    - TV: `/media/tv` as a Shows/`tvshows` library.
    - Anime: `/media/anime` as a Shows/`tvshows` library, not Movies. Use
      Shokofin/Shoko metadata for this library instead of Sonarr local NFO
      metadata.
    - Movies: `/media/movies`
    Avoid Jellyfin's mixed library type because mixed libraries produce
    unreliable metadata matches.
    Keep real-time monitoring enabled, but leave LUFS scanning, chapter-image
    extraction, trickplay image extraction, trickplay extraction during library
    scans, and embedded-title parsing disabled during scans. Disable scheduled
    `Generate Trickplay Images` and `Extract Chapter Images` triggers.
    Jellyfin should read local `Nfo` files first and should not write metadata
    back into the media library. Keep hardware transcoding disabled until the
    deployment has a supported GPU/VPU device mounted.
22. In Seerr, connect Jellyfin at
    `http://jellyfin.media.svc.cluster.local:8096`, Sonarr at
    `http://sonarr.media.svc.cluster.local:8989`, Ryokan's Sonarr API shim at
    `http://ryokan.media.svc.cluster.local:8978`, and Radarr at
    `http://radarr.media.svc.cluster.local:7878`. Use the existing
    `SONARR_ANIME_API_KEY` for the anime server. Set Radarr's default movie
    request profile to the Dictionarry-managed normal movie profile; add a
    second non-default Radarr service entry named `Ryokan Anime Movies` pointing
    at `http://ryokan.media.svc.cluster.local:8978` with URL Base `/radarr` and
    the existing `RADARR_API_KEY`. Set Sonarr's normal TV request profile to
    `[TV] WEB-1080p` and root folder to `/data/tv`; add a second non-default
    Sonarr service entry named
    `Ryokan Anime` using Ryokan's shim-provided quality profile and root folder.
    Keep 4K request servers disabled. The live Seerr network settings prefer IPv4,
    use a 30 second Servarr API timeout, and route external metadata requests
    through the DigitalOcean Squid proxy. Keep the Seerr proxy bypass filter
    covering local media hosts, currently
    `*.cluster.local,*.svc.cluster.local,*.media.home,watch.media.home,localhost,127.0.0.1`,
    so Radarr, Sonarr, and Jellyfin stay direct instead of going through Squid.
qBittorrent uses its built-in WebUI authentication on both edge and in-cluster
access. Profilarr is protected at the Traefik edge by the
`media-edge-basic-auth` middleware.
