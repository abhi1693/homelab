---
title: Completed Torrent Import Recovery
---

# Completed Torrent Import Recovery

- **Service:** qBittorrent, Sonarr, Radarr, Ryokan, and Smart Queues
- **Type:** Media import diagnosis and break-glass recovery
- **Last verified:** Sonarr pack-title recovery on 2026-08-19 against Sonarr
  4.0.19.2997 and Smart Queues 0.1.85; Radarr and Ryokan classification paths
  on 2026-08-16 against Radarr 6.4 and Ryokan 1.8.5
- **Owner:** Home lab operator

## Meaning

Use this runbook when qBittorrent reports a completed torrent but its payload
has not reached the completed media library. Completion proves only that the
download client has the selected bytes. It does not prove that an importer
matched the release, accepted its quality, moved every file, or recorded the
result.

Classify each exact torrent hash before changing anything:

| Arr or Ryokan evidence | Meaning | Normal action |
| --- | --- | --- |
| Remaining files have unambiguous episode or movie mappings and no import rejections | Recoverable import | Use the importer's manual or interactive import. |
| Movie is known from grab history but the file parser reports `Unknown Movie` | Recoverable identity failure | Assign the known movie during Radarr manual import. |
| A multi-episode pack imported only the episode encoded in the release title | Recoverable pack-title mismatch | Map each remaining file to its exact Sonarr episode. |
| `Not a Custom Format upgrade` or `Not an upgrade` and an existing library file is verified | Intentional rejection | Remove and normally blocklist the inferior release. |
| Ryokan source episodes map to different destination identities or overwrite older episodes | Corrupt import | Quarantine immediately; preserve payload and metadata. |
| Source is absent and there is no distinct, same-size destination receipt | Possible payload loss | Recover from the torrent or backup; do not clean up. |

## Impact

A safe cleanup releases download storage and prevents an inferior copy from
being grabbed again. An unsafe cleanup can delete the only remaining payload.
Ryokan uses move mode, so a bad batch identity can also overwrite a valid older
episode while removing the newly downloaded source.

Do not infer safety from `progress=1`, an Arr queue state, a Ryokan
`state=imported` value, or a downstream Jellyfin item alone. Destructive live
actions in this runbook require explicit break-glass authorization.

Prefer a two-phase recovery for valid media: copy into the library, prove the
import, and only then delete the exact download-client payload. Move mode
combines recovery and source deletion into one operation and removes the safest
rollback point.

## Diagnosis

### 1. Inventory exact completed hashes

Record the qBittorrent hash, name, category, content path, selected file list,
file sizes, per-file progress, and total selected bytes. Keep each hash separate;
do not act on a title substring.

```bash
kubectl -n media get deployment sonarr radarr ryokan qbittorrent \
  qbittorrent-smart-queues
kubectl -n media get pvc media-downloads-unas media-library-unas
kubectl -n media logs deployment/qbittorrent-smart-queues --since=24h \
  | grep -Ei 'import|already imported|not.*upgrade|Ryokan|reconcil'
```

Stop if either storage claim is not Bound or if the importer cannot see both
`/downloads` and its completed-library root.

### 2. Correlate the download with its owner

For TV and movies, inspect Sonarr or Radarr Activity -> Queue and History. Record:

- queue ID and exact download ID/hash;
- series, episode, or movie ID;
- tracked download state;
- every status message; and
- the current library file ID, path, size, quality, and custom formats, if one
  exists.

Do not dump complete Arr history records. A history record can contain a
download URL with an embedded indexer or Prowlarr API key. Whitelist only the
fields needed for the incident, and never print or persist credential values.

For anime, inspect the exact hash in Ryokan's `grabbed_torrents`, its
`episode_grab_history` rows, `imported_source_paths`, and the physical source
and destination files. Follow the dedicated corruption runbook when identities,
counts, or byte sizes differ.

### 3. Ask the importer to parse the remaining files

Open Wanted -> Manual Import in Sonarr or Movies -> Manual Import in Radarr and
select the exact torrent content directory. Do not submit the import yet.

For a Sonarr grabbed-release mismatch, candidate discovery must be independent
of the tracked download. Use the exact source folder and omit `downloadId`.
Activity -> Queue -> Manual Import may retain the bad grab association and
continue rejecting valid files. If the candidates still say that an episode was
not found in the grabbed release, stop: the request is still associated with the
tracked download.

A recoverable candidate must have:

- exactly one intended series/movie and the expected episode IDs;
- a plausible quality and language parse;
- no rejection other than Radarr's `Unknown Movie` when grab history proves the
  intended movie; and
- a source path and byte size that match qBittorrent.

If the candidate maps to the wrong title or episode, stop. Manual import is not
permission to guess.

### 4. Establish the recovery gate

Before importing, record an incident manifest containing:

- the exact torrent hash, name, category, content path, and total selected
  bytes;
- each selected media path, byte size, progress, and qBittorrent priority;
- the affected Arr series/movie ID and expected episode/movie IDs;
- the baseline library file IDs, paths, sizes, and quality values;
- the expected set of files to import; and
- free bytes on both the download and completed-library filesystems.

For a copy-mode import, the completed-library filesystem must have more free
space than the total bytes being recovered. Stop if any selected qBittorrent
file is incomplete, missing, unselected, or different from the candidate
reported by Arr.

## Mitigation

### Recover a Sonarr multi-episode pack

This commonly occurs when the release title says `S01E01-08` but Sonarr tracks
the grab as only `S01E01`. The first file imports automatically while the other
files report that their episodes were not in the grabbed release.

1. Confirm the already-imported episode and its destination file ID, path, and
   byte size.
2. Discover candidates from the exact source folder without a `downloadId`.
3. Select only missing episodes. Map every source file to exactly one expected
   episode and require zero rejections.
4. Reject the whole operation if an episode is duplicated, absent, ambiguous,
   already represented by a different library file, or has a source-size
   mismatch.
5. Choose **Copy**. Keep the qBittorrent torrent stopped and retain its payload
   until all verification gates pass.
6. Submit one import command and record its command ID. Large copies between
   the download and library NFS exports can take several minutes per file.
7. Poll the command until it is terminal. Success requires `status=completed`,
   no exception, and an imported-file count equal to the selected candidate
   count.
8. If the command fails or times out, inspect episode-file records and the
   destination filesystem before retrying. A command can fail after copying
   some files; blindly retrying can create replacements or duplicates.

#### API-assisted import

Use the API when the UI cannot detach the candidates from the stale tracked
download. Keep credentials inside the existing Smart Queues pod environment;
do not pass them on the command line or print them.

Discover candidates with a folder-only request:

```text
GET /api/v3/manualimport?folder=<url-encoded-source-directory>&filterExistingFiles=true
```

The request must not contain `downloadId`. For every selected response item,
require the expected series ID, exactly one expected episode ID, zero
rejections, and a path and byte size matching the exact qBittorrent file.

Submit a whitelisted command payload shaped like this:

```jsonc
{
  "name": "ManualImport",
  "importMode": "copy",
  "files": [
    {
      "path": "/downloads/<exact-folder>/<exact-file>.mkv",
      "seriesId": 123,
      "episodeIds": [456],
      "quality": { /* complete quality object from the candidate */ },
      "languages": [ /* complete language objects from the candidate */ ],
      "releaseGroup": "<candidate-release-group>",
      "indexerFlags": 0,
      "releaseType": "<candidate-release-type>"
    }
  ]
}
```

Send the payload to `POST /api/v3/command`. Deliberately omit `downloadId` from
every file. Copy `quality`, `languages`, `releaseGroup`, `indexerFlags`, and
`releaseType` from the live candidate; do not invent them or submit the entire
unfiltered response object. `POST /api/v3/manualimport` reprocesses candidate
metadata and is not the command that imports the files.

Poll `GET /api/v3/command/<command-id>` until the command completes. During a
large import, confirm that completed episodes acquire distinct episode-file IDs
one at a time. Do not treat a partially written destination file as a completed
import.

#### Cleanup after verified copy

Delete the download payload only after the verification section below passes:

1. Re-resolve one qBittorrent record by the exact 40-character hash. Recheck its
   name, content path, strict completion, and total bytes immediately before
   deletion.
2. Delete that exact hash with `deleteFiles=true`. Do not select by title, use a
   wildcard, or blocklist a valid release whose only fault was pack-title
   parsing.

   ```text
   POST /api/v2/torrents/delete
   hashes=<exact-40-character-hash>&deleteFiles=true
   ```

3. Poll qBittorrent until the exact hash is absent.
4. Wait for the exact source directory to disappear. The torrent record may be
   removed before asynchronous NFS payload deletion finishes; do not race it
   with `rm`.
5. Allow Sonarr one normal download-client refresh to clear cached queue rows.
   Do not delete queue rows merely because they remain for a few seconds after
   qBittorrent cleanup.
6. Re-run the complete library verification after the source path is absent.

### Recover a Radarr movie matched only by grab history

If the queue identifies a movie but Manual Import reports `Unknown Movie`:

1. Verify the queue download ID equals the torrent hash.
2. Verify the queue's movie ID, title, year, and configured destination.
3. Assign that exact movie to the manual-import candidate.
4. Preserve the parsed quality and language values.
5. Choose **Move** only when seeding is no longer required, then submit.
6. Verify Radarr created a movie-file record whose byte size equals the source.

### Clean a release that is not an upgrade

Treat `Not an upgrade` and `Not a Custom Format upgrade` as terminal only after
the existing media file is independently verified through Sonarr or Radarr.

1. Record the existing file ID, path, byte size, quality, and custom-format
   score.
2. Confirm the rejected release does not improve the accepted file.
3. Remove the exact queue record with **Remove from download client** enabled.
4. Blocklist an objectively inferior or mislabeled release so Arr can choose a
   different candidate; leave redownload enabled.
5. Confirm only the rejected hash and its download payload disappeared and the
   existing library file is unchanged.

Smart Queues 0.1.85 recognizes both legacy `Not an upgrade for existing ...`
messages and Radarr's `Not a Custom Format upgrade for existing ...` wording.
It still fails closed unless the corresponding existing Arr library file can be
verified.

### Contain a corrupt Ryokan batch

When logs show `Orphan upgrade`, `Replacing`, or source season/episode numbers
being written onto a different destination identity:

1. Export or verify the qBittorrent `.torrent` backup and record all selected
   source paths and byte sizes.
2. Remove only the exact qBittorrent record with `deleteFiles=false` to stop
   repeated post-processing while retaining the payload.
3. Verify the content directory remains on disk and no newer Ryokan import log
   appears for that hash.
4. If an in-flight worker completes another move after the client record is
   gone, scale Ryokan to zero under break glass, wait for the old pod to exit,
   confirm the source count is stable, and restore one replica only after the
   hash is absent. The replacement pod should mark the grab removed.
5. Do not set the grab back to `pending` and do not re-add it under `anime` or
   `priority-anime`.
6. Continue with the manifested recovery procedure in
   [Ryokan batch import corruption recovery](storage/ryokan-batch-import-corruption-recovery.md).

Smart Queues 0.1.85 fails closed when the qBittorrent-selected media count and
Ryokan's grabbed episode count differ. That mismatch requires this operator
workflow and must never trigger automatic requeue.

## Verification

The incident is complete only when:

- every recoverable source has one intended destination with the same byte size;
- Sonarr/Radarr records every expected episode or movie file;
- a Sonarr manual-import command is completed without an exception and its
  imported count matches the selected candidate count;
- every expected Sonarr episode has `hasFile=true`, a unique nonzero
  episode-file ID, and a recorded byte size equal to its source;
- the sum of recovered library bytes equals the sum of the selected recovery
  source bytes;
- imported and rejected torrent hashes are absent from qBittorrent;
- the cleaned torrent's exact source directory is absent after qBittorrent
  finishes payload deletion;
- stale Arr queue rows for the exact download ID disappear after a normal
  download-client refresh;
- the existing files used to justify rejection are unchanged;
- no completed torrent remains in an import-blocked or import-pending state;
- Ryokan emits no further import or replacement event for a quarantined hash;
- Smart Queues logs no repeated terminal rejection for the same hash; and
- fresh library scans expose and play representative imported files.

Do not remove preserved torrent metadata, database backups, or recovery
manifests until these checks pass.

`GET /api/v3/manualimport` can continue listing retained source files after a
successful copy. It is a source-folder browser, not authoritative proof that an
episode is missing. Use episode records, episode-file records, import history,
destination paths, and byte sizes for final verification.

## Rollback

Before cleanup, copy mode leaves the qBittorrent payload intact. If a mapping
was wrong, stop further processing, record the created file IDs and paths, and
use the Arr UI to remove only those exact records without deleting either copy
until the source/destination identity is reconstructed.

If a manual-import command fails, re-inventory the library before retrying.
Treat any file with a newly assigned episode-file ID as imported even when the
command reports failure, then recover only the still-missing set.

If a rejected torrent was removed incorrectly, re-add the preserved `.torrent`
stopped and point it at its original payload. Do not recheck or start it until
the expected file selection and save path have been verified.

After `deleteFiles=true` completes, the download copy is not recoverable from
qBittorrent. The verified Arr library file or a backup becomes the recovery
source. Do not delete a library file merely to recreate seeding state.

For Ryokan, never reverse files by pattern. Use only the saved manifest and the
dedicated recovery runbook.

## References

- [qBittorrent Smart Queues notes](../../kubernetes/projects/entertainment/apps/media-qbittorrent/README.md)
- [Sonarr application notes](../../kubernetes/projects/entertainment/apps/media-sonarr/README.md)
- [Radarr application notes](../../kubernetes/projects/entertainment/apps/media-radarr/README.md)
- [Ryokan batch import corruption recovery](storage/ryokan-batch-import-corruption-recovery.md)
- [Sonarr Manual Import API controller](https://github.com/Sonarr/Sonarr/blob/develop/src/Sonarr.Api.V3/ManualImport/ManualImportController.cs)
- [Sonarr tracked-download manual-import failure](https://github.com/Sonarr/Sonarr/issues/8649)
