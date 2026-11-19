# Ryokan

Ryokan is the anime-only request and import service.

The deployment runs continuously with one replica managed by Git/Fleet.
Existing configuration, storage and application data are retained. Automatic
replica scaling and availability recovery remain disabled in its recommendation
profile.

It retains two ReplicaSet revisions; Git and Fleet history remain the primary
rollback path.

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
   The Fleet-managed init container keeps the recycle bin at
   `/media/anime/.recycle` with 14-day retention. The hidden directory shares
   the media filesystem, so replacements use an atomic move and can be restored
   from Library -> Recycle Bin before cleanup.
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

## Official runtime

The app uses the official [johnthreekay/Ryokan](https://github.com/johnthreekay/Ryokan)
image at version **2.3.0**, through Harbor's GHCR proxy, pinned to immutable
multi-platform digest `sha256:8e4aaa2aa097d94270eaf0289e3732cd5d7d95155f2a5e43c6e35079e353f0d2`.
The verified ARM64 manifest is
`sha256:0d8735ce242edfd26199c74f8cefb031b323848acab476ba5de3fdc8d826a9e0`.
Release source: [v2.3.0](https://github.com/johnthreekay/Ryokan/releases/tag/v2.3.0).

This replaces the private 1.9.13 fork. The fork's per-file checkpoint and
one-file-per-pass settings are not part of the official image; its two custom
post-processing environment variables are removed. Imports now follow upstream
behavior. Existing configuration, private key, artwork and library storage are
retained. Credential initialization still enforces source-retaining copy mode
and recycle protection before the app starts. Upstream performs its database
migrations at startup after the stopped-state backup completes. A rollback
across this version change requires restoring that backup, not only reverting
the image tag.

The import reconciler shares Ryokan's UID/GID 568 because the official entrypoint
makes `/data` private to that user. Directory permissions remain private.
The pod also runs the narrowly scoped import reconciler on port `8979` with a
`256Mi` memory limit for bulk receipt checks. Smart
Queues submits the selected qBittorrent media paths while copy-mode sources are
still retained. The reconciler compares them with Ryokan's
`imported_source_paths` receipt and requires one distinct library file with the
same size per source before deletion is allowed. If an exact hash is already marked
`imported` but the receipt is incomplete, it is atomically returned to
`pending`; Smart Queues then rechecks the torrent and Ryokan's normal
post-processing loop imports the complete set. Requeue is allowed only when the
grabbed episode count is below the selected qBittorrent media count. Older batch
metadata may include secondary files; exact source receipts and library targets
remain mandatory. Other states and unknown, ambiguous, or batch-shape-mismatched
hashes are never modified.
Authentication reuses
`SONARR_ANIME_API_KEY` from `media-jellyfin-arr-api-keys`. Ryokan's ingress
boundary exposes port `8979` only to the Smart Queues pod selector.
The same encrypted Secret supplies `PROWLARR_API_KEY` to the startup reconciler
so all configured Prowlarr endpoints stay aligned after credential rotation.

Do not use automatic requeue for a partial multi-file batch when the current
qBittorrent selection differs from the original episode set, or when a prior
import overwrote existing library episodes. Quarantine that torrent outside the
`anime` and `priority-anime` categories and follow the
[Ryokan batch import corruption recovery runbook](../../../../../docs/runbooks/storage/ryokan-batch-import-corruption-recovery.md).
The recovery download must remain outside Ryokan post-processing until every
source-to-destination episode and byte size has been verified.

## Direct HTTPS egress

Ryokan sends external HTTPS requests directly through normal cluster egress.

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

The `ryokan-data` Longhorn PVC is mounted at `/data` with `8 GiB` requested
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

The data claim declares 8Gi. Preserve SQLite, WAL, artwork and recovery snapshots.
After expanding through Fleet, verify the PVC capacity and mounted filesystem;
a larger request does not prove filesystem expansion. Claims cannot shrink.
Review recovery-snapshot retention separately from database storage alerts.

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
  for `Nyaa request failed`. Ryokan renders transport failures as an empty
  result set. Confirm direct pod egress to `https://nyaa.si/` and check whether
  the indexer is blocking or rate-limiting the current public WAN address.
- **Low-resolution posters:** verify `/data` is not full, then run **Rebuild
  metadata cache**. AniList `/cover/small/` assets are only about 100 pixels
  wide; healthy hydrated covers use the high-resolution artwork cache.

## Pre-start state restore points

The first init container backs up the stopped SQLite database, private key,
artwork and import-reconciler state before credential sync or either writer
starts. See [the shared backup contract](../media-state-backups/README.md).
No additional quiesce commit or backup Job is used.

Official Ryokan 2.3.0 keeps both qBit consumers on the verified 0.2.14 image.
The Ryokan backup cohort is `qbit-0.2.14-ryokan-2.3.0`; the qBit controller
uses the matching cohort for this fail-safe guard release.
The first init makes a new complete stopped SQLite/configuration/key restore
point for this target cohort before credential sync and both writers start.

## Credential init runtime

The credential-sync init uses the same immutable, independently verified public
[Python image](../media-state-backups/public-helper-image.json) as the backup
helper, with `/usr/bin/python -c` and its existing numeric UID/GID 568. The
standard-library script, required Secret key references, security context and
`/data` mount are unchanged. It needs only `os`, `sqlite3`, `time` and `pathlib`;
there is no startup installer or network request. The stopped-source backup
still runs first, before credential sync changes any SQLite rows or schema.

A runtime-pin update requires upstream signature verification, native platform
manifests/configurations, recognized OS inventory/SBOM, strict zero high/critical
and secret findings, and execution of the exact credential script in a
read-only, capability-free, no-network UID568 image fixture. Tests cover absent
state, missing required inputs, both indexer branches, the additive column
migration, policy/credential idempotency and complete row/schema rollback on
failure. `updated_at` remains deliberately refreshed by the existing script;
idempotency does not mean freezing operational timestamps.

```bash
python3 -m unittest discover -s kubernetes/projects/entertainment/apps/media-ryokan/tests -v
python3 kubernetes/projects/entertainment/apps/media-ryokan/scripts/verify-credential-runtime.py
```

The native Docker test uses a private `/data` tmpfs and runs the script bytes
unchanged. Local repository tests relocate only the database path into a new
disposable fixture. Production acceptance requires both init containers to exit
successfully, expected image identities, the retained source/key metadata and
healthy anonymous login/assets; no synthetic production credentials or writes
are used for verification.

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `media/ryokan/ryokan` | 75m → 25m | 512Mi → 1152Mi | 2Gi → 2Gi |
| `media/ryokan/import-reconciler` | 10m → 10m | 32Mi → 96Mi | 256Mi → 256Mi |

## Guarded import-state recovery

Updating the shared immutable pre-start backup helper also recreates Ryokan.
Before starting either application container, the init validates retained
restore points and creates and restores a new backup. Large historical archives
can keep this phase busy for several minutes; check init logs and I/O progress
and allow its configured deadline before treating it as a stalled rollout.

The 28 October review found a roughly 4.1GiB database dominated by repeated
post-processing warnings for unrelated torrents assigned to the wrong series.
Quarantine those torrents before repairing state; preserving their source files
keeps classification reversible and prevents the same retry loop.

`scripts/recover-import-state.py` is an operator tool, not a startup hook or
periodic controller. It defaults to dry-run. Use it only after the current
Pod's `backup-state-before-start` init exits zero with a `status: verified`
termination record. Verify the Pod/PVC identities and archive receipt first.
Keep Smart Queues paused through Git/Fleet while classifying or deleting payloads.

The reviewed JSON plan supplies that backup record, the existing receipt count,
and exact completed torrent hashes, source paths/sizes, series identities and
episode numbers. The tool refuses incomplete, already-tracked or mismatched
downloads, requires copy mode and recycle protection, preserves old import
receipts, and lets Ryokan perform the actual imports. It does not move or delete
media. Logs retain the newest 100,000 non-error rows and 10,000 errors; bounded
transactions and WAL/disk checks protect the small volume before compaction.
This one-off maintenance does not alter Ryokan's normal retention scheduler.

Run the dry-run and inspect the plan before adding `--apply`; execute in the
existing reconciler container with its normal application UID and mounts.
It mounts the database and library, but not downloads. For adoption, collect
fresh, nonsymlink source-file stats through the existing Sonarr downloads mount
and include `source_verification` in the plan (Pod UID, Unix `verified_at`, and
exact `files` observations). Verify that Pod UID before and after collection;
observations expire after five minutes. Recheck qBittorrent completion/hash/name
and content path before executing. No new Pod or writable source mount is needed.
For log-only maintenance, supply an empty adoption list. The helper selects the
writable database directory for SQLite temporary files and checkpoints the WAL
after compaction; a read-only container root is not valid scratch space.
Archive the plan, output and verification locally, never credentials or private
torrent metadata in Git. Verify new receipts and byte-matched library copies
before any qBittorrent source cleanup, then restore the single controller replica.

A measured 4.1GiB legacy database exceeded the former 1,800-second backup
deadline. The bounded backup allowance is now 3,600 seconds, Deployment
progress allowance 4,800 seconds, and Fleet Helm timeout 5,400 seconds.
Full database, archive readback and restored-file checks remain enabled.
Reducing the stale log backlog is still required; longer deadlines do not
replace the guarded maintenance procedure.
