# Ryokan

Ryokan replaces the old Sonarr Anime instance as the anime-only PVR.

The deployment runs as a single replica with persistent configuration and
library mounts.

It retains two ReplicaSet revisions; Git and Fleet history remain the primary
rollback path.

The `media-anime` recommendation profile observes CPU and memory usage every
five minutes and retains learning history for right-sizing. Resource and
replica changes remain disabled while the initial operational baseline is
collected.

The web UI is available at `http://requests.anime.media.home`.

## First-run setup

1. Open `http://requests.anime.media.home` and create the admin account.
2. In Settings -> Download Clients, add qBittorrent:
   - URL: `http://qbittorrent.media.svc.cluster.local:8080`
   - Username and password: use `QBT_USER` and `QBT_PASSWORD` from the
     `media-qbittorrent-cleanup` Secret. Do not leave them blank or copy them
     into Git.
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

## HTTPS proxy egress

Ryokan sends external HTTPS requests through the authenticated DigitalOcean
Squid proxy managed by `media-do-squid-firewall`. This gives the built-in
Nyaa scraper an egress path that is not reset by the home ISP. The proxy URL is
stored as `HTTPS_PROXY` in the SOPS-encrypted `ryokan-proxy` Secret; never put
its username or password in the ConfigMap or documentation.

Keep the proxy URL under `stringData` in `secrets.sops.yaml`. The SOPS operator
treats `data` values as pre-encoded base64; putting the plaintext URL there
prevents it from creating the `ryokan-proxy` child Secret.

`NO_PROXY` keeps loopback, Kubernetes service DNS, the Pod and Service CIDRs,
and the known AniList, MAL/Jikan, Kitsu, GitHub, and SeaDex metadata endpoints
on the direct path. Ryokan's qBittorrent, Prowlarr, and Jellyfin connections use
HTTP service URLs and therefore are not sent through the HTTPS proxy. Nyaa and
other public HTTPS indexer traffic use the controlled Squid egress.

The Fleet bundle depends on `media-do-squid-firewall`, which keeps the remote
firewall's `3128/tcp` source allowlist synchronized with the home public IPv4
address. When the Squid credential changes, update both Prowlarr and
`secrets.sops.yaml`, then verify without exposing the credential:

```bash
kubectl -n media logs deployment/ryokan --since=10m \
  | grep -E "Search failed|Nyaa request failed"
```

A successful built-in search and no matching error confirm the proxy path.

## Persistent data and poster artwork

The `ryokan-data` Longhorn PVC is mounted at `/data` with `4 GiB` requested
capacity. It stores the SQLite database, WAL, AniBridge cache, and locally
cached poster/banner artwork. Keep enough free space for both the database WAL
and high-resolution artwork; a full volume can surface as SQLite `database is
locked`, failed metadata refreshes, and stale or low-resolution posters.

Ryokan initially receives a search-result poster and then hydrates full
metadata from AniList. The full metadata path prefers AniList's `extraLarge`
cover, caches it locally, and refreshes tracked-series metadata every 12 hours.
After a provider outage or a bulk request migration, open `/system` and run
**Maintenance actions -> Rebuild metadata cache**. The rebuild is complete only
when it reports no failed titles and the PVC still has free space:

```bash
kubectl -n media exec deployment/ryokan -- df -h /data
```

Do not delete `ryokan.db`, its WAL files, or artwork blobs manually. Expand the
Fleet-managed PVC when capacity is the problem, then rerun the native rebuild.

## Connection troubleshooting

- **qBittorrent Forbidden:** network connectivity succeeded, but qBittorrent
  rejected the unauthenticated or incorrect login. Confirm Ryokan has the
  `QBT_USER` and `QBT_PASSWORD` values from `media-qbittorrent-cleanup`; an
  empty username and password reliably produces HTTP 403.
- **AniList `MediaListCollection` error:** inspect Ryokan egress and DNS to
  `graphql.anilist.co`, then retry after connectivity recovers. A successful
  workstation request does not prove that the Ryokan Pod can reach AniList.
- **Nyaa search shows `No results` for a known title:** inspect the Ryokan logs
  for `Nyaa request failed`. Ryokan 1.8 renders transport failures as an empty
  result set. Confirm the `ryokan-proxy` Secret exists, the
  `media-do-squid-firewall` CronJob is succeeding, and the remote Squid
  credential matches the encrypted proxy URL.
- **Low-resolution posters:** verify `/data` is not full, then run **Rebuild
  metadata cache**. AniList `/cover/small/` assets are only about 100 pixels
  wide; healthy hydrated covers use the high-resolution artwork cache.
