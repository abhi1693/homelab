# Prowlarr

This bundle installs Prowlarr through a Fleet `HelmOp` for media indexer
management.

Runs continuously with one replica managed by Git/Fleet. Configuration, queues
and media remain on their existing persistent storage.

## Runtime Shape

- Namespace: `media`
- Chart: TrueCharts `prowlarr`
- Release: `prowlarr`
- Internal URL: `http://prowlarr.media.home`
- Ingress class: `traefik`
- Image: Harbor proxy path for `oci.trueforge.org/containerforge/prowlarr`, pinned in `values.yaml`

Fleet orders Prowlarr after FlareSolverr because indexer configuration can use
the FlareSolverr service for browser-challenge handling.

CPU requests are `100m`, with no CPU limit (`resources.limits.cpu: 0` disables
the TrueCharts default). Indexer work may burst above the request.
Resource changes roll the singleton; deploy through Fleet in a quiet window.

## Storage

Prowlarr uses a retained 512 MiB Longhorn config PVC. The manifest preserves the
bound volume ID so Fleet expands the existing claim instead of attempting to
replace it. Prowlarr does not mount the shared media library or downloads PVCs.

## Network Boundary

Ingress is allowed from Traefik, Sonarr, Radarr, Ryokan, and qBittorrent on port
`9696`. The qBittorrent path is required because submitted download URLs point
back to Prowlarr. Egress allows DNS, FlareSolverr on port `8191`, Sonarr,
Radarr, qBittorrent, and external index/API traffic outside the pod and service
CIDRs.

Allowed Hosts is pinned through `PROWLARR__SERVER__ALLOWEDHOSTS` to
`prowlarr.media.home` and the short and fully qualified Kubernetes service names.
This validates the HTTP Host header; it does not filter client source networks.
Clients on the Default VLAN (`192.168.1.0/24`) continue to use
`http://prowlarr.media.home` through the existing ingress VIP and inter-VLAN
routing. Loopback hosts remain accepted by Prowlarr, and rendered HTTP probes
explicitly send `Host: localhost`. Verify ingress access from the Default VLAN,
internal Arr access, and rejection of an unrelated Host header after changes.

## Operating Notes

- Keep indexer credentials and app API keys out of Git.
- Prowlarr reads its API key from the encrypted
  `media-jellyfin-arr-api-keys` Secret. Rotate that value and bump
  `home-lab.io/api-key-revision` in `values.yaml`; Fleet restarts Prowlarr and
  the Ryokan startup reconciler updates its configured endpoints.
- After rotating Arr credentials, update Prowlarr's Sonarr/Radarr application
  connections and force a full application/indexer sync. A normal sync can
  complete without repairing stale credentials. Verify actual searches and
  download handoff using the
  [download recovery runbook](../../../../../docs/runbooks/media-download-recovery.md).
- Use Prowlarr as the normal source of truth for Sonarr and Radarr indexers.
- Indexers that need the configured FlareSolverr proxy must carry its
  `flaresolverr` tag. Uindex was tested successfully and tagged on 2026-10-28
  after direct requests were blocked by Cloudflare; retain its Sonarr/Radarr
  synchronization tags. This application setting persists in its config PVC.
- Ryokan manages anime indexers directly; do not configure a separate Sonarr
  Anime application in Prowlarr.
- Change chart configuration in `values.yaml` and let Fleet reconcile.

## Internet Archive client compatibility

`custom-definitions-values.yaml` preserves the upstream v11 Internet Archive
definition's canonical URL, search parameters, parser and capabilities, with a
`Mozilla/5.0` User-Agent. Repeated alternating requests from the same pod and
upstream IP returned HTTP 200 in about one second with this header; the default
Prowlarr User-Agent timed out or returned HTTP 429. The upstream file and blob
revision are recorded in the values file for future comparison.

Keep generated values files beside `kustomization.yaml` and reference their
filenames directly. Fleet's virtual post-render filesystem rejects nested or
aliased generator inputs even when local filesystem Kustomize rendering passes.

The chart renders this public definition into ConfigMap
`prowlarr-custom-indexers` and mounts its single file read-only at
`/config/Definitions/Custom/internetarchive-client.yml`. Other custom definitions
and the retained config PVC are preserved. Helm's ConfigMap checksum rolls the
pod when the definition changes. Cardigann's Go expressions are escaped for the
chart's single Helm template pass; inspect the rendered ConfigMap when editing.

After Fleet makes the definition available, preserve the existing Internet
Archive indexer's ID, name, tags, profile and priorities while setting its
`definitionFile` field to `internetarchive-client` through the application API.
Run its non-saving connection test, then verify an actual search and Arr sync.
Keep the previous API configuration in a private backup. The definition uses a
unique file ID and display name so Prowlarr's normal definition updates do not
replace it; periodically compare it with the upstream definition.

For rollback, restore the existing indexer's `definitionFile` to
`internetarchive` before removing the custom definition's values and mount
through Git. This change keeps the current Prowlarr image and database schema.

## CPU reservation

CPU request is 100m; indexer work retains its uncapped CPU burst policy.

## 2026-11-13 replica recovery

The config volume retained a failed replica address in its engine after
Longhorn removed the failed replica object. Two healthy copies remained, but
new replicas were not admitted and snapshot purge failed on the missing
replica. Prowlarr was paused through Fleet for a normal CSI detach
and Longhorn engine shutdown. No volume, replica, finalizer, or backup target
is manually changed. The stale engine reached stopped with no node assignment and no attachment
tickets after temporarily disabling offline rebuilding. Prowlarr resumes at
one replica. Verify SQLite state, indexer integration, and the
three-writable-replica target independently.
