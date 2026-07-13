# qBittorrent

This bundle runs the qBittorrent client used by the media stack.

The smart queues controller code lives in
`https://github.com/abhi1693/qbittorrent-smart-queues` and runs from the
`registry.home/ghcr.io/abhi1693/qbittorrent-smart-queues`
container image. Its Kubernetes runtime lives in this media qBittorrent bundle
and runs in the `media` namespace.

Legacy split-client hostnames and service names for `qbittorrent-movies`,
`qbittorrent-anime`, and `qbittorrent-prowlarr` are retained as aliases to the
single `qbittorrent` deployment so existing media app settings continue to work.

## Bandwidth policy

qBittorrent starts with a bounded global rate limit, so a pod restart
cannot temporarily consume the full WAN link before the management controller
reconciles it:

- `qbittorrent`: 8 MiB/s down, 1 MiB/s up, 1 active download outside the
  uncapped window; up to 5 active downloads from 22:00 to 05:00 IST

The qBittorrent pod is allowed up to `2 GiB` of memory to absorb restore and
peer-reconnect bursts without OOM-killing the client and dropping active peers.

`qbittorrent-smart-queues` also enforces runtime limits. The deployed ceiling is
10 MiB/s down and 512 KiB/s up, with the same 10 MiB/s ceiling available to
burst mode while quota headroom remains. If UDM quota data is temporarily
unavailable, the controller applies a safe fallback of 8 MiB/s down and
512 KiB/s up instead of pausing every torrent.

The smart queues controller mounts `media-downloads` read-only so it can enforce
free-space guardrails before starting torrents. Its queue, quota, thermal, and
recovery decisions use service APIs plus the small
`media/qbittorrent-smart-queues-state` PVC.

The controller checks Rancher Monitoring Prometheus for Raspberry Pi CPU and
NVMe temperatures before it can start or raise downloads. Thermal mitigation is
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

Automatic PoE off/on recovery is controlled through Home Assistant webhooks in
the home-automation Fleet app. The webhook automations call the UniFi Network
PoE switch entities for these ports:

- `k8s-rpi1`: `switch.usw_24_poe_port_2_poe`
- `k8s-rpi2`: `switch.usw_24_poe_port_4_poe`
- `k8s-rpi3`: `switch.usw_24_poe_port_6_poe`

The smart queues controller discovers the webhook targets from optional
`QBT_RPI_COOLING_POWER_OFF_URLS` and `QBT_RPI_COOLING_POWER_ON_URLS` values in
the `media/media-qbittorrent-smart-queues` Secret. Use newline or comma
separated `node=url` entries. When configured, the controller calls the off URL
after the node becomes `NotReady`, waits the cooldown window, calls the on URL,
and keeps the lock until the node is `Ready` again.

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
the Cilium LoadBalancer service. For inbound WAN peers, keep the gateway TCP/UDP
port forward aligned with the assigned qBittorrent LoadBalancer IP and port.
Behind ISP CGNAT this forward does not make qBittorrent publicly connectable;
the client is effectively outbound-only, so release health and rotation matter
more than the listener port.

## Smart Queues Controller

`qbittorrent-smart-queues` polls the UDM at `https://192.168.3.1` for current
WAN download usage and treats `2.5 TB` as the hard monthly qBittorrent guardrail.
It also derives a daily guardrail by dividing the monthly guardrail by the
number of days in the current month. While usage is under both guardrails, it
sets a conservative qBittorrent download limit from the tighter of the remaining
monthly budget and the remaining daily budget. There is no client-activity
based bypass.

`qbittorrent-smart-queues` runs as a single-replica Deployment in continuous
mode, polling every 30 seconds after each pass. It keeps or resumes up to three
active download workers per qBittorrent category, capped by the effective
download limit divided by the productive minimum rate so a low quota cap cannot
start more workers than it can feed. Stalled torrents that are
already listening for peers are allowed to remain active above those category
worker limits at all times, so a returning seeder can move them immediately
without blocking replacement workers. The deployed selector uses the balanced
strategy, so priority requests still win first, then torrent health, progress,
remaining size, ETA, current seeds, and availability are evaluated before media
queue focus. This keeps a slow or seedless queue item from replacing a torrent
that is currently making useful progress. A productive active torrent can be
preempted only when a stopped candidate's balanced score is materially better.
When `SONARR_API_KEY` is present from `media-jellyfin-arr-api-keys`, Sonarr
queue position and episode metadata determine the focused series and next
episode; otherwise the guard falls back to parsed torrent names. This keeps
episodes from multiple shows from interleaving just because they share the same
season and episode number. For selected multi-file TV torrents, the guard also
raises qBittorrent file priority for the earliest incomplete episode and the
next two episodes while leaving the remaining selected files at normal priority.
This keeps an outbound-only CGNAT client from spending the slot on repeatedly
poor releases.
If the kept or newly selected torrent does not make enough progress over the
five-minute sample window, the guard parks it so it can keep listening for peers
while another torrent gets a worker slot. The deployed floor starts from the
`18.75 MiB` static threshold, scales for torrent size and age, and is capped by
80% of the effective download limit divided across active worker slots. Up to
five normal-mode stalled torrents may stay parked. qBittorrent's `downloading`
state alone is not enough: a torrent must move at least `64 KiB/s`, or the
cap-aware 80% worker share when the effective cap is lower, before it counts as
productive. If the controller exits, it stops qBittorrent downloads so they are
not left unmanaged while Smart Queues is offline.
New magnets stop as soon as their metadata is available, so the guard is the
only component that chooses when payload downloading starts. It reserves the
larger of `30 GiB` or `10%` free space on `media-downloads`, and skips any
torrent whose selected files do not fit in the remaining storage headroom.
Older stopped magnets can predate the metadata stop condition and therefore
have no file sizes for the fit check. When no productive payload download is
active, the guard temporarily opens one queue slot and gives one such magnet up
to 45 seconds to fetch metadata at 64 KiB/s down and 16 KiB/s up. It always
attempts to stop the magnet afterward and restores its previous per-torrent
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

The selector persists torrent health in the `qbittorrent-smart-queues-state` PVC.
For each torrent hash it tracks EWMA download speed, attempts, consecutive
failures, last productive time, seed/availability signals, and predicted
completion time. Priority requests still win first, TV focus chooses the next
watchable series/episode, and health score breaks ties while giving repeatedly
poor torrents a memory beyond the current controller pass.
The same health state tracks continuously stalled or parked incomplete torrents.
After 14 days, the controller tags them with `stale-stalled-YYYYMMDD`,
reannounces them, and parks any still-running copy so they can resume when peers
return without blocking active download slots. It does not delete incomplete
stale torrents automatically. Destructive cleanup is limited to completed
downloads that Sonarr says were already imported, and completed Radarr downloads
with permanent corrupt media/sample-detection import failures; those are removed
from qBittorrent through the Arr queue API, with bad Radarr releases blocklisted.
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
When Jellyfin reports an active episode session, the selector boosts matching
single-episode TV torrents for later episodes in the same season. Full-season
packs are deliberately excluded because once a pack finishes, the entire season
is available together. The deployment optionally imports `media-jellyfin-arr-api-keys`; add
`JELLYFIN_API_KEY` or `QBT_TV_WATCH_JELLYFIN_API_KEY` there in the `media`
namespace to enable the Jellyfin watch signal.

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
are effectively idle.

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

Sonarr and Radarr queue enrichment are optional. If the `media/media-jellyfin-arr-api-keys`
Secret exists and contains `SONARR_API_KEY`, the controller reads Sonarr's queue from
`http://sonarr.media.svc.cluster.local:8989` for TV ordering. If it contains
`RADARR_API_KEY`, the guard reads Radarr's queue from
`http://radarr.media.svc.cluster.local:7878` for movie ordering. Missing API
keys or missing queue records fall back to qBittorrent torrent names.

## Download Recovery

`qbittorrent-smart-queues` also owns qBittorrent cleanup so it cannot race with a
separate recovery controller. Cleanup deletes missing-file torrents only. Starting,
stopping, reannouncing, and cooldown rotation are handled by the single-download
selector so cleanup cannot accidentally start additional torrents.
