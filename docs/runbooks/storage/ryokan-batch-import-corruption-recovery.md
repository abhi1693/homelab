---
title: Ryokan Batch Import Corruption Recovery
---

# Ryokan Batch Import Corruption Recovery

- **Service:** qBittorrent, Ryokan, Smart Queues, Shoko, and Jellyfin
- **Type:** Break-glass media recovery
- **Last verified:** 2026-08-16 against Ryokan 1.8.5 and Smart Queues 0.1.84
- **Owner:** Home lab operator
- **Estimated time:** 20-45 minutes plus torrent download and Shoko hashing time

## Meaning

Use this runbook when a multi-file anime torrent is complete but Ryokan's
receipt, the qBittorrent selection, and the completed library do not describe
the same episode set. Typical symptoms include:

- Ryokan marks a batch imported while the library contains fewer videos;
- source episode numbers are moved onto different destination episode numbers;
- a partial recovery download overwrites older library episodes;
- Smart Queues retains or rechecks a completed torrent because reconciliation
  cannot prove one destination for every selected source; or
- Jellyfin/Shokofin shows episodes that are absent, stale, or mapped to the
  wrong underlying video.

The recovery invariant is strict: every selected source video needs one unique
completed-library destination with the intended episode number and the same
byte size. A Ryokan `imported` state, a completed qBittorrent progress value,
or a Jellyfin item is not sufficient evidence by itself.

Smart Queues 0.1.84 refuses automatic requeue when Ryokan's grabbed episode
count differs from qBittorrent's selected media count. Treat that result as an
identity boundary and continue only with manifested operator recovery.

## Impact

Ryokan uses move mode. A bad batch mapping can therefore replace an existing
library file and remove the only source copy from `/downloads`. Requeuing the
same partial batch can repeat the overwrite with a different subset.

Smart Queues normally cleans up only the Ryokan categories `anime` and
`priority-anime`. A recovery torrent must use a different category and an
isolated save path so neither Ryokan nor the automated cleanup path can process
it.

Shoko and Jellyfin are downstream metadata/indexing systems. Their databases or
virtual paths can remain stale after the physical file has been moved or
overwritten; they do not provide a backup of the media payload.

This runbook includes live qBittorrent, filesystem, and SQLite mutations. Use
it only with explicit break-glass authorization. The normal cluster-change
policy remains GitOps-only.

## Diagnosis

### 1. Confirm workloads and mounts

```bash
kubectl -n media get deployment ryokan qbittorrent-smart-queues shoko jellyfin
kubectl -n media get pods \
  -l 'app.kubernetes.io/name in (ryokan,qbittorrent-smart-queues,shoko,jellyfin)' \
  -o wide
kubectl -n media get pvc media-downloads-unas media-library-unas
```

Stop if either storage claim is not Bound or the Ryokan pod cannot see both
`/downloads` and `/media/anime`. Resolve storage before changing media state.

### 2. Identify one exact torrent and grab

Record the exact torrent hash, title, Ryokan grab ID, series ID, library folder,
and expected episode set. Do not use a title substring when multiple torrents
or grabs can match.

Inspect without printing credentials:

```bash
kubectl -n media logs deployment/qbittorrent-smart-queues --since=24h \
  | grep -Ei 'Ryokan|reconcil|import|completed'

kubectl -n media logs deployment/ryokan -c ryokan --since=24h \
  | grep -Ei 'Imported|Orphan upgrade|Replacing|post_process'
```

In qBittorrent, record for the exact hash:

- state, progress, save path, category, and completion time;
- every selected file's index, relative path, size, priority, and progress;
- the selected media count and total selected bytes; and
- current seed count and availability.

Do not trust torrent-level `progress=1` when selected source files are absent.
qBittorrent fast-resume data can remain complete until an exact recheck.

### 3. Compare receipts with physical files

Read `/data/ryokan.db` from the `import-reconciler` sidecar. Inspect only the
target hash in `grabbed_torrents`, the matching rows in
`episode_grab_history`, and the series metadata. Do not print download-client
credentials.

For the exact series directory, count videos and collect each filename and byte
size. Compare that inventory with the selected qBittorrent files. Unique byte
sizes are useful evidence, but episode numbers must also be parsed from the
source and destination names.

Classify the result:

| Result | Meaning | Action |
| --- | --- | --- |
| Counts, episode numbers, paths, and sizes all match | Import is valid | Allow normal reconciliation and cleanup. |
| Source receipt matches but destination count or episode mapping differs | Corrupt import | Quarantine the torrent; do not requeue it through Ryokan. |
| Selected source still exists in `/downloads` | Import is incomplete | Keep the torrent and investigate Ryokan logs before any move. |
| Source is gone and no same-size destination exists | Payload is lost from the library | Recover from the original torrent or backup. |
| Shoko/Jellyfin shows an item whose physical file is absent | Stale downstream metadata | Recover the file first, then rescan Shoko/Jellyfin. |

## Mitigation

### 1. Contain the torrent before changing anything

If the corrupt hash is actively being post-processed, first verify its
`.torrent` backup and capture the exact selected-file manifest. Then remove only
that qBittorrent record with `deleteFiles=false`. This immediately breaks the
repeated Ryokan processing loop while retaining the payload. Verify the content
directory remains and that no newer import event appears for the hash before
continuing.

Removing the qBittorrent record does not cancel a file move already executing
inside Ryokan. If another import or replacement event appears afterward, scale
Ryokan to zero under break glass, wait for the old pod to terminate, verify the
source-file count is stable, and restore one replica only after the hash is
absent. Confirm the replacement pod marks the exact grab removed.

Create a dedicated qBittorrent category such as `series-recovery` with an
isolated save path such as `/downloads/recovery/series-slug`.

Before using it, verify all of the following:

1. Ryokan's qBittorrent `label` in `download_clients` is different. The normal
   label is `anime`.
2. The category is not listed in
   `QBT_RYOKAN_IMPORTED_ANIME_CATEGORIES`; the normal cleanup categories are
   `anime` and `priority-anime`.
3. The isolated save path is not the existing stale source path.
4. The Ryokan grab remains closed (`imported` or another non-pending state).

Force-start is a deliberate manual override in this stack. Smart Queues leaves
force-started torrents running. Keep the recovery torrent force-started until
manual recovery is complete.

Do not set a corrupt partial batch back to `pending`. Do not let Ryokan run its
post-processor against the recovery category.

### 2. Preserve recovery artifacts

Before removing or re-adding a torrent entry:

- export the exact `.torrent` metadata;
- take a consistent SQLite backup using SQLite's backup API, not a live file
  copy of `ryokan.db` alone;
- write a JSON manifest containing source path, intended destination path,
  episode number, file index, and byte size; and
- keep the old source directory until the recovery download and import are
  verified.

Store the artifacts under a timestamped `/data/recovery/<incident>/`
directory. They contain no credentials and must not be committed to Git.

If every torrent media file has a unique byte size, use that property to build
a read-only library-match manifest. Any library file whose unique size maps to
this batch but whose destination episode differs from the source episode is a
proven corrupt placement. Move such files into a hidden quarantine on the same
library filesystem so the operation is atomic and the media scanner cannot
serve them. Keep the move manifest; never delete or relocate files whose match
is ambiguous.

### 3. Start a clean recovery download

If qBittorrent resumes a large stale hash check, use the exported `.torrent`
to create a fresh job:

1. Remove only the old qBittorrent entry with `deleteFiles=false`.
2. Re-add the preserved `.torrent` stopped, in the recovery category, with the
   isolated recovery save path.
3. Deselect every file.
4. Select only the exact missing episode files and set them high priority.
5. Start and force-start the torrent.

The qBittorrent add endpoint may return either `Ok.` or a JSON success object
with the added torrent ID. Accept either only when `failure_count` is zero and
the returned ID is the expected hash.

Verify immediately:

- the category and save path are the recovery values;
- the selected file count equals the missing episode count;
- selected bytes equal the expected missing payload size;
- state is `forcedDL` or another active download state;
- `amount_left` is nonzero and decreases; and
- peers, seeders, or availability show that recovery is possible.

If the selected count differs, stop the torrent. Do not download an entire pack
to compensate for an unresolved episode map.

### 4. Import the recovery without Ryokan

After all selected files reach 100%, keep the torrent force-started and perform
a manual, manifested import:

1. Re-read the qBittorrent file list and verify every selected source exists at
   the isolated recovery path with the reported byte size.
2. Resolve the intended episode number from the source filename and verify it
   against `series_episode_metadata`.
3. Refuse any duplicate episode, ambiguous parse, missing title metadata,
   existing destination, or size mismatch.
4. Stage all files in a temporary directory on the same library filesystem.
5. Move staged files to their final episode filenames only after every source
   and destination passes validation.
6. In one SQLite transaction, supersede false completed history rows, insert
   one completed history row per recovered file, update the corresponding
   quality tag, and keep genuinely missing episodes absent from completed
   state.

On this live WAL database, a broad predicate update can return SQLite
`disk I/O error` even when the same exact rows update successfully by primary
key. If that occurs, roll back, checkpoint the WAL with
`PRAGMA wal_checkpoint(PASSIVE)`, select the exact row IDs read-only, and update
those IDs individually in one transaction. Never disable journaling or copy a
live database over its WAL files.

Do not remove the recovery torrent until the reconciler independently proves:

- source receipt count equals selected source count;
- destination count and distinct episode count equal selected source count;
- every destination exists;
- source and destination sizes match; and
- `delete_allowed=true`.

### 5. Refresh downstream metadata

Trigger a Shoko scan of `/media/anime`, wait for hashing and matching to finish,
then trigger Jellyfin `/Library/Refresh`. Verify Jellyfin through the Shokofin
series, not only by checking the direct NAS filename.

Shoko virtual paths can outlive a deleted source file. Confirm that sampled
episodes are playable and that their physical source paths exist before
calling the recovery complete.

## Verification

The incident is complete only when all of these are true:

- qBittorrent selected-file count and bytes match the intended recovery set;
- every recovered source has one exact destination with the same byte size;
- no older episode was overwritten to make room for a newer one;
- `PRAGMA quick_check` returns `ok` for `ryokan.db`;
- the Ryokan receipt contains the exact recovered episode and source counts;
- the reconciler returns `complete` with `delete_allowed=true`;
- Shoko finishes hashing/matching the changed files; and
- Jellyfin/Shokofin exposes and plays representative early, middle, and final
  recovered episodes.

Keep the database backup, torrent export, and move manifest until this full
verification has passed.

## Rollback

If a filesystem move is wrong, stop Ryokan processing and reverse only the
manifested moves. Validate file sizes after every reverse move.

If receipt changes are wrong, stop Ryokan before database restoration. Take a
second backup of the current database, restore the consistent pre-recovery
backup with its normal SQLite recovery procedure, and restart Ryokan. Never
replace `ryokan.db` while Ryokan or the reconciler is writing it.

If the qBittorrent job was removed incorrectly, re-add the exported `.torrent`
stopped in the recovery category. Reconstruct its selection from the manifest;
do not select all files by default.

## References

- [Ryokan application notes](../../../kubernetes/projects/entertainment/apps/media-ryokan/README.md)
- [qBittorrent Smart Queues notes](../../../kubernetes/projects/entertainment/apps/media-qbittorrent/README.md)
- [Anime library relocation and Shoko recovery](anime-library-relocation-and-shoko-recovery.md)
