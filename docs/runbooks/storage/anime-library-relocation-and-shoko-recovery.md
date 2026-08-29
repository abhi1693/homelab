---
title: Anime Library Relocation and Shoko Recovery
---

# Anime Library Relocation and Shoko Recovery

- **Service:** NAS media library, Radarr, Sonarr, Ryokan, Shoko, and Jellyfin
- **Type:** Maintenance and metadata recovery
- **Last verified:** 2026-07-21 against the live media stack and Shoko Server 5.3.3
- **Owner:** Home lab operator
- **Estimated time:** 10-30 minutes plus Shoko hashing time

## Meaning

Use this runbook when anime is physically stored below `/media/movies` or
`/media/tv`, or when a title moved to `/media/anime` appears in Shoko as an
unrecognized file. Also use it when Ryokan reports a monitored episode as
missing even though its video file is present in the title directory.

The same NAS export is mounted differently by each workload:

| Workload | Movies | TV | Anime | Access |
| --- | --- | --- | --- | --- |
| Radarr and Sonarr | `/data/movies` | `/data/tv` | `/data/anime` | Read/write |
| Ryokan | Not used | Not used | `/media/anime` | Read/write |
| Shoko | Not mounted | Not mounted | `/media/anime` | Read-only |
| Jellyfin | `/media/movies` | `/media/tv` | `/media/anime` | Read/write mount |

Shoko hashes files and matches those hashes against AniDB. A correctly moved
file can therefore still be unrecognized when its exact release hash is absent
from AniDB. Moving or renaming the file again does not fix that case; create a
manual episode link instead.

## Impact

- A directory move changes the shared NAS library immediately for every media
  workload.
- Moving a title without updating its owning application can make Radarr or
  Sonarr mark it missing and download it again.
- Shoko hashing is read-only but can consume CPU and take several minutes.
- A wrong manual link gives Jellyfin/Shokofin incorrect metadata until the link
  is removed.

Do not run the move while Radarr, Sonarr, or Ryokan is importing the same title.
Do not move anything from `/downloads`; only completed top-level library
directories are in scope.

## Prerequisites

- `kubectl` access to the home cluster and the `media` namespace.
- Browser access to Radarr, Sonarr, Ryokan, Shoko, and Jellyfin.
- Use `http://requests.anime.media.home` for the Ryokan UI. The retired
  `ryokan.media.home` hostname is not part of the supported workflow.
- `jq` and `curl` only when using the optional Shoko API fallback.
- The exact source directory and verified AniDB title or anime ID.
- No active import, rename, upgrade, or download for the title being moved.

The normal procedure does not change Kubernetes resources. Do not use
`kubectl apply`, `kubectl scale`, or another live-cluster mutation as part of
this runbook.

## Diagnosis

### 1. Confirm storage and mounts

```bash
kubectl -n media get pvc media-library-unas \
  -o custom-columns='NAME:.metadata.name,STATUS:.status.phase,VOLUME:.spec.volumeName'

kubectl -n media get deployment radarr sonarr ryokan shoko \
  -o custom-columns='NAME:.metadata.name,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas'
```

Expected state:

- `media-library-unas` is `Bound`;
- Radarr, Sonarr, Ryokan, and Shoko each have one Ready replica.

If the PVC is not Bound or a workload cannot mount it, stop. This is a storage
incident, not a title-relocation problem.

### 2. Inventory candidate directories without changing them

```bash
kubectl -n media exec deployment/radarr -c radarr -- sh -c '
  find /data/movies /data/tv \
    -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null \
    | sort
'
```

Expected output is one directory per title. This list is only a candidate
inventory; animation, Japanese audio, or a familiar title is not sufficient
proof that an item belongs in the anime library.

For every candidate, confirm all of the following before moving it:

1. The title has an AniDB entry, or its metadata clearly identifies it as
   anime.
2. Radarr, Sonarr, or Ryokan is not currently importing or renaming it.
3. `/data/anime/<title-directory>` does not already contain another copy.
4. The source is a completed library directory under `/data/movies` or
   `/data/tv`, not a download directory.

### 3. Determine the current owner

- If the movie exists in Radarr, use **Managed anime movie** below.
- If a TV series exists in Sonarr, use **Sonarr-to-anime handoff** below.
- If neither application owns it, use **Guarded direct move** below.

Do not directly move a Radarr-managed movie first. Radarr would retain its old
path and may treat the movie as missing.

### 4. Distinguish an absent file from a Ryokan parse miss

Ryokan's red **Missing** state does not by itself prove that the NAS file is
absent. Set the exact top-level anime directory name shown in Ryokan, then
inventory it through Radarr's writable view of the same NAS export:

```bash
title_directory='REPLACE_WITH_EXACT_DIRECTORY'

kubectl -n media exec deployment/radarr -c radarr -- sh -eu -c '
  title_directory=$1
  case "$title_directory" in
    ""|.|..|*/*) echo "Refusing a non-top-level directory" >&2; exit 1 ;;
  esac

  directory="/data/anime/$title_directory"
  test -d "$directory" || {
    echo "TITLE_DIRECTORY_ABSENT path=$directory"
    exit 2
  }

  find "$directory" -maxdepth 1 -type f -exec stat \
    -c "FILE name=%n bytes=%s modified=%y" {} \;
' sh "$title_directory"
```

Interpret the result before taking action:

| Result | Meaning | Next action |
| --- | --- | --- |
| `TITLE_DIRECTORY_ABSENT` or no video file | The payload is actually missing from `/data/anime` | Do not rename anything. Check the old Movies/TV root, download history, and owning application. |
| One video exists, Ryokan shows `0 / 1`, and the filename has no episode token | Likely single-episode filename parse miss | Use **Make single-episode movies visible to Ryokan** below. |
| A video exists and already has the correct episode token | The path, AniList association, or episode count is wrong | Stop; verify the Ryokan title path and AniList entry. Do not keep adding tokens. |
| More than one video exists | It may be a multi-episode title or duplicate payload | Stop and map each file to an episode before renaming anything. |

The Shoko `GET WebUI/LatestVersion` HTTP 500 banner is a separate update-check
failure. It is not evidence that this inventory or Shoko file matching failed.

## Mitigation

### Managed anime movie: let Radarr move it

Radarr remains the owner of anime movies, but their root folder must be
`/data/anime`.

1. Open `http://radarr.media.home`.
2. Open the movie and choose **Edit**.
3. Change **Root Folder** from `/data/movies` to `/data/anime`.
4. Choose **Yes, Move the Files** when Radarr asks whether to move them.
5. Save and wait for the move task to finish in **System -> Tasks** or
   **Activity -> History**.

Expected state: Radarr shows the movie path below `/data/anime`, the old
directory is absent, and the movie still has its file.

If Radarr reports that the destination already exists, stop and compare the
two directories. Never merge them blindly.

### Sonarr-to-anime handoff

This stack assigns normal TV to Sonarr and anime TV downloads to Ryokan.

1. In `http://sonarr.media.home`, open the series and set monitoring to
   **Unmonitored** so Sonarr cannot replace files during the handoff.
2. Confirm the series is not present in Sonarr's activity queue.
3. Remove the series from Sonarr with **Delete series folder disabled**.
4. Perform the guarded direct move below.
5. Confirm Ryokan still uses `/media/anime` as its media root and that future
   requests for the title are owned by Ryokan, not Sonarr.

If removing the Sonarr record would lose settings that are still needed, stop
and keep the title unmonitored until its intended owner is clear.

### Guarded direct move

Set these two variables to one exact top-level directory. Keep the directory
name unchanged unless a deliberate rename is part of the maintenance.

```bash
source_path='/data/movies/REPLACE_WITH_EXACT_DIRECTORY'
destination_path='/data/anime/REPLACE_WITH_EXACT_DIRECTORY'

printf 'SOURCE=%s\nDESTINATION=%s\n' "$source_path" "$destination_path"
```

For TV, the source must begin with `/data/tv/`. Review the printed paths before
continuing. Then run the guarded move:

```bash
kubectl -n media exec deployment/radarr -c radarr -- sh -eu -c '
  source_path=$1
  destination_path=$2

  case "$source_path" in
    /data/movies/*|/data/tv/*) ;;
    *) echo "Refusing source outside movies or tv" >&2; exit 1 ;;
  esac
  case "$destination_path" in
    /data/anime/*) ;;
    *) echo "Refusing destination outside anime" >&2; exit 1 ;;
  esac

  test -d "$source_path" || {
    echo "Source directory does not exist" >&2
    exit 1
  }
  test ! -e "$destination_path" || {
    echo "Destination already exists; refusing to merge" >&2
    exit 1
  }
  test "$(stat -c %d "$source_path")" = "$(stat -c %d /data/anime)" || {
    echo "Source and destination are not on the same filesystem" >&2
    exit 1
  }

  before_files=$(find "$source_path" -type f | wc -l)
  before_bytes=$(du -sb "$source_path" | awk "{print \\$1}")

  mv -- "$source_path" "$destination_path"

  after_files=$(find "$destination_path" -type f | wc -l)
  after_bytes=$(du -sb "$destination_path" | awk "{print \\$1}")
  test ! -e "$source_path"
  test "$before_files" = "$after_files"
  test "$before_bytes" = "$after_bytes"

  printf "MOVE_OK files=%s bytes=%s destination=%s\n" \
    "$after_files" "$after_bytes" "$destination_path"
' sh "$source_path" "$destination_path"
```

Expected output starts with `MOVE_OK`. Because all three library roots are on
the same NFS filesystem, `mv` changes directory metadata rather than copying
the media payload. Any refusal message means no move should have occurred.

### Make single-episode movies visible to Ryokan

Ryokan scans files as anime episodes. A Radarr movie filename without an
episode token can therefore exist on disk while Ryokan reports episode 1 as
missing. Keep the Radarr movie folder unchanged and add an explicit `- 01`
token to a confirmed single-episode AniList movie filename:

```text
Title (Year) {tmdb-ID} [quality].mkv
Title (Year) - 01 {tmdb-ID} [quality].mkv
```

Do not apply this convention to TV series, multi-episode OVAs, or a file whose
Ryokan/AniList entry has more than one episode.

First, validate that Radarr parses the proposed filename as the intended movie.
Use only an API key obtained from the Radarr UI; do not extract one from its
database or write it to Git:

```bash
read -rsp 'Radarr API key: ' radarr_api_key
printf '\n'
proposed_filename='REPLACE_WITH_PROPOSED_FILENAME'
expected_tmdb_id=REPLACE_WITH_NUMERIC_TMDB_ID

curl -fsS -G \
  -H "X-Api-Key: $radarr_api_key" \
  --data-urlencode "title=$proposed_filename" \
  'http://radarr.media.home/api/v3/parse' \
  | jq --argjson expected_tmdb_id "$expected_tmdb_id" \
      '{title: .movie.title, year: .movie.year,
        tmdbId: .movie.tmdbId, expectedTmdbId: $expected_tmdb_id,
        matches: (.movie.tmdbId == $expected_tmdb_id),
        quality: .parsedMovieInfo.quality.quality.name}'

unset radarr_api_key
```

Expected state: `matches` is `true`, and the title, year, and quality describe
the existing movie. If the response is empty, `matches` is false, or the API
returns an error, stop and leave the filename unchanged.

Set all three values to exact basenames. The new filename must differ only by
the deliberate episode token. This command refuses subdirectories, an absent
source, or an existing destination; records the old name, byte size,
modification time, and SHA-256 hash; and verifies that the rename preserved the
payload metadata:

```bash
title_directory='REPLACE_WITH_EXACT_DIRECTORY'
current_filename='REPLACE_WITH_CURRENT_FILENAME'
new_filename='REPLACE_WITH_FILENAME_CONTAINING_-_01'
repair_record=$(mktemp)

kubectl -n media exec deployment/radarr -c radarr -- sh -eu -c '
  title_directory=$1
  current_filename=$2
  new_filename=$3

  for value in "$title_directory" "$current_filename" "$new_filename"; do
    case "$value" in
      ""|.|..|*/*) echo "Refusing a non-basename value: $value" >&2; exit 1 ;;
    esac
  done

  directory="/data/anime/$title_directory"
  source_path="$directory/$current_filename"
  destination_path="$directory/$new_filename"
  test -f "$source_path"
  test ! -e "$destination_path" || {
    echo "Destination already exists; refusing to overwrite" >&2
    exit 1
  }

  before_bytes=$(stat -c %s "$source_path")
  before_mtime=$(stat -c %Y "$source_path")
  before_sha256=$(sha256sum "$source_path" | awk "{print \\$1}")

  mv -- "$source_path" "$destination_path"

  test ! -e "$source_path"
  test -f "$destination_path"
  test "$before_bytes" = "$(stat -c %s "$destination_path")"
  test "$before_mtime" = "$(stat -c %Y "$destination_path")"
  test "$before_sha256" = "$(sha256sum "$destination_path" | awk "{print \\$1}")"

  printf "RENAME_OK directory=%s old=%s new=%s bytes=%s mtime=%s sha256=%s\n" \
    "$directory" "$current_filename" "$new_filename" \
    "$before_bytes" "$before_mtime" "$before_sha256"
' sh "$title_directory" "$current_filename" "$new_filename" \
  | tee "$repair_record"
```

Expected output starts with `RENAME_OK`. Preserve the local path printed by
`printf '%s\n' "$repair_record"` until verification is complete. A failure
before `RENAME_OK` requires checking both exact paths; do not retry blindly.

In Radarr, open the movie and run **Refresh & Scan**. Wait for the
`RescanMovie` task to complete under **System -> Tasks**, then rescan Shoko's
`/media/anime` import folder using the next section. Refresh the title at
`http://requests.anime.media.home`, then refresh Jellyfin's Anime library.

Verify all of the following:

- Ryokan reports `hasFile: true` and the UI shows `1 / 1`;
- Radarr reports the new relative path and the original file size;
- Shoko retains the original ED2K hash, updates the location, and reports no
  new unrecognized file;
- Jellyfin/Shokofin still exposes the same Shoko file ID.

If any check fails, rename the file back using the recorded source name and
rescan Radarr and Shoko again.

The 2026-07-21 repair established these known-good payload baselines:

| Title | Bytes | Shoko ED2K after rename |
| --- | ---: | --- |
| *Naruto Shippuden the Movie: Blood Prison* | `951792580` | `94631C040B5740C30487CD3E313D97F3` |
| *Naruto the Movie: Ninja Clash in the Land of Snow* | `3841009934` | `52FEB55AD843F1F10D541A016F129E4A` |

These hashes prove that the verified renames did not rewrite the media. They
are reference values for these two payloads only, not identifiers to reuse for
other releases.

### Rescan Shoko

1. Open `http://anime.media.home`.
2. On **Dashboard -> Import Folders**, find `/media/anime` and select
   **Rescan Folder**. If that action is unavailable, use
   **Actions -> Import New Files**.
3. Wait for hashing and import jobs to finish.
4. Check **Dashboard -> Recently Imported** and **Unrecognized Files**.

Expected state: a hash known to AniDB appears under the correct series. If the
file remains under **Unrecognized Files**, continue to manual linking.

### Manually link an unrecognized file

Use a manual link for private encodes, remuxes, modified releases, or any file
whose hash AniDB does not know. Do not AVDump those files; AniDB does not accept
them.

1. In Shoko, open **Utilities -> Unrecognized**.
2. Select only files belonging to one AniDB series.
3. Choose **Manual Link**.
4. Search for the exact series title or its numeric AniDB anime ID.
5. Select the series and review Shoko's proposed file-to-episode match.
6. For a movie, normally select **Complete Movie**. For TV, select the exact
   episode number and type; do not assume filesystem season numbering matches
   AniDB.
7. Choose **Save** and wait for the manual-link job to finish.

Expected state: the file leaves **Unrecognized**, appears in
**Utilities -> Manually Linked**, and the dashboard unrecognized count drops.

The 2026-07-20 repair used these stable AniDB anime IDs:

- `1456`: *Naruto the Movie: Ninja Clash in the Land of Snow*;
- `8312`: *Naruto Shippuden the Movie: Blood Prison*.

Never reuse Shoko file, series, or episode IDs from another repair. Those IDs
are internal to the current Shoko database.

## Optional Shoko API fallback

Use this only when the WebUI manual-link workflow returns an error and the
server itself is otherwise healthy. The commands match Shoko Server 5.3.3;
check `http://anime.media.home/swagger` before using them after an upgrade.

Obtain a Shoko API key through the normal Shoko account/API-key workflow. Do
not extract tokens from the database, paste them into Git, enable shell tracing,
or include them in an incident log.

```bash
read -rsp 'Shoko API key: ' shoko_api_key
printf '\n'
shoko_api='http://anime.media.home/api/v3'
```

List the current unrecognized files and record the intended file ID:

```bash
curl -fsS -G \
  -H "apikey: $shoko_api_key" \
  --data-urlencode 'pageSize=200' \
  --data-urlencode 'include_only=Unrecognized' \
  "$shoko_api/File" \
  | jq '{Total, Files: [.List[] | {
      FileID: .ID,
      Path: .Locations[0].RelativePath,
      ED2K: .Hashes.ED2K
    }]}'
```

Set the exact AniDB anime ID, then ensure its series exists in Shoko:

```bash
anidb_id=REPLACE_WITH_ANIDB_ANIME_ID

curl -fsS -X POST \
  -H "apikey: $shoko_api_key" \
  "$shoko_api/Series/AniDB/$anidb_id/Refresh?force=true&createSeriesEntry=true&immediate=true"
```

Expected response is `true`. Read the Shoko series ID and list all episodes:

```bash
series_id=$(
  curl -fsS \
    -H "apikey: $shoko_api_key" \
    "$shoko_api/Series/AniDB/$anidb_id/Series" \
    | jq -er '.IDs.ID'
)

curl -fsS -G \
  -H "apikey: $shoko_api_key" \
  --data-urlencode 'pageSize=0' \
  --data-urlencode 'includeMissing=True' \
  "$shoko_api/Series/$series_id/Episode" \
  | jq '.List[] | {
      ShokoEpisodeID: .IDs.ID,
      AniDBEpisodeID: .IDs.AniDB,
      Type: .AniDB.Type,
      Number: .AniDB.EpisodeNumber,
      Title: .Name
    }'
```

Double-check the selected file and episode IDs, then create the link:

```bash
file_id=REPLACE_WITH_SHOKO_FILE_ID
episode_id=REPLACE_WITH_SHOKO_EPISODE_ID

jq -n --argjson episode_id "$episode_id" \
  '{EpisodeIDs: [$episode_id]}' \
  | curl -fsS -X POST \
      -H "apikey: $shoko_api_key" \
      -H 'Content-Type: application/json' \
      --data-binary @- \
      "$shoko_api/File/$file_id/Link"
```

HTTP 200 with no response body is normal. Confirm completion without exposing
the API key:

```bash
curl -fsS \
  -H "apikey: $shoko_api_key" \
  "$shoko_api/Dashboard/Stats" \
  | jq '{UnrecognizedFiles}'

kubectl -n media logs deployment/shoko --since=10m \
  | rg -i 'Manually Linking File|ManualLinkJob|Job Completed'

unset shoko_api_key
```

Expected state is the intended lower count and a completed manual-link job. A
nonzero count is valid when other unrelated files remain unrecognized.

## Verification

Verify the destination and absence of the old source path:

```bash
source_path='/data/movies/REPLACE_WITH_EXACT_DIRECTORY'
destination_path='/data/anime/REPLACE_WITH_EXACT_DIRECTORY'

kubectl -n media exec deployment/radarr -c radarr -- sh -eu -c '
  test ! -e "$1"
  test -d "$2"
  printf "files=%s\n" "$(find "$2" -type f | wc -l)"
  du -sh "$2"
' sh "$source_path" "$destination_path"
```

For a TV source, change `/data/movies/` to `/data/tv/`.

Complete all application-level checks:

- Radarr-managed anime movies show `/data/anime/...` and retain their files.
- Sonarr does not monitor a handed-off anime series at its old path.
- A repaired Ryokan single-episode title shows `1 / 1`, not `0 / 1`.
- Shoko no longer lists the repaired file as unrecognized.
- The Shoko series and episode mapping are correct.
- Jellyfin's Anime library shows the title after a library scan or the normal
  Shokofin refresh.
- No duplicate remains in the Movies or TV Jellyfin library.

The maintenance is complete only when both filesystem checks and user-facing
metadata checks pass.

## Rollback

### Roll back a guarded direct move

Set the paths to the reverse of the completed move. The old parent directory
must already exist, and the old title directory must remain absent.

```bash
current_path='/data/anime/REPLACE_WITH_EXACT_DIRECTORY'
original_path='/data/movies/REPLACE_WITH_EXACT_DIRECTORY'

kubectl -n media exec deployment/radarr -c radarr -- sh -eu -c '
  current_path=$1
  original_path=$2
  test -d "$current_path"
  test ! -e "$original_path"
  case "$current_path" in /data/anime/*) ;; *) exit 1 ;; esac
  case "$original_path" in /data/movies/*|/data/tv/*) ;; *) exit 1 ;; esac
  mv -- "$current_path" "$original_path"
  test -d "$original_path"
  test ! -e "$current_path"
  printf "ROLLBACK_OK destination=%s\n" "$original_path"
' sh "$current_path" "$original_path"
```

If Radarr performed the original move, change its root folder back through the
Radarr UI and choose **Move Files**. Do not move the directory behind Radarr's
back.

Restore the original Sonarr record only if the handoff was rolled back. Keep it
unmonitored until its files and path are confirmed.

### Roll back a single-episode filename repair

Use the `old` and `new` names in the saved `RENAME_OK` record. Reverse them
within the same title directory; do not move the file to another root:

```bash
title_directory='REPLACE_WITH_EXACT_DIRECTORY'
current_filename='REPLACE_WITH_REPAIRED_FILENAME'
original_filename='REPLACE_WITH_ORIGINAL_FILENAME'

kubectl -n media exec deployment/radarr -c radarr -- sh -eu -c '
  title_directory=$1
  current_filename=$2
  original_filename=$3

  for value in "$title_directory" "$current_filename" "$original_filename"; do
    case "$value" in
      ""|.|..|*/*) echo "Refusing a non-basename value: $value" >&2; exit 1 ;;
    esac
  done

  directory="/data/anime/$title_directory"
  current_path="$directory/$current_filename"
  original_path="$directory/$original_filename"
  test -f "$current_path"
  test ! -e "$original_path" || {
    echo "Original path already exists; refusing to overwrite" >&2
    exit 1
  }

  before_bytes=$(stat -c %s "$current_path")
  before_mtime=$(stat -c %Y "$current_path")
  mv -- "$current_path" "$original_path"
  test ! -e "$current_path"
  test -f "$original_path"
  test "$before_bytes" = "$(stat -c %s "$original_path")"
  test "$before_mtime" = "$(stat -c %Y "$original_path")"
  printf "RENAME_ROLLBACK_OK restored=%s bytes=%s mtime=%s\n" \
    "$original_path" "$before_bytes" "$before_mtime"
' sh "$title_directory" "$current_filename" "$original_filename"
```

Expected output starts with `RENAME_ROLLBACK_OK`. Run **Refresh & Scan** for
the movie in Radarr and rescan Shoko afterward. Confirm the file has its
original byte size and hash from the saved repair record. Ryokan will normally
return to `0 / 1`; that confirms the rollback restored the original parser
behavior.

### Remove an incorrect Shoko manual link

1. Open **Utilities -> Unrecognized -> Manually Linked**.
2. Select the series, then the incorrectly linked episode.
3. Choose **Unlink**.
4. Confirm the file returns to **Unrecognized**, then link it to the correct
   episode.

Unlinking changes Shoko metadata only; it does not move or delete the NAS file.

## Troubleshooting

| Symptom | Likely cause | Resolution |
| --- | --- | --- |
| `Destination already exists; refusing to merge` | Another copy or partially completed move exists | Compare file names, counts, sizes, and hashes. Keep both directories unchanged until the canonical copy is known. |
| Radarr or Sonarr shows the title as missing | The filesystem moved but the manager path did not | Stop monitoring to prevent a replacement download, then correct the root/path or roll back the move. |
| Ryokan shows `0 / 1` but a single movie file exists | The filename has no episode token, so Ryokan did not associate it with episode 1 | Confirm the AniList entry has exactly one episode, validate the proposed name through Radarr, then use the guarded `- 01` filename repair. |
| Ryokan still shows `0 / 1` after a guarded rename | Ryokan has not refreshed, the title points at another directory, or the association is wrong | Refresh the Ryokan title, compare its path with `/media/anime/<title-directory>`, and verify the AniList entry before changing the file again. |
| Ryokan posters are blurry or use AniList `/cover/small/` URLs | Full metadata hydration did not finish after an import, migration, or provider outage | Confirm the `ryokan-data` PVC has free space, then run **Maintenance actions -> Rebuild metadata cache** at `http://requests.anime.media.home/system`. Expect no failed titles. |
| Ryokan logs `database is locked`, `No space left on device`, or metadata rebuild failures | The `/data` PVC is full, preventing SQLite WAL and artwork-cache writes | Run `kubectl -n media exec deployment/ryokan -- df -h /data`. Expand the Fleet-managed PVC before retrying; do not delete the database, WAL, or artwork blobs manually. |
| Ryokan shows `qBittorrent Forbidden` | The qBittorrent API is reachable but Ryokan has blank or incorrect credentials | Set the download client's username and password from the `QBT_USER` and `QBT_PASSWORD` keys in `media-qbittorrent-cleanup`, then retest the connection. Never write those values to Git or logs. |
| Ryokan reports an AniList `MediaListCollection` request error | The Ryokan Pod cannot currently complete HTTPS requests to `graphql.anilist.co` | Verify Pod DNS/egress and retry after connectivity returns. Do not replace AniList IDs or artwork URLs based only on this transport error. |
| Shoko does not discover the file | `/media/anime` was not rescanned, the import folder is wrong, or the mount is inaccessible | Verify the Shoko import folder is `/media/anime`, rescan it, and check the Shoko Pod mount and logs. |
| File remains unrecognized after rescan | Its ED2K hash is absent from AniDB | Manually link it to the exact AniDB episode. Moving or renaming it again will not change the hash. |
| Dashboard shows `GET WebUI/LatestVersion` HTTP 500 | Shoko could not complete the independent WebUI-version check | Check Shoko logs and outbound connectivity separately. This error does not prove hashing or manual linking failed. |
| Manual-link search finds no series | Shoko does not yet hold that AniDB series | Search by numeric AniDB ID in the UI or use the API fallback to create and refresh the series entry. |
| Manual-link job returns HTTP 200 but the card remains | The job is asynchronous or the browser query is cached | Wait for `Job Completed` in Shoko logs, then refresh the dashboard and query `Dashboard/Stats`. |
| API endpoint returns 404 or rejects the payload | Shoko was upgraded and the v3 contract changed | Stop using the fallback and inspect the live `/swagger` document; do not guess endpoint changes. |

If the NAS move cannot be accounted for by an intact source or destination
directory, stop all import activity for that title and preserve both paths.
Escalate with the exact paths, timestamps, file counts, byte counts, and the
relevant Radarr/Sonarr/Shoko history. Do not start another move.

## Post-Procedure Checklist

- [ ] The source and destination were recorded.
- [ ] The owning application points at the new path or relinquished ownership.
- [ ] The old directory is absent and the destination file count is correct.
- [ ] Any filename-only repair retained the recorded byte size, modification
      time, and content hash.
- [ ] Ryokan reports files for present episodes and future anime requests are
      owned by Ryokan.
- [ ] Shoko recognizes the files or has verified manual links.
- [ ] Jellyfin displays the title only in the Anime library.
- [ ] Any new failure mode discovered during the repair is added to this
      runbook.

## References

- [Shoko: Unrecognized Files](https://docs.shokoanime.com/shoko-server/unrecognized-files)
- [Shoko: Dashboard and Import Folders](https://docs.shokoanime.com/shoko-server/dashboard)
- [Shoko: Actions](https://docs.shokoanime.com/shoko-server/actions)
- [Shoko app documentation](../../../kubernetes/projects/entertainment/apps/media-shoko/README.md)
- [Media storage documentation](../../../kubernetes/projects/entertainment/apps/media-storage/README.md)
- [Radarr app documentation](../../../kubernetes/projects/entertainment/apps/media-radarr/README.md)
- [Ryokan app documentation](../../../kubernetes/projects/entertainment/apps/media-ryokan/README.md)
