---
title: MeTube
---

# MeTube

Fleet deploys MeTube as the browser front end for `yt-dlp`. Downloads are
written directly into the NAS-backed Jellyfin media PVC under `/media/youtube`,
which appears inside the MeTube container as `/downloads`.

## URL

- `http://youtube.media.home`

The Ingress uses the shared `media-edge-basic-auth` Traefik middleware from the
`media-storage` bundle because MeTube can download arbitrary URLs and delete
completed files when the trash action is used.

## Jellyfin Wiring

The Jellyfin image bakes in the YouTube Metadata plugin. Add a Jellyfin library
pointing at `/media/youtube/videos` after this bundle reconciles, then enable
the `YouTube Metadata` local provider for that library. The MeTube filename
templates include the source video ID in square brackets and the global
`yt-dlp` options write matching `.info.json` and thumbnail files, which is the
format expected by the plugin.

Audio-only downloads go to `/media/youtube/audio`. Add that as a separate
Jellyfin music or music-video library if you want audio downloads visible in
Jellyfin.

## Storage

- `media-library-nas`: mounted at `/downloads` with `subPath: youtube`.
- `metube-state`: small Longhorn PVC for queue, subscription, and completed
  download state.
- `/tmp`: pod-local scratch space for in-progress downloads.

## yt-dlp Defaults

The `metube` ConfigMap enables `writeinfojson`, `writethumbnail`, and
FFmpeg metadata post-processing globally. Optional UI presets are available for
English subtitle embedding and SponsorBlock chapter removal.
