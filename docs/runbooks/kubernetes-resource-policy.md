# Kubernetes Resource Policy

## Meaning

Production Pods must be schedulable from declared resource requests and must
not be able to consume unbounded memory. Directly authored regular and init
containers therefore declare CPU and memory requests plus a memory limit.

CPU limits are required for short-lived init containers, batch work, and small
controllers when the chart exposes the setting. They are intentionally omitted
for latency-sensitive or throughput-sensitive datapaths, including the Cilium
agent and Envoy, Longhorn Manager, and selected application data containers.
Those containers remain bounded by memory and schedulable by both requests.

## Impact

Requests prevent BestEffort scheduling and make node commitments visible.
Memory limits contain leaks and runaway processes. Selective CPU bursting avoids
CFS throttling on networking, storage, databases, and application hot paths.

The initial values are production starting points derived from 14 days of
Prometheus history, with headroom above observed p95/p99 usage. Revisit them
after workload or replica changes rather than treating them as permanent
capacity guarantees.

## Enforcement

The repository uses three enforcement layers:

1. Direct manifests declare resources on every regular and init container.
   `scripts/check-kubernetes-resource-bounds.py` enforces CPU/memory requests
   and memory limits in CI. It also requires recommendation-profile
   `minChangePercent` values to remain below `maxDecreasePercent`, preventing a
   bounded downsize from being discarded by the material-change gate.
2. Bootstrap and application charts use native resource values for Cilium,
   Envoy, cert-manager, Longhorn Manager and CSI sidecars, Fleet controllers,
   Traefik, Rancher Monitoring, ZITADEL helper containers, and other supported
   components.
3. Narrow `LimitRange` defaults cover generated containers whose owning chart
   or operator has no resource field. These defaults are limited to the
   Cloudflare connector, Home Assistant, PostgreSQL Pooler, and Rancher/Fleet
   controller namespaces. Explicit resources always take precedence.

Namespace defaults in shared monitoring and Fleet namespaces provide CPU and
memory requests plus a memory limit without introducing a generic CPU limit.
Controller-only namespaces may also default a conservative CPU limit.

## Longhorn Exception

Do not add a generic `LimitRange` to `longhorn-system`. Longhorn 1.11 exposes
resource values for Manager and system-managed CSI components, and the repo
uses those values. It does not expose equivalent per-workload memory settings
for instance managers, share managers, engine-image DaemonSets, all driver/UI
helpers, or recurring filesystem-trim Pods.

An earlier seven-day window measured four instance managers at about 1.745
CPU cores in aggregate at p95 and 1.968 cores at p99. Per-node p95 ranged from
217m to 1.144 cores because attached engine and replica work is unevenly
distributed. Share managers and CSI helpers are much smaller. One namespace
default would either under-size storage I/O or reserve excessive memory for
every helper. Instance managers therefore retain Longhorn's 12 percent
guaranteed CPU setting, or 480m for **each instance-manager pod** on a four-core
node, while remaining CPU-unlimited so rebuild and recovery work can burst
above the reservation.
Lower settings are not applied while engine instances are running and must not
be forced through instance-manager deletion. Revisit this setting after a
tested Longhorn upgrade/failover rehearsal or when the upstream chart exposes
safe component-specific values.

### 2026-09-05 CPU sizing review

The live audit found 20.985 cores of regular-container requests and 21.035
cores of scheduler-effective requests, including init containers, on 32 cores.
CPU requests reserve scheduling capacity and CPU shares under contention;
they do not prevent other pods using idle CPU. Removing limits alone does not
reduce reserved CPU. Retain memory requests/limits and nonzero CPU requests.

The following Git changes reduce steady scheduled requests by about 1.64 cores
at the observed replica counts. The original projection was 21.035 to 19.395
scheduler-effective cores. The fresh deployment baseline was 20.935 cores;
after Fleet applied the changes, the observed total was **19.295 cores**,
or **65.4% to 60.3%** of physical capacity. Pod inventory can change between
samples; these aggregate totals do not guarantee that every placement fits.

| Workload | CPU request per replica, before → after | Seven-day aggregate p95 / p99, millicores |
| --- | --- | --- |
| Jellyfin | 780m → 300m | 199 / 446 |
| Sonarr | 520m → 100m | 24 / 428 |
| Radarr | 240m → 75m | 10 / 35 |
| Prowlarr | 180m → 75m | 32 / 134 |
| Music Assistant | 150m → 50m | 1.5 / 8.7 |
| ShipyardHQ web, three replicas | 200m → 125m | 175 / 214 |
| Wardn AI frontend | 70m → 25m | 1.7 / 2.1 |
| Wardn AI website | 70m → 10m | 1.0 / 1.1; only about 12 hours available |
| Portfolio | 50m → 10m | 0.8 / 2.0 |

Metrics use five-minute CPU rates sampled every five minutes over a seven-day
window, joined to workload ownership **inside** the historical subquery so old
pod revisions are included. Most workloads have 2016 samples; several media
workloads have about 1613–1619, so missing intervals are not treated as idle.
Five-minute peaks do not capture every sub-minute burst. Jellyfin peaked at
2380m, Sonarr at 605m, and Prowlarr at 384m. These are burstable services, not
hard performance guarantees: their requests cover measured baseline demand
with headroom, while CPU limits are removed and latency/queue health must be
checked during representative bursts. ShipyardHQ's restore-init request is
lowered with the web request so it does not negate scheduler savings; its
finite-work CPU limit is retained.

Jellyfin, Sonarr, Radarr, Prowlarr, and qBittorrent use the pinned TrueCharts
common library's numeric `resources.limits.cpu: 0` to render **no** CPU limit.
Omitting this value inherits a chart default (1500m for the latter four).
This numeric-zero convention is chart-specific; never set a Kubernetes
container's raw `resources.limits.cpu` to zero. Verify the rendered PodSpec.
Jellyfin and qBittorrent config init containers retain their former CPU caps
through explicit per-container overrides; only the main service is uncapped.
qBittorrent's 360m request stays: its p95/p99 are 275m/302m. Wardn Hub worker's
980m request also stays: its p95/p99 are 807m/1051m. Control-plane, networking,
databases, storage, and all memory envelopes are unchanged by this review.

At the initial review, the largest outstanding reservation was **15 Longhorn instance managers ×
480m = 7.2 cores**. Eight used v1.11.3 and seven used v1.11.2. The older managers
still hosted 16 running engines, although all 26 volumes reported the v1.11.3
engine image. They were not disposable idle pods. Retiring those seven through
a separately planned, supported volume detach/reattach sequence could have released
another 3.36 cores without reducing storage CPU guarantees. Do not delete
managers, force volume detach, or lower the setting to force their recreation.
Use a separate storage window, preserve application backups/PDBs, and verify
healthy volumes and automatic old-manager cleanup after each owner recovers.
The subsequent 1.12.1 upgrade and separately authorized cleanup are tracked in
the [instance-manager retirement runbook](storage/longhorn-instance-manager-retirement.md).

Deploy app changes through Git/Fleet in stages; singleton media resource
changes cause serving gaps. Recheck scheduler-effective requests, Fleet
convergence, restarts, playback/import/transfer behavior, and node saturation.
Review after 24 hours and one week; raise a specific request if contention or
latency regresses. Do not lower recommendation-engine confidence safeguards.

#### Deployment verification

The changes were deployed through Fleet in three gated stages on 2026-09-05:
web applications (`5155c7fb`), indexers (`5f6e6b71`), then Jellyfin, qBittorrent,
and Music Assistant (`f48fe594`). Jellyfin playback interruption was explicitly
authorized. No manual workload patch, restart, or storage change was used.

- All ten affected Deployments completed their rollout. Their twelve replacement
  pods were Ready with zero container or init-container restarts.
- All fifteen affected BundleDeployments, including the five HelmOp wrappers,
  had matching desired/applied deployment IDs and Ready status.
- Admitted PodSpecs had the intended CPU requests and no main-container CPU
  caps. Memory requests/limits were unchanged; Jellyfin, qBittorrent, and
  ShipyardHQ retained their finite init-container CPU caps.
- Portfolio, ShipyardHQ, Wardn AI, and the Wardn AI website returned HTTP 200.
  Authenticated indexer status/queue APIs responded; their pre-existing indexer
  configuration/availability health findings remain a separate issue.
- Jellyfin's authenticated API, library counts, and a 64 KiB static media range
  read passed; an active playback session resumed after the restart.
- qBittorrent retained 39 torrents with zero error/missing-file states.
  Music Assistant's UI and server-info API responded successfully.
- All eight nodes remained Ready and all 26 Longhorn volumes were healthy.

These are rollout and smoke-test results, not a sustained load test. Recheck
latency, playback, imports, transfers, and historical CPU contention after a
representative busy period before making further request reductions.

## Diagnosis

List admitted Pod containers that still have neither requests nor limits. This
view includes values supplied by `LimitRange` admission:

```sh
kubectl get pods -A -o json \
  | jq -r '
      .items[] as $pod
      | (($pod.spec.initContainers // []) + ($pod.spec.containers // []))[]
      | select(((.resources.requests // {}) | length) == 0
          and ((.resources.limits // {}) | length) == 0)
      | [$pod.metadata.namespace, $pod.metadata.name, .name]
      | @tsv' \
  | sort -u
```

LimitRange defaults are applied when Pods are created. Existing Pods retain
their admitted resources until the owning controller rolls them out.

## Verification

Run the direct-manifest policy and normal repository validation:

```sh
python scripts/check-kubernetes-resource-bounds.py
yamllint .
cd infrastructure/ansible
ansible-playbook --syntax-check playbooks/site.yml
```

For Helm-backed changes, render the exact pinned chart with the Git-managed
values and inspect every regular/init container. After push, wait for Fleet
GitRepos and bundles to become ready, then repeat the read-only live audit.

## Rollback

Revert the Git commit and let Fleet or the bootstrap workflow reconcile the
previous values. Do not delete or patch live Pods manually. If a new limit
causes restart loops or throttling, raise or remove that component-specific
limit in Git; keep CPU/memory requests and a memory limit unless the Longhorn
exception above applies.
