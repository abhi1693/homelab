# Media acquisition schedule

Acquisition runs **22:00–10:00 Asia/Kolkata on nights starting Monday through
Friday**. Friday's window ends Saturday at 10:00. Saturday daytime, Sunday and
Monday before 22:00 remain paused. The end is exclusive: 10:00 is closed.

The reconciler manages these seven Deployments in `media`:

- `qbittorrent`
- `qbittorrent-smart-queues`
- `sonarr`
- `radarr`
- `episeerr`
- `prowlarr`
- `profilarr`

They have a Git baseline of zero replicas and run one replica inside the window.
Queues, configuration PVCs and media files are retained. Jellyseerr, Jellyfin and
FlareSolverr remain online. Ryokan and Shoko retain their separately paused state;
this controller has no permission to scale any of those excluded applications.

## Configuration and ownership

[`config.json`](config.json) owns the timezone, overnight interval, starting
weekdays, startup phases and request retry limits. `enabled: false` keeps the
acquisition apps paused. Set it back to `true` to resume the configured schedule.
Apply configuration through Git/Fleet.

The controller checks current time every 15 seconds, including immediately after
restart, rather than relying on a start/stop CronJob edge. Fleet retains ownership
of images, resources, storage, network policies and other configuration. Exact
`/spec/replicas` comparison exclusions delegate only the seven runtime replica
counts. The four chart apps use the exclusion in their child HelmOps; the three
plain Deployments use it in their owning Fleet bundles. Their zero baseline makes
an unrelated upgrade or rollback start paused; the reconciler can restore one
replica only while the window is open.

No fixed node placement or affinity is added. The controller uses an existing
verified ARM64 Python image, 10m CPU / 32Mi memory requests, and namespace-scoped
permissions limited to seven scale subresources, three CronJobs and one state
ConfigMap. It cannot read Secrets through the API. Its Jellyseerr key is supplied
from the existing `media-episeerr` Secret, with only that one key exposed.

## Stop and start behavior

At closure, the controller suspends the three qBittorrent maintenance CronJobs,
scales qBittorrent to zero and waits for its graceful shutdown, then stops the
remaining acquisition apps. A running transfer or import may need its existing
termination grace to finish stopping; no force deletion or media cleanup occurs.
Smart Queues' shutdown callback alone is not used as the transfer stop barrier.

At opening, Prowlarr and qBittorrent start first. Sonarr and Radarr follow after
those are Ready. Episeerr and Profilarr then start, followed by Smart Queues.
The backup, downloads-layout and tracker-refresh CronJobs resume after the apps
are Ready. Explicit timezones and bounded missed-start deadlines prevent a
weekend suspension from replaying old maintenance runs. Tracker refresh stays at
03:17 IST on Tuesday–Saturday mornings.

## Requests received while paused

Jellyseerr remains available, but an auto-approved request sent to a stopped Arr
API is stored as Failed. Once all acquisition apps are Ready, the reconciler
retries only eligible requests created after this schedule was activated and
during its off-hours or recorded startup downtime. Existing failures from before
activation are never replayed. Pending, declined, deleted, available and completed
requests are left alone. Anime and non-managed server requests are excluded;
anime ownership remains with Ryokan/Shoko.

The configured activation boundary was captured before the first rollout, so
requests arriving while the apps stop and the controller starts remain eligible.
Once initialized, the retained state keeps its original activation boundary.
The retained `media-acquisition-schedule-state` ConfigMap records activation time,
managed downtime and per-request retry claims. Claims are saved before an API
retry, with at most one attempt per request per overnight window. Ambiguous
network responses therefore do not create an immediate repeat loop. The
controller sends no approval, deletion, search or manual import commands.

Keep this state ConfigMap when updating the code. It is runtime-owned and kept
on Helm removal. Before deliberately resetting it, move `activationAt` to the
reset time; retaining the original boundary would make previously attempted
eligible failures retryable again. Imports interrupted by closure can resume
from retained paths; missed application webhooks are not guaranteed to replay.

## Validation and inspection

Run the local lifecycle and retry tests:

```sh
python3 -m unittest discover -s kubernetes/projects/entertainment/apps/media-acquisition-schedule/tests -v
```

Inspect an allowed Friday night and a paused Sunday without API changes:

```sh
python3 kubernetes/projects/entertainment/apps/media-acquisition-schedule/controller.py --config kubernetes/projects/entertainment/apps/media-acquisition-schedule/config.json --once --dry-run --now 2026-11-06T22:00:00+05:30
python3 kubernetes/projects/entertainment/apps/media-acquisition-schedule/controller.py --config kubernetes/projects/entertainment/apps/media-acquisition-schedule/config.json --once --dry-run --now 2026-11-08T12:00:00+05:30
```

`--now` is accepted only with `--dry-run`. Dry runs do not write controller state
or retry requests. The native shell health probe checks the small local status
file without starting Python, importing an application backend or making network
requests. This keeps probes cheap under the controller's 100m CPU limit.

After Fleet reconciliation, inspect the controller logs and
`/tmp/status.json`, the seven desired/Ready counts, helper CronJob suspension and
excluded app readiness. Verify Fleet desired/applied equality separately from
Git, and check retained PVC UIDs against the pre-change inventory. During an
off-hours rollout, verify the closed state and dry-run opening plan; a live
scheduled opening is observed at the next allowed weekday night.
