# qBittorrent

The qBittorrent Deployment and its state-backup CronJob are no longer pinned to
`k8s-rpi2`. They retain the ARM64 selector and, because they do not tolerate the
control-plane critical-addons taint, schedule on any available worker.

This bundle runs the qBittorrent client used by the media stack. qBittorrent
and the Smart Queues controller each run with one replica, and the maintenance
CronJobs are active. The HelmOp explicitly remains unpaused so Fleet
reconciles the one-replica desired state after an out-of-band pause.

The smart queues controller code lives in
`https://github.com/abhi1693/qbittorrent-smart-queues` and runs from the
`registry.home/ghcr.io/abhi1693/qbittorrent-smart-queues`
container image. Its Kubernetes runtime lives in this media qBittorrent bundle
and runs in the `media` namespace.

All media applications connect to the single in-cluster service at
`http://qbittorrent.media.svc.cluster.local:8080`. Category-specific routing is
handled inside qBittorrent rather than through separate workloads or Services.
qBittorrent can reach Prowlarr on TCP `9696` because Prowlarr download URLs are
submitted to qBittorrent for the client to fetch directly.

## Bandwidth policy

qBittorrent starts with a bounded global rate limit, so a pod restart
cannot temporarily consume the full WAN link before the management controller
reconciles it:

- `qbittorrent`: 64 MiB/s down, about 100 kbps up, and up to 7 active downloads
  and active torrents until the controller reconciles. This matches the five
  useful workers plus two parked stalled listeners. The configured upload and
  seeding sub-limit remains 8; qBittorrent stores the fallback upload bandwidth
  cap in KiB/s, so the persisted startup value is `12 KiB/s`.

The qBittorrent pod is allowed up to `2 GiB` of memory to absorb restore and
peer-reconnect bursts without OOM-killing the client and dropping active peers.

`qbittorrent-smart-queues` also enforces runtime limits. The primary ISP link is
currently a static-IP 1 Gbps service with a `3 TB` monthly high-speed allowance,
then `300 Mbps` service after that allowance. For the 2026-08 temporary policy,
the controller keeps the uncapped download window active all day, raises the
download ceiling to `100 MiB/s`, allows up to 5 useful download workers, and
caps upload at `512 KiB/s` (`524,288 B/s`) so peer traffic stays bounded while
still giving peers enough return bandwidth for healthier swarms. The five-worker
cap, plus at most two parked stalled listeners, bounds qBittorrent and Cilium
CPU load on the client node.
These lower normal-mode limits are a conservative response to sustained NFS
write waits observed on the qBittorrent node; monitor node load and I/O wait for
at least the 15-minute alert window before increasing them again.
The quota guardrail is temporarily lifted to `1 PB`; storage, thermal, backup-WAN,
and qBittorrent-authentication guards still apply. If UDM quota data is
unavailable, the controller fails closed by applying the 1 B/s safety limits and
pausing every torrent until accounting recovers.

The smart queues controller mounts `media-downloads-unas` read-only so it can
enforce free-space guardrails before starting torrents. Its queue, quota,
thermal, and recovery decisions use service APIs plus the small
`media/qbittorrent-smart-queues-state-nfs` PVC backed by a retained directory on
the shared NAS export.

`qbittorrent-downloads-layout` runs every 15 minutes and recreates the
expected qBittorrent category directories on `media-downloads-unas`. This
keeps cleanup of stale torrent payloads from breaking Sonarr, Radarr, Prowlarr,
or Ryokan path checks that expect `/downloads/tv`, `/downloads/movies`,
`/downloads/anime`, `/downloads/prowlarr`, and their temporary directories to
exist. qBittorrent still stages incomplete payloads below `/downloads/temp`,
but each category uses its own temporary subdirectory and moves completed files
to the matching final category directory. Both this job and the state backup
use `fsGroupChangePolicy: OnRootMismatch` so mounting large NFS trees does not
repeat recursive ownership changes and exceed their active deadlines.
Completed maintenance Job objects expire after one hour so retained failures do
not keep the cluster-wide `KubeJobFailed` alert active indefinitely.

`qbittorrent-state-backup` runs every 15 minutes on the qBittorrent node and
copies qBittorrent's torrent catalog and core config from the Longhorn-backed
`qbittorrent-config` PVC to the retained
`media/qbittorrent-state-backup-nfs` PVC. Each snapshot includes
`BT_backup`, categories, watched folders, RSS state, and qBittorrent config
files, plus a checksum and `latest.txt` with torrent-state counts. Longhorn
replication protects against a single replica loss but is not a catalog backup;
restore from this NFS snapshot if the Longhorn config volume is ever faulted or
recreated with an empty torrent catalog.
Required pod affinity keeps the backup on the live qBittorrent node, allowing
the read-only `ReadWriteOnce` config volume to attach without a cross-node
multi-attach conflict.
The backup stages and compresses the small catalog on node-local `emptyDir`,
then atomically publishes one archive, checksum, and `latest.txt` to NFS. This
avoids rereading the NAS during archive creation and gives both maintenance
jobs bounded longer deadlines for temporary array latency.

The controller checks Thanos Query's deduplicated Prometheus view for Raspberry
Pi CPU and NVMe temperatures before it can start or raise downloads. Thermal mitigation is
staged: first throttle qBittorrent, then pause torrents and suspend configured
batch CronJobs, and only allow host shutdown as a last-resort protection at the
higher emergency thresholds. The cooling lock is persisted in
`/state/rpi-cooling.json`, so a controller restart does not forget the active
thermal state.

Clean shutdown, when last-resort shutdown is enabled and eligible, is performed
by node-pinned `rpi-shutdown-*` DaemonSets in the `rack-ops` namespace. They are
privileged because they chroot into the host root and run the host
`systemctl poweroff` or `shutdown -h now` command. The controller does not
cordon or drain nodes before shutdown.

Automatic PoE off/on recovery through Home Assistant is currently disabled. The
previous webhook automations were removed during the 2026-08-13 Home Assistant
automation reset. Thermal throttling, pausing, and guarded clean shutdown remain
active, but powered-off nodes require manual PoE recovery until replacement
actuators are deliberately introduced.

The smart queues controller discovers the webhook targets from optional
`QBT_RPI_COOLING_POWER_OFF_URLS` and `QBT_RPI_COOLING_POWER_ON_URLS` values in
the `media/media-qbittorrent-smart-queues` Secret. Use newline or comma
separated `node=url` entries. Those values must remain unset while Home
Assistant has no matching webhook automations. When configured in a future
revision, the controller calls the off URL after the node becomes `NotReady`,
waits the cooldown window, calls the on URL, and keeps the lock until the node
is `Ready` again.

## Download connectivity

The init container pins the qBittorrent settings that most directly affect
stalled downloads. New magnets start only until qBittorrent receives their
metadata and then stop for Smart Queues selection. DHT, PeX, local peer
discovery, encrypted protocol support, TCP/uTP transport, all-tracker
announcing, disabled anonymous mode, and bounded connection/upload limits are
written to `qBittorrent.conf` on every pod start. The init container does not
write qBittorrent's additional tracker settings; tracker list updates are owned
only by the scheduled `qbittorrent-tracker-refresh` job.

Magnet links are supported through the qBittorrent WebUI/API. The WebUI is
served at `https://qbittorrent.media.home` through Traefik's default
self-signed certificate because qBittorrent only exposes its browser
`magnet:` protocol-handler registration over HTTPS. After accepting the local
certificate in the browser, use `Tools -> Register to handle magnet links...`
from the qBittorrent WebUI. Added magnets fetch metadata immediately, stop at
the `MetadataReceived` condition, and remain stopped so
`qbittorrent-smart-queues` can choose when to download their payload.

Sonarr, Radarr, Prowlarr, Ryokan, and automation should not use that
self-signed browser URL. They should keep using the in-cluster HTTP WebUI API at
`http://qbittorrent.media.svc.cluster.local:8080` or the legacy in-cluster alias
services for category-specific clients. TLS is terminated at Traefik only; the
qBittorrent pod still listens on HTTP port `8080`.

`qbittorrent-tracker-refresh` runs once daily and refreshes the fallback list
from `https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_all.txt`
through the qBittorrent Web API. It uses the existing
`media-qbittorrent-cleanup` Secret for WebUI credentials and updates
`add_trackers_enabled` plus `add_trackers`, so new torrents pick up the current
public tracker list without waiting for a qBittorrent pod restart.

The same startup pass clears stale proxy, IP filter, and interface binding
settings. Those are useful when deliberately configured, but stale values are a
common way for all torrents to appear healthy while no peers can connect.
It also removes qBittorrent's persisted single-instance lockfile on pod start.
qBittorrent can also leave Qt single-instance markers in pod-local `/tmp`,
`/var/run`, or `/dev/shm` after an unclean container restart. The main
container pins `XDG_RUNTIME_DIR` to `/tmp/qbittorrent-runtime`, recreates that
runtime directory, and clears both the persisted lockfile and old pod-local
markers before executing the image entrypoint, because init containers do not
rerun during a container-level crash loop. Without that startup cleanup,
qBittorrent can exit immediately with `Another qBittorrent instance is already
running` even when Kubernetes has only one replica.

The torrent listener is fixed at high TCP/UDP port `53181` and is exposed by
the MetalLB Layer 2 service on the fixed VIP `192.168.3.16`. The Service uses
`externalTrafficPolicy: Local`, so MetalLB selects a node with the qBittorrent
endpoint and preserves peer source addresses. For inbound WAN peers, keep the
gateway TCP/UDP port forward aligned with that VIP and port.

The primary WAN now has a static public IPv4 address, so qBittorrent can be
publicly connectable again as long as the gateway forwards only TCP/UDP `53181`
to `192.168.3.16:53181`. Do not forward qBittorrent's WebUI/API port `8080` or
the private Traefik hostname externally; browser and automation access should
remain on LAN/VPN paths with the SOPS-managed strong WebUI credentials.

The HelmOp pulls the qBittorrent chart directly from its OCI URL and therefore
does not depend on the aggregate media `ClusterRepo` bundle. This keeps a
failure in an unrelated catalog source from blocking qBittorrent reconciliation.

## Smart Queues Controller

`qbittorrent-smart-queues` polls the UDM at `https://192.168.3.1` for current
combined primary-WAN download and upload usage. The billing cycle starts on the
17th in the gateway's reporting timezone and runs through the 16th inclusive.
It normally derives a daily guardrail by dividing the monthly guardrail by the
number of days in the current billing cycle. During the 2026-08 temporary
uncapped policy, the daily and monthly quota stop points are intentionally
lifted and the local-time uncapped window spans `00:00` through `00:00`, which
the controller treats as a full-day window. There is no client-activity based
bypass.

UniFi usage periods follow the reporting timezone discovered from the gateway,
currently `Asia/Kolkata`, rather than UTC. Completed local days come from daily
reports and the current local day comes from hourly reports, so the open day is
not counted twice. Smart Queues also compares each hourly WAN field with the
provider capability configured in UniFi. If a failover or interface reset emits
an impossible counter jump, only that field is replaced with the larger adjacent
valid hour; the other selected usage fields remain counted. The correction is
persisted in `/state/udm-usage-corrections.json` on the existing controller
state PVC and is subtracted again when UniFi later folds the affected hour into
a daily report.

The controller also repairs newly enabled fields in completed daily reports. If
a daily field exceeds the physical WAN capability and has no saved correction,
it replays that local day's retained hourly data once and merges the verified
field correction into the existing state. If hourly evidence is unavailable or
inconclusive, the raw daily value remains counted so quota enforcement stays
conservative.

Before reading quota statistics or selecting downloads, the controller resolves
the gateway's active WAN from UniFi. It discovers the backup dynamically from
the WAN configuration's `failover-only` role and correlates that role with the
gateway's current logical interface and uplink. No editable WAN name, WAN group,
or physical port is pinned in this deployment. Quota report fields are derived
from those same roles and include only network groups that are not
`failover-only`. This means WAN2 is counted automatically if it becomes the
primary, while backup traffic is excluded because torrent transfers are already
blocked for the entire backup session. While the backup WAN is active, the
controller applies the 1 byte/s safety limits and calls qBittorrent's stop-all
endpoint every 30 seconds. If UniFi WAN state cannot be read or mapped, this
guard fails closed. Quota-statistics failures also fail closed, so normal queue
selection resumes only after both active-WAN state and combined usage accounting
are available again.

`qbittorrent-smart-queues` runs as a single-replica Deployment in continuous
mode, polling every 30 seconds after each pass. Five is the useful-worker
ceiling during the temporary full-day uncapped policy, not a fixed target. The
controller begins with up to two discovery workers when nothing is productive,
then adds at most two probe slots beside known productive downloads while
aggregate throughput remains below 80% of the effective download capacity. It
contracts to the productive workers when they reach that target, and replaces
failed probes within the same run instead of waiting for another controller
pass. The per-category ceiling is also five, so the aggregate cap governs when
multiple categories have candidates. The effective download limit divided by
the productive minimum rate can lower that ceiling when a low quota, fallback,
or thermal cap cannot feed every worker. The global upload ceiling is
independently configurable through
`QBT_SINGLE_DOWNLOAD_UPLOAD_LIMIT_BYTES_PER_SEC`; production currently allows
`512 KiB/s` (`524,288 B/s`). Storage-constrained recovery remains limited to two workers.
Up to two stalled torrents that are already listening for peers may remain
active above the useful worker limit, so returning seeders retain a bounded
chance to move them without unbounded node load. No-progress probes beyond
those two listener slots are stopped and placed in reason-specific exponential
backoff so the controller searches the rest of the queue instead of retrying
the same unavailable releases hundreds of times. The controller also leaves
user-forced downloads outside the managed worker pool:
forcing a torrent does not stop the five normally selected downloads, while
quota, backup-WAN, thermal, storage hard-stop, and shutdown safeguards still
apply. The deployed selector uses the balanced strategy, so priority requests
still win first, then
torrent health, progress, remaining size, ETA, current seeds, and availability
are evaluated before media queue focus. This keeps a slow or seedless queue item
from replacing a torrent that is currently making useful progress. A
productive active torrent can be preempted only when a stopped candidate's
balanced score is materially better.
Production also enables relative-speed yielding for category batches. After a
five-minute trial, a productive worker below 25% of the other productive
workers' median observed rate may yield when that median is at least 1 MiB/s
and at least one peer worker was sampled. A 1 MiB/s good-enough floor with
10% tolerance retains workers down to about 0.9 MiB/s even when their peers are
much faster. A worker yields when another same-category torrent remains queued
after hard safety and ordering checks, even if that alternative is still in a
cooldown. It then remains in a 30-minute non-failure defer so spare worker
capacity can be used as soon as another useful candidate becomes ready. The
yield does not add a stall tag, failure count, or exponential backoff.
TV cross-torrent ordering is disabled by setting
`QBT_SINGLE_DOWNLOAD_TV_ORDER_CATEGORIES` to an empty value. TV torrents
therefore compete through the normal priority and health scoring path rather
than being blocked behind an earlier episode or focused series. For selected
multi-file TV torrents, the guard still
raises qBittorrent file priority for the earliest incomplete episode and the
next two episodes while leaving the remaining selected files at normal priority.
For Ryokan-managed `anime` and `priority-anime` torrents, Smart Queues first
unselects files beneath secondary-media directories such as `Extras/`,
`Samples/`, and `Trailers/`. The release root is ignored for this check, so a
root title that advertises `[Extras]` does not hide its real numbered episodes.
This keeps the client from spending worker slots on repeatedly poor releases.
The controller is excluded from `k8s-rpi5`: that node's hard NFS mounts entered
uninterruptible I/O during rollout and prevented the first queue decision from
completing even after the pod became Ready. Remove the exclusion only after
node-local NFS reads and a full Smart Queues decision cycle are verified there.
If a newly selected torrent does not make enough progress over the one-minute
probe window, the guard either parks it within the bounded listener pool or
cools it down and immediately probes a replacement while the run budget allows.
Preferred priority/watch pools are used only while they contain a usable worker;
parked or deferred preferred torrents no longer block normal candidates, and a
productive normal download remains active while preferred candidates use probe
slots. The deployed progress floor starts from the
`3.75 MiB` static threshold, scales for torrent size and age, and is capped by
80% of the effective download limit divided across active worker slots. Up to
two normal-mode stalled torrents may stay parked. qBittorrent's `downloading`
state alone is not enough: a torrent must move at least `64 KiB/s`, or the
cap-aware 80% worker share when the effective cap is lower, before it counts as
productive. If the controller exits, it stops qBittorrent downloads so they are
not left unmanaged while Smart Queues is offline.
New magnets stop as soon as their metadata is available, so the guard is the
only component that chooses when payload downloading starts. The UNAS NFS
export reports pool-wide free space instead of its Shared Drive quota, so the
guard applies the configured decimal `4 TB` logical capacity and measures
allocated blocks below `/downloads` at most once per minute. It reserves the
larger of `30 GiB` or `10%` of that logical capacity and skips any torrent whose
selected files do not fit in the remaining storage headroom.
Older stopped magnets and newly added magnets still in qBittorrent's `queuedDL`
state can have no file sizes for the fit check. When no productive payload
download is active, the guard temporarily opens one queue slot and gives one
such magnet up to 45 seconds to fetch metadata at 64 KiB/s down and 16 KiB/s
up. A runnable metadata bootstrap takes precedence over the older
availability-probe backlog, so new releases are not starved one tracker-dead
probe at a time. The guard always attempts to stop the magnet afterward and
restores its previous per-torrent
limits only after a stop call succeeds; the low caps remain if cleanup cannot
confirm a stop. A timeout applies the 30-minute metadata cooldown. Up to three
metadata attempts are allowed per run; their 45-second discovery windows leave
headroom in the 180-second run budget while the local qBittorrent API is
responsive. This bootstrap is disabled while storage is already at or below
reserve.
Before the reserve is exhausted, if
at least ten candidates and at least half of the candidate set are blocked by
storage fit, storage pressure mode biases selection toward torrents that fit and
finish with the least verified remaining data. When free space is already at or
below reserve, it enters constrained recovery mode instead of pausing every
torrent: it only considers torrents whose selected remaining bytes fit in the
currently free space, selects the smallest verified remaining downloads first,
temporarily raises qBittorrent's active download limit to `5`, and tracks
no-progress samples for each recovery member. In constrained recovery mode,
after two no-progress samples, a
stalled member is parked: it stays active in qBittorrent so it can resume when
seeders appear, but it no longer consumes one of the five active recovery worker
slots. The guard then refills open worker slots with other fitting torrents while
accounting for parked torrents in the storage headroom budget. There is no count
cap on parked stalled torrents; the storage fit budget still applies while
storage is constrained. A running recovery worker must sustain at least
64 KiB/s; below that it is treated as too slow for recovery, stopped, and
replaced rather than parked. Once free space is back above reserve, the next
guard pass restores the normal active download limit from the selected workers
and parked listeners instead of keeping the constrained recovery cap.
For multi-file torrents, the fit check sums only files with qBittorrent priority
greater than `0` and subtracts bytes already present according to file progress.
Torrents with unknown remaining size or no selected files are blocked while
storage is constrained; Smart Queues never uses metadata discovery to bypass
the reserve.
At the end of each pass, the guard removes expired cooldown tags from all
torrents and deletes unused global cooldown tags from qBittorrent.
Attempts are not monthly state; a pass tries up to three payload torrents and,
when needed, up to three separate metadata-only candidates, then the continuous
controller polls again. Once the monthly or daily guardrail is reached, it sets
1 B/s global transfer limits and pauses all torrents until quota is available
again.
The Grafana dashboard's Download Workers table lists every selected worker and
parked listener from the latest decision, while the summary row aggregates
worker count, remaining bytes, ETA, speed, seeds, and availability across the
selected workers.

The selector persists torrent health in the `qbittorrent-smart-queues-state-nfs` PVC.
For each torrent hash it tracks EWMA download speed, attempts, consecutive
failures, last productive time, seed/availability signals, and predicted
completion time. Priority requests still win first, and health score breaks
ties while giving repeatedly poor torrents a memory beyond the current
controller pass. TV focus does not constrain cross-torrent selection while TV
ordering categories remain empty.
The same health state tracks continuously stalled or parked incomplete torrents.
After 14 days, the controller tags them with `stale-stalled-YYYYMMDD`,
reannounces them, and parks any still-running copy so they can resume when peers
return without blocking active download slots. It does not delete incomplete
stale torrents automatically. Destructive cleanup is limited to completed
downloads that Sonarr says were already imported, and completed Radarr downloads
with permanent corrupt media/sample-detection import failures; those are removed
from qBittorrent through the Arr queue API, with bad Radarr releases blocklisted.
Completed Ryokan anime leftovers are removed directly from qBittorrent only
after strict qBittorrent completion and after Ryokan proves that every exact
selected source produced a distinct, size-matched library file. Copy-mode
sources remain recoverable in `/downloads` until that proof succeeds, then
qBittorrent removes them with the verified torrent entry. A false
`imported` state is moved back to `pending` and qBittorrent is rechecked so the
missing payload can be downloaded and Ryokan can import the full set.
Adding the qBittorrent tag `blacklist` to an active Sonarr or Radarr torrent is
also a built-in Smart Queues operator action. The controller consumes the tag,
finds the matching Arr queue item, calls the Arr queue API with
`removeFromClient=true`, `blocklist=true`, and `skipRedownload=false`, and lets
Sonarr/Radarr grab another release. If no Arr queue item matches, the controller
deletes the torrent directly from qBittorrent with `deleteFiles=true`; if the Arr
delete call or direct qBittorrent delete fails, the action tag is replaced with
`blacklist-failed`.
Smart Queues also ensures the global `blacklist` tag exists in qBittorrent on
each successful API connection, so the tag is available from the qBittorrent UI
without typing it manually.
Smart Queues additionally gates newly selected payload workers on total swarm
availability. A new worker is tagged `availability-probe` and capped at
`1 MiB/s`; the next controller pass reannounces it and collects six fresh
samples ten seconds apart. Any sample at or above `1.0` proves every selected
piece is available and removes the cap. Five positive samples below `1.0`, with
no complete sample, cause Smart Queues to remove and blocklist the release
through Sonarr/Radarr with `skipRedownload=false`, so Arr can grab another
release. Zero or missing availability telemetry is treated as inconclusive and
stopped without deletion. Admission-pending torrents with tracker-dead results
retry after 30 minutes instead of inheriting the generic exponential cooldown
up to 24 hours. Tracker-dead failures use that fixed 30-minute retry rather than
the generic no-progress backoff, and existing longer persisted cooldowns are
capped immediately. Each normal controller run checks up to two of the
least-recently-tried availability candidates. When no torrent is downloading
productively, idle fast-scan mode instead checks up to ten candidates within a
15-minute run budget. This rotates a large dead-tracker backlog substantially
faster without making active-download passes more aggressive. After that
bounded batch, the same run refreshes qBittorrent state and continues normal
queue selection instead of exiting and allowing the probe backlog to starve
runnable torrents. The same gate probes legacy stalled
torrents after two no-progress observations or once they reach 95% completion.
Force-started torrents remain explicit operator overrides. Failed Arr removals
are tagged
`availability-rejection-failed`, stopped, and excluded from automatic worker
selection instead of consuming more bandwidth. A complete sample is persisted
in an `availability-verified-<timestamp>` tag and is not rechecked for six
hours, preventing a flapping swarm from monopolizing every controller pass; a
still-stalled torrent becomes eligible for another probe after that interval.
Jellyfin watch signals do not influence torrent selection while TV ordering is
disabled. The deployment still optionally imports
`media-jellyfin-arr-api-keys`; retaining `JELLYFIN_API_KEY` or
`QBT_TV_WATCH_JELLYFIN_API_KEY` does not re-enable TV ordering without a
non-empty `QBT_SINGLE_DOWNLOAD_TV_ORDER_CATEGORIES` value.

Controller logs default to plain text at `INFO` level, including a compact
active-torrent heartbeat and compact behavior-changing decisions such as pause,
throttle, try, keep, stop, and no-candidate outcomes. Routine poll telemetry and
full structured decision payloads stay at `DEBUG`. Set `QBT_LOG_LEVEL` to
`debug`, `info`, `warning`, or `error` to tune verbosity. Set
`QBT_DECISION_LOG_LEVEL=info` only while tuning candidate selection, and set
`QBT_LOG_FORMAT=json` if machine-readable JSON lines are needed.

The Deployment exposes `/healthz` on the metrics port for startup, readiness,
and liveness probes. Rancher Monitoring scrapes `/metrics` and evaluates
PrometheusRule alerts for scrape health, stale decisions, very low effective
caps with queued work, constrained download storage, and selected workers that
are effectively idle. A warning also fires while UniFi reports the backup WAN
active and Smart Queues is holding every torrent stopped.

Priority requests are selected before normal requests. The guard treats a
qBittorrent torrent as priority when it has the `priority` tag or belongs to one
of these qBittorrent categories:

- `priority-tv`
- `priority-movies`
- `priority-anime`

Use the Seerr tag `priority` for requests that should jump the queue. In Radarr
and Sonarr, create additional qBittorrent download clients for priority-tagged
media and point them at the same qBittorrent instance with these categories:

- Radarr priority client: require the Radarr tag `priority`, category
  `priority-movies`.
- Sonarr priority TV client: require the Sonarr tag `priority`, category
  `priority-tv`.
- Sonarr priority anime client, if kept separate: require the Sonarr tag
  `priority`, category `priority-anime`.

Keep the existing non-priority clients for untagged media. The priority
categories save into the same download paths as their non-priority equivalents,
so imports continue to use the existing `/downloads` mount layout.

The controller expects UDM credentials in the
`media/media-qbittorrent-smart-queues` Secret. The legacy
`media-qbittorrent-quota-guard` Secret is still accepted as a fallback. Use
a local Network API key if the UDM accepts it for local stats endpoints:

```bash
kubectl -n media create secret generic media-qbittorrent-smart-queues \
  --from-literal=UDM_API_KEY='<local-unifi-network-api-key>'
```

or:

```bash
kubectl -n media create secret generic media-qbittorrent-smart-queues \
  --from-literal=UDM_USER='<local-udm-user>' \
  --from-literal=UDM_PASSWORD='<local-udm-password>'
```

Do not commit UDM credentials to Git. The qBittorrent WebUI credentials continue
to come from the existing `media-qbittorrent-cleanup` Secret.

Sonarr and Radarr queue enrichment are optional. TV ordering is currently
disabled with an empty `QBT_SINGLE_DOWNLOAD_TV_ORDER_CATEGORIES`, but Sonarr
queue access remains enabled for import-rejection cleanup and related metadata.
If the `media/media-jellyfin-arr-api-keys` Secret contains `RADARR_API_KEY`, the
guard reads Radarr's queue from
`http://radarr.media.svc.cluster.local:7878` for movie ordering. Missing API
keys or missing queue records fall back to qBittorrent torrent names. Queue reads
are paginated so the controller can see large Arr backlogs before ordering,
cleanup, or rejection decisions are made.

## Download Recovery

`qbittorrent-smart-queues` also owns qBittorrent cleanup so it cannot race with a
separate recovery controller. Generic missing-files cleanup removes only the
qBittorrent entry with `deleteFiles=false`; it never deletes residual filesystem
data because an interrupted importer may have left the only recoverable copy.
Ryokan-managed anime categories retain the torrent entry as well, allowing the
receipt reconciler to requeue and recheck an interrupted import.
Starting, stopping, reannouncing, and cooldown rotation are handled by the
single-download selector so cleanup cannot accidentally start additional torrents.
Before normal selection, Smart Queues also checks Sonarr and Radarr terminal
import rejections. Queue items marked already imported, not an upgrade, or not
a Custom Format upgrade are
verified against the existing Arr library file, then removed from Arr with
`removeFromClient=true`. If verification or removal fails, the matching torrent
is still filtered out of worker selection so bandwidth is not spent on a release
Sonarr or Radarr has already decided it cannot import.
Ryokan intentionally retains imported anime sources in copy mode, so Smart
Queues handles verified source cleanup in the same
cleanup pass. The Ryokan path uses `QBT_RYOKAN_IMPORTED_ANIME_*` settings and
deletes only completed torrents in `anime` or `priority-anime` when every selected
media path resolves safely from the read-only `/downloads` mount and the receipt
reconciler at `ryokan.media.svc.cluster.local:8979` confirms an exact
source receipt and one distinct, size-matched target per source. The reconciler
runs beside Ryokan, reads its SQLite database and anime library locally, and accepts the existing
`SONARR_ANIME_API_KEY`; the database's RWO volume is never shared with the Smart
Queues pod. Receipt mismatches requeue only an already-imported matching hash
whose grabbed episode count equals the selected media count, and trigger a
qBittorrent recheck instead of deletion. Count mismatches fail closed for
operator recovery.

For completed torrents that need operator classification or manual import,
follow the
[`completed-torrent-import-recovery` runbook](../../../../../docs/runbooks/completed-torrent-import-recovery.md).
For Sonarr packs whose grab metadata contains only the first episode, recover
from a folder-only candidate scan in copy mode, omit the stale download ID, and
retain the payload until exact episode-file and byte-size verification passes.

For node-load alerts, productive-worker tuning, and process-table diagnosis,
follow
[`docs/runbooks/node-saturation-and-zombie-processes.md`](../../../../../docs/runbooks/node-saturation-and-zombie-processes.md).
