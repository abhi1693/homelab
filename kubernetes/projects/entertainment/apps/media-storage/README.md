# Media Stack

This stack runs a Rancher/Fleet-managed media automation pipeline using
TrueCharts OCI Helm charts, the official Seerr OCI Helm chart, and raw
Kubernetes manifests for custom services.

## Operational state

The download and import pipeline is intentionally stopped: qBittorrent, Smart
Queues, Sonarr, Radarr, Prowlarr, FlareSolverr, Ryokan, and Shoko have zero
replicas, and qBittorrent's maintenance CronJobs are suspended. Retained PVCs,
Services, and library playback remain in place. Jellyfin, Seerr, Episeerr,
Profilarr, and Music Assistant remain available.

## Architecture

- `qBittorrent`: torrent download client.
- `Prowlarr`: torrent indexer manager for Sonarr and Radarr.
- `Sonarr`: TV management.
- `Ryokan`: anime TV request and download management.
- `Radarr`: movie management.
- `Shoko`: anime metadata and library management for Jellyfin/Shokofin.
- `Jellyfin`: video, anime, and live TV media server.
- `Seerr`: Jellyfin request portal. The Kubernetes release and internal Service
  name remain `jellyseerr` for compatibility, but the workload runs the official
  Seerr chart/image.
- `Music Assistant`: authenticated YouTube Music account mirror, persistent
  local cache, on-device audio-similarity radio, recommendations, PWA, and
  playback.

All app releases run in the `media` namespace, which is assigned to the Rancher
`Entertainment` project.

The completed media library is stored on the UNAS Pro 4 Shared Drive
`192.168.1.128:/var/nfs/shared/media`. The storage bundle binds that export to
the `media/media-library-unas` PVC through the upstream NFS CSI driver, with a
requested capacity of `10Ti`. This is an advertised Kubernetes capacity rather
than an NFS quota; the UNAS controls the Shared Drive's actual available space.
The PV/PVC pair is statically bound with no StorageClass, so the driver mounts
the existing export root and does not create a server-side subdirectory. It
currently uses NFSv3 because the Shared Drive is not exposed in the UNAS NFSv4
namespace; move it to NFSv4.1 only after a real read-write v4 mount succeeds.

Sonarr and Radarr mount the completed-media PVC at `/data`. Jellyfin mounts the
same PVC at `/media`, while keeping its own application data under its
chart-managed `/data` PVC.

Music Assistant mounts the same completed-library PVC twice: the common
`/library/music` tree is read-only at `/media`, while
`/library/music/YouTube Music` is writable at `/library-cache/music/YouTube
Music` for atomic background cache publication. Production allows three
concurrent yt-dlp track downloads; each stages on the retained application PVC
before its completed file is atomically copied to NFS. The provider catalog and
queue live in PostgreSQL rather than on this claim.

The retired music applications' app-owned Longhorn PVCs are deleted with their
Fleet bundles. Their old shared-export directories—`music/Lidarr`,
`music/Aurral`, and `downloads/slskd`—remain on the NAS. Those paths are
operator-owned retained data and are not removed by Kubernetes retirement.

The previous Longhorn `media-library` PVC and standalone Longhorn volume are no
longer declared. Do not recreate `media-library`; the UNAS-backed
`media-library-unas` PVC is the completed-media library. The old
`media-library-nfs-csi` claim remains bound to
`192.168.3.115:/nfs/media_new` as a read-only rollback source and is not mounted
by active consumers.

Downloads are intentionally separated from the completed Jellyfin library.
The qBittorrent clients, Sonarr, Ryokan, and Radarr mount the
`media-downloads-unas` PVC backed by
`192.168.1.128:/var/nfs/shared/torrents` on the UNAS Pro 4; Jellyfin does not
mount it. The existing static claim still advertises `3T`; that pre-bound PVC
cannot be expanded without recreation and its requested size does not enforce
NFS capacity. The UNAS Shared Drive's decimal `4 TB` quota is the authoritative
ceiling and remains the NAS enforcement boundary.
The static volume currently mounts with NFSv3 because UniFi Drive does not yet
expose the Shared Drive in its advertised NFSv4 namespace. Move it to NFSv4.1
only after a real read-write v4 mount succeeds.
The qBittorrent
clients write incomplete and completed torrent payloads to `/downloads`, then
Sonarr imports finished TV into `/data/tv`. Radarr imports normal movies into
`/data/movies` and anime movies into `/data/anime`.
Ryokan mounts `/downloads` because qBittorrent reports anime torrent paths relative to that
root, but it only processes torrents from the anime qBittorrent client using
the `anime` category. Ryokan imports anime into `/media/anime`, which is the
NAS anime subfolder and the same directory Radarr sees as `/data/anime` for
anime movies. Shoko scans the NAS anime library read-only at `/media/anime`,
and Jellyfin scans the same completed library path. This keeps Jellyfin from
scanning partial downloads and preserves the completed-media PVC as the final
library only.

The `media-downloads-unas` and `media-library-unas` claims are the active
download and completed-library storage. The former `media-downloads-nfs-csi`
claim remains bound to
`192.168.3.115:/nfs/torrents` only as a retained rollback source until that old
Shared Drive is removed. The old `media_new` export also remains unchanged for
rollback. `media-storage` permanently owns both retained UNAS PV/PVC pairs.

Use the
[anime library relocation and Shoko recovery runbook](../../../../../docs/runbooks/storage/anime-library-relocation-and-shoko-recovery.md)
when correcting anime that was previously imported below `movies` or `tv`.

The qBittorrent clients stop torrents immediately after completion by using a
zero ratio and zero seeding-time limit. Sonarr and Radarr have
completed-download removal enabled, so after they successfully import a
completed item to the NAS-backed library, they remove the stopped torrent and
its payload from `/downloads`. Ryokan owns anime post-processing from the anime
qBittorrent client and uses move mode so completed anime lands in the
NAS-backed `/media/anime` library and is removed from `/downloads` after
import.

The legacy Longhorn-backed `media-downloads` PVC and the former direct-NFS
`media-library-nas`, `media-library-nas-v2`, and `media-downloads-nas` PV/PVC
pairs were removed after Fleet reported both NFS CSI claims bound and every
current media consumer was verified against them. The static direct-NFS PVs
used `Retain`, so deleting their Kubernetes objects did not remove either NAS
export or its data.

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
- `https://music.media.home`
- `http://requests.anime.media.home`
- `http://anime.media.home`
- `http://prowlarr.media.home`
- `https://qbittorrent.media.home`

qBittorrent exposes torrent TCP/UDP port `53181` through the fixed MetalLB
Layer 2 VIP `192.168.3.16`.

The qBittorrent Service requests `192.168.3.16` explicitly from the
`app-services` pool, so its gateway port-forward target does not depend on
allocation order. If WAN inbound torrent connectivity is needed, configure
matching TCP/UDP gateway port forwards to the assigned qBittorrent LoadBalancer
IP; Fleet declares the in-cluster service and MetalLB allocation. Under ISP
CGNAT, gateway forwarding does not make qBittorrent publicly connectable; the
client still downloads over outbound peer connections, but low-health releases
are more likely to stall.

Prowlarr uses direct egress by default. Avoid putting search traffic behind free
VPN Gate endpoints; it adds latency, breaks Cloudflare flows, and causes noisy
rate-limit failures. If qBittorrent needs VPN transport, use a provider and
protocol that support stable inbound port forwarding, then wire that explicitly
instead of routing the whole media stack through a random free OpenVPN endpoint.

Public indexers use the normal cluster egress path by default. The previous
DigitalOcean Squid proxy path has been retired now that the primary WAN has a
static public IPv4 address and direct Nyaa access from the Ryokan pod validates.
Do not recreate the old `DigitalOcean Squid` Prowlarr proxy or `do-proxy` tag
unless a future indexer-specific incident justifies a new alternate egress path.

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
   `/downloads`. All dependent apps use the canonical `qbittorrent` Service;
   qBittorrent WebUI auth is enforced for edge and in-cluster clients. Keep
   automation credentials in the `qbittorrent-cleanup` Kubernetes Secret and
   in the dependent apps' own config stores.
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
   - Direct app-synced TV/movie: `Knaben`, `nekoBT`, `The Pirate Bay`,
     `TorrentKitty`, `LimeTorrents`, `TorrentDownload`, and `Uindex`.
   - Direct app-synced movie: `YTS`.
   - Anime TV for Ryokan manual Torznab/Newznab setup: `Bangumi Moe`,
     `Nyaa.si`, `SubsPlease`, `Shana Project`, `Tokyo Toshokan`, and
     `AnimeTosho`.
   - Manual-only enabled: `TorrentsCSV` and `Torrent Downloads` direct.
     `Torrent Downloads` passed Prowlarr validation but failed Sonarr/Radarr
     validation with Cloudflare/429, so it must not have app-sync tags.
   - Disabled with `flaresolverr`: `1337x`, `ExtraTorrent.st`,
     `kickasstorrents.to`, and `Torrent[CORE]`.
   - Disabled direct: `Anidex`, `AniSource`, `Demonoid Clone`, `EZTV`,
     `kickasstorrents.ws`, `Magnet Cat`, `Magnetz`, and `TorrentGalaxyClone`.
   Disabled indexers keep `manual-only` and must not keep `sonarr-sync` or
   `radarr-sync`; otherwise Prowlarr will sync broken indexers into Sonarr/Radarr.
   Ryokan's Seerr-facing Sonarr API shim uses anibridge plus AniList/MAL
   fallback for anime requests. Shoko does not consume Prowlarr indexers or
   download media.
12. If a public indexer fails from the home IP, prefer direct validation and
    FlareSolverr for browser challenges before adding any new alternate egress
    path. There is no live DigitalOcean Squid proxy or firewall updater.
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
    `Default` as the active request profile. Keep the active automatic Sonarr
    and Radarr request profiles in the app-default quality order with HD and UHD
    qualities allowed through the highest 2160p cutoff, so existing UHD library
    files are not replaced by lower-resolution 1080p releases. Keep CAM,
    telesync, SD/DVD, raw-HD, BR-DISK, and other low-quality sources disabled
    for normal automatic requests. When cleaning pre-policy queue entries,
    remove and blocklist a torrent with its download data only when every item
    in that torrent already has a library file and progress is at most 30
    percent.
    Preserve mixed or missing-item torrents and pure upgrades above 30 percent
    so useful downloads and already-spent bandwidth are not discarded. Add
    Sonarr's `Emby / Jellyfin` notification connection to
    `jellyfin.media.svc.cluster.local:8096` with `Update Library` enabled,
    import/upgrade/rename/delete triggers enabled, and path mapping
    `/data -> /media` so Jellyfin refreshes the imported TV paths immediately.
16. In Ryokan, add qBittorrent as
    `http://qbittorrent.media.svc.cluster.local:8080` using the `anime`
    category, set the qBittorrent download path to `/downloads`, and set
    the media root to `/media/anime`. Enable post-processing and set the file
    operation mode to `Copy` so completed anime remains recoverable until exact
    Ryokan receipts and distinct size-matched NAS targets are verified; Smart
    Queues then removes the qBittorrent source. Install Ryokan's bundled anime
    custom format defaults from the Custom Formats settings. Add the enabled anime Prowlarr Torznab
    feeds and enable RSS for them. Configure Ryokan's Jellyfin integration with
    `http://jellyfin.media.svc.cluster.local:8096` and an active Jellyfin API key
    so Ryokan can validate the server connection and request library refreshes
    after imports. Enable Ryokan's Seerr Sonarr API compatibility with
    `SONARR_ANIME_API_KEY` and Radarr API compatibility with `RADARR_API_KEY`;
    the Radarr-compatible Seerr entry must use URL Base `/radarr`.
    Shoko/Shokofin still owns anime metadata in Jellyfin after files are
    imported. Keep Ryokan's preferred source at WEB, cutoff source at Blu-ray,
    and both preferred and cutoff resolution at 2160p so scheduled upgrade
    search can improve anime through the highest common library tier.
17. Manage the existing movie and TV quality profiles, custom formats, delay
    profiles, naming, quality definitions, and media-management settings
    directly in Radarr and Sonarr.
    Keep Radarr's built-in Propers/Repacks preference set to
    `Do Not Prefer` so Repack/Proper custom formats control
    that behavior. Add Radarr's `Emby / Jellyfin` notification connection to
    `jellyfin.media.svc.cluster.local:8096` with `Update Library` enabled,
    import/upgrade/rename/delete triggers enabled, and path mapping
    `/data -> /media` so Jellyfin refreshes imported movie paths immediately.
    Use `Default` as the normal movie request profile and keep its HD/UHD
    quality order aligned with Sonarr's normal TV profile.
18. In Radarr, add `/data/anime` as the anime movie root and use the separate
    anime movie profile and custom formats that match the live stack's scoring
    policy. Use this root and profile only for anime movies unless a second
    anime-only Radarr instance is added later.
19. In Shoko, complete first-run setup at `http://anime.media.home` and add
    `/media/anime` as the anime import folder. This mount is read-only in
    Kubernetes so Shoko can scan metadata without moving or rewriting files.
20. In Jellyfin, add libraries:
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
21. In Seerr, connect Jellyfin at
    `http://jellyfin.media.svc.cluster.local:8096`, Sonarr at
    `http://sonarr.media.svc.cluster.local:8989`, Ryokan's Sonarr API shim at
    `http://ryokan.media.svc.cluster.local:8978`, and Radarr at
    `http://radarr.media.svc.cluster.local:7878`. Use the existing
    `SONARR_ANIME_API_KEY` for the anime server. Set Radarr's default movie
    request profile to `Default`; add a
    second non-default Radarr service entry named `Ryokan Anime Movies` pointing
    at `http://ryokan.media.svc.cluster.local:8978` with URL Base `/radarr` and
    the existing `RADARR_API_KEY`. Set Sonarr's normal TV request profile to
    `Default` and root folder to `/data/tv`; add a second non-default
    Sonarr service entry named
    `Ryokan Anime` using Ryokan's shim-provided quality profile and root folder.
    Keep 4K request servers disabled. The live Seerr network settings prefer IPv4
    and use a 30 second Servarr API timeout; external metadata requests use
    direct egress.

## Music Initial Wiring

1. Open `https://music.media.home`, create the Music Assistant administrator,
   enable the built-in Sendspin web player, and add `/media` as a local
   filesystem music source when retained local media should be indexed.
2. Confirm the Fleet-managed **YouTube Music** source loads. It reads the
   browser cookie from `music-assistant-secrets`, stores it encrypted in Music
   Assistant, mirrors the account snapshot into PostgreSQL, and caches audio
   under `music/YouTube Music` without a PO-token service.
3. Replace the SOPS value and increment Music Assistant's
   `home-lab.io/ytmusic-cookie-revision` pod-template annotation when YouTube
   expires the session.

Only configure media sources and downloads that you have the right to access.

qBittorrent uses its built-in WebUI authentication on both edge and in-cluster
access.
