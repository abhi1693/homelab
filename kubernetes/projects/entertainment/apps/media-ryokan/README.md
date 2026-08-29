# Ryokan

Ryokan replaces the old Sonarr Anime instance as the anime-only PVR.

## Operational state

Ryokan is intentionally stopped with zero replicas while the qBittorrent anime
download and import pipeline is disabled. Its persistent configuration and
library storage are retained. Restore it to one replica with Shoko and the
other download automation workloads.

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
3. In Settings -> General, set the media root to `/media/anime` and enable
   post-processing. The Fleet-managed init container enforces file operation
   mode `Copy`, retaining the qBittorrent source until Ryokan has committed an
   exact import receipt for every selected video and every distinct,
   size-matched NAS library target exists. Smart Queues then deletes the
   qBittorrent entry and source files. Do not change this back to `Move`:
   planned workload shutdowns can interrupt a cross-filesystem copy.
   The short-lived credential sync requests `5m` CPU and `32Mi` memory with a
   `96Mi` memory limit.
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
7. In Settings -> Quality, keep WEB as the preferred source, Blu-ray as the
   cutoff source, and set both the preferred and cutoff resolution to `2160`.
   This lets scheduled upgrade search improve anime through the highest common
   library tier instead of stopping at the former 1080p ceiling.

Ryokan mounts `/downloads` so it can read qBittorrent's reported anime torrent
paths, and `/media/anime` as the NAS-backed anime library.

Completed multi-video grabs are treated as batches from their actual wanted
file shape even when the indexer recorded `is_batch=false` and only episode 1.
Videos beneath `Extras/`, `Samples/`, `Trailers/`, and similar secondary-media
directories are excluded from episode routing and batch preflight. Dotted codec
tokens such as `H.264` and `H.265` are not interpreted as episode numbers.
Ryokan validates every parseable episode destination before copying any file:
unparseable or non-positive extras are warned and skipped, while duplicate
episode destinations fail the whole import without changing the library.

The pod also runs the narrowly scoped import reconciler on port `8979`. Smart
Queues submits the selected qBittorrent media paths while copy-mode sources are
still retained. The reconciler compares them with Ryokan's
`imported_source_paths` receipt and requires one distinct library file with the
same size per source before deletion is allowed. If an exact hash is already marked
`imported` but the receipt is incomplete, it is atomically returned to
`pending`; Smart Queues then rechecks the torrent and Ryokan's normal
post-processing loop imports the complete set. Requeue is allowed only when the
grabbed episode count equals the selected qBittorrent media count. Other states
and unknown, ambiguous, or batch-shape-mismatched hashes are never modified.
Authentication reuses
`SONARR_ANIME_API_KEY` from `media-jellyfin-arr-api-keys`. Ryokan's ingress
boundary exposes port `8979` only to the Smart Queues pod selector.

Do not use automatic requeue for a partial multi-file batch when the current
qBittorrent selection differs from the original episode set, or when a prior
import overwrote existing library episodes. Quarantine that torrent outside the
`anime` and `priority-anime` categories and follow the
[Ryokan batch import corruption recovery runbook](../../../../../docs/runbooks/storage/ryokan-batch-import-corruption-recovery.md).
The recovery download must remain outside Ryokan post-processing until every
source-to-destination episode and byte size has been verified.

## Direct HTTPS egress

Ryokan sends external HTTPS requests directly from the cluster. The primary WAN
now has a static public IPv4 address and direct Nyaa access from the Ryokan pod
has been validated, so the former DigitalOcean Squid proxy path is retired.

Ryokan's qBittorrent, Prowlarr, and Jellyfin connections continue to use
in-cluster HTTP service URLs. Nyaa and other public HTTPS indexer traffic use
the normal cluster egress path.

After WAN or indexer changes, verify the direct path without exposing secrets:

```bash
kubectl -n media logs deployment/ryokan --since=10m \
  | grep -E "Search failed|Nyaa request failed"
```

A successful built-in search and no matching error confirm the direct path.

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
  empty username and password reliably produces HTTP 403. Ryokan's init
  container syncs those Secret values into the SQLite download-client rows on
  pod startup. After rotating the qBittorrent password, bump
  `home-lab.io/qbittorrent-credential-revision` in `deployment.yaml` so Fleet
  reruns the init sync and rolls Ryokan away from any qBittorrent WebUI auth ban
  on the old pod IP.
- **AniList `MediaListCollection` error:** inspect Ryokan egress and DNS to
  `graphql.anilist.co`, then retry after connectivity recovers. A successful
  workstation request does not prove that the Ryokan Pod can reach AniList.
- **Nyaa search shows `No results` for a known title:** inspect the Ryokan logs
  for `Nyaa request failed`. Ryokan 1.8.x renders transport failures as an empty
  result set. Confirm direct pod egress to `https://nyaa.si/` and check whether
  the indexer is blocking or rate-limiting the current public WAN address.
- **Low-resolution posters:** verify `/data` is not full, then run **Rebuild
  metadata cache**. AniList `/cover/small/` assets are only about 100 pixels
  wide; healthy hydrated covers use the high-resolution artwork cache.
