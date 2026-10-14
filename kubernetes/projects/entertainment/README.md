# Entertainment Project

The Entertainment project owns the media stack. It combines upstream Helm
charts, raw Kubernetes manifests, shared storage, app network policy, and custom
automation into one Fleet-managed media domain.

Fleet tracks this project through the `home-lab-entertainment` GitRepo.

## Why This Project Exists

Media workloads have a different operational profile from public web apps:

- they share large storage volumes;
- they have long-running imports and background jobs;
- some services need LAN or peer-to-peer exposure;
- several apps depend on each other through API integrations;
- partial downloads must be kept away from completed libraries;
- ARM64 chart and image choices matter.

Keeping the media stack in its own Rancher project makes those assumptions
visible and keeps media-specific network and storage policies away from other
apps.

## App Catalog

| App | What it does | Key coupling |
| --- | --- | --- |
| `media-storage` | Owns the `media` namespace and the NAS-backed completed-library and downloads PVCs. | NFS CSI and existing NAS exports. |
| `media-qbittorrent` | Torrent client and smart queue automation. | LoadBalancer peer port, downloads PVC, state snapshots, tracker refresh, rack automation. |
| `media-prowlarr` | Indexer manager. | qBittorrent, Sonarr, Radarr, FlareSolverr. |
| `media-sonarr` | TV library automation. | Prowlarr, qBittorrent, completed media PVC. |
| `media-radarr` | Movie library automation. | Prowlarr, qBittorrent, completed media PVC. |
| `media-episeerr` | Season-ahead TV download automation. | Sonarr delay tags and webhook, Jellyseerr request tags, Jellyfin playback events. |
| `media-ryokan` | Anime request/import workflow. | qBittorrent anime category, NAS anime library, direct public-indexer HTTPS egress. |
| `media-shoko` | Anime metadata and library management. | NAS anime library, Jellyfin/Shokofin workflow. |
| `media-jellyfin` | Media server. | NAS media library, custom image, PostgreSQL experiment, shared metadata PVCs. |
| `media-jellyseerr` | Media request portal. | Jellyfin and media app APIs. |
| `media-flaresolverr` | Browser challenge helper for indexers. | Prowlarr indexer proxy. |
| `media-helm-repositories` | Registers Helm repositories for media charts. | Rancher ClusterRepo. |

## Storage Flow

Downloads and completed media are intentionally separate.

```mermaid
flowchart LR
  qbittorrent["qBittorrent"]
  downloads["NAS downloads NFS CSI PVC"]
  importers["Sonarr / Radarr / Ryokan"]
  library["NAS media library"]
  jellyfin["Jellyfin"]

  qbittorrent --> downloads
  downloads --> importers
  importers --> library
  library --> jellyfin
```

This avoids Jellyfin scanning partial downloads and keeps the final media
library on the UNAS-backed `media-library-unas` NFS CSI claim. Sonarr, Radarr,
and Ryokan import completed downloads into the final library. Jellyfin and
metadata tools read from the completed library. The old
`media-library-nfs-csi` claim remains retained and unmounted as rollback.

The retired music applications' old `music/Lidarr`, `music/Aurral`, and
`downloads/slskd` directories remain operator-owned data on NFS.

## Traffic Flow

- Browser UIs use Traefik ingress on internal hostnames such as
  `sonarr.media.home`, `radarr.media.home`, and
  `watch.media.home`.
- qBittorrent requests the fixed MetalLB Layer 2 VIP `192.168.3.16` for torrent
  peer traffic.
- Media apps communicate east-west through ClusterIP services.
- Jellyseerr tags new standard-TV requests and reports the requested season to
  Episeerr; Sonarr delays the initial grab until Episeerr limits monitoring to
  that complete season, and Jellyfin playback advances the next season
  automatically.
- Network policies limit ingress to Traefik, monitoring, and approved app
  peers.
- Indexer traffic goes direct by default, with FlareSolverr retained only for
  indexers that need browser-challenge handling.
- Ryokan uses direct public HTTPS for Nyaa and other external metadata/search
  endpoints.

## Operating Notes

- Keep credentials and app API keys out of Git.
- Keep Prowlarr as the indexer source of truth for normal TV/movie apps.
- Keep completed libraries and download scratch space separate.
- Treat qBittorrent LoadBalancer exposure as a deliberate exception to the
  normal HTTP ingress model.
- Use the app-level README files for detailed wiring and first-run steps.
