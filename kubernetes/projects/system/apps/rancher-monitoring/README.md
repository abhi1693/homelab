# Upstream kube-prometheus-stack

The monitoring runtime uses upstream `prometheus-community/kube-prometheus-stack`
`92.2.0`: Prometheus 3.15.0, Grafana 13.2.3, Alertmanager 0.34.1 and operator
0.94.1. Prometheus, Alertmanager, Grafana, the Grafana sidecar and Thanos use
upstream images. Thanos query and sidecars run 0.42.4. Existing storage identities
are retained. Review backups and a supported recovery path before stateful maintenance.

The upstream chart is fetched from its official GHCR OCI repository, avoiding
large HTTP chart-index parsing in the memory-bounded HelmOps controller.
HelmOp resources put the complete OCI reference in `helm.repo` and omit
`helm.chart`, as required by Fleet's HelmOps resolver.

Three Fleet HelmOps reconcile in order: upstream CRDs, upstream runtime, then
Rancher dashboard integration. `upstream-values.yaml` and
`upstream-crd-values.yaml` own the runtime; `dashboards-values.yaml` owns the
Rancher UI integration. Namespaces belong to wrapper manifests, not HelmOps.
Use the active files for changes; the release and resource names preserve
storage bindings, selectors and consumers.

Fleet accepts the NFS dependency in `Ready` or `NotReady` state so an unhealthy
node agent does not block monitoring rule and dashboard updates. Missing or
undeployed dependencies remain blocked.

The CRD upgrade Job applies schemas before runtime updates. Grafana database
changes require a reviewed recovery plan rather than a blind downgrade.
Stock dashboards are provisioned by the upstream chart in
`cattle-monitoring-system`; chart upgrades refresh them. Integration/custom
dashboards remain in their owning namespaces, and UI-created content lives in
Grafana's database. Preserve dashboard UIDs and datasource references.

Grafana 13's SQLite migration uses a 64 MiB migration cache and Parquet staging;
the Grafana container has a 1 GiB memory limit and its existing UID/GID 472.

Native `monitoring-prometheus`, `monitoring-alertmanager` and
`monitoring-grafana` Services back the maintained Rancher UI proxies. Grafana's
Ingress connects directly to its native Service. Replica-specific OTLP write
Services and Thanos discovery names remain unchanged. Preserve these service
identities during upgrades and verify native and Rancher UI access after Fleet
reconciliation.

Grafana anonymous access is explicitly disabled before collecting broader OS
authentication and API audit records. Use the existing authenticated login;
dashboard folders do not restrict datasource query access. Existing Loki/Tempo
datasource UIDs remain stable. Native OTel `trace_id` structured metadata has a
label-derived trace link alongside the legacy body-regex link.

OS monitoring has two dashboards:

- **OS / Host Metrics** keeps UID `os-incident-evidence` and the existing URL.
  Every query and variable uses Prometheus: CPU, MemAvailable-based memory,
  root capacity, I/O pressure, physical Ethernet, uptime, readiness, inventory,
  filesystems, network-stack counters, scheduler process counts and host alerts.
  Opening this dashboard issues no Loki requests. Host-table columns fill the
  available panel width; missing data remains Unknown.
- **OS / Logs** has UID `os-logs`. Choose a node and one source: System journal,
  Kubernetes API audit, or OS files and saved journals. One bounded browser
  loads the latest 100 matching records. Level, Service and Search
  filter the full message before its 320-character display excerpt. Level supports
  multiple selections, with All levels showing every level.
  API audit rows summarize the action, resource, actor, stage and HTTP result;
  plain package/bootstrap files remain visible without requiring JSON.

Both dashboards start with data panels and link to each other with node/time
selection. Logs use UTC and show **Event time** from the original record next
to **Stored time**, the timestamp searched by the time picker. Imported journals
and source times outside the accepted range have an explicit row context;
plain files without a separately parsed producer date show Unknown event time.
Click Message to open unchanged originals and surrounding records in Explore.
There are no separate clock/boot, change-context or authentication evidence
sections to interpret: use Source, Service and text to find those records.
For example, journal Service `ssh` or `sudo` focuses authentication, `kernel`
focuses kernel messages, and source OS files includes package/setup logs and
saved native journals.

Host Metrics defaults to 30 minutes with a one-minute refresh. Logs defaults
to 30 minutes with refresh off, so a long investigation does not resubmit
expensive scans in the background. The dashboard runs only the bounded message
query; filter Level to errors to inspect the actual records. The log query
uses compiled parser stages instead of compiling regular
expressions for every record. The plaintext control is named `contains`, so
legacy `search=.*` regex state is not carried into the new dashboard.

Per-process CPU/RSS, logged-in-user counts and systemd service-state metrics
are not collected; the process view shows existing runnable/blocked counts.
The [incident coverage runbook](../../../../../docs/runbooks/incident-coverage.md)
defines source coverage, timestamp semantics and SSH capture when the query
backends are unavailable. The query regression validator runs the actual
shipped expressions against synthetic journal, audit and file records in the
pinned Loki image, including body/timestamp preservation and original-record
links: `python3 scripts/check-os-dashboard-queries.py`.

The layout was checked against these community examples. Queries are written
for this repository's datasource UIDs, `node-exporter` job, ARM64 node identity
and `eth0` interface; the examples are references, not imported dependencies.

| Examples | Applied here | Dependency difference |
| --- | --- | --- |
| [10180](https://grafana.com/grafana/dashboards/10180-kds-linux-hosts/), [22066](https://grafana.com/grafana/dashboards/22066-status-elhacker-net/) | Host summary and grouped CPU/memory/storage/network trends | Rewrite hard-coded host/job/interface selectors; use MemAvailable. |
| [5984](https://grafana.com/grafana/dashboards/5984-alerts-linux-nodes/) | Host alert context | Use current Prometheus rules, rather than legacy panel alerts. |
| [25816](https://grafana.com/grafana/dashboards/25816-linux-network-stack-node-exporter/) | TCP retransmissions, conntrack, sockets and softnet | Use enabled collectors; omit unavailable IRQ collectors. |
| [13766](https://grafana.com/grafana/dashboards/13766-loki-syslog-aio-overview/), [17514](https://grafana.com/grafana/dashboards/17514-ssh-logs/) | Level/activity overview, searchable journal and SSH evidence | Parse native journal fields from the existing OTel pipeline; no Promtail/syslog-ng replacement. |
| [8378](https://grafana.com/grafana/dashboards/8378-system-processes-metrics/), [3387](https://grafana.com/grafana/dashboards/3387-process-top/) | Process-detail reference | Require process-exporter or Telegraf procstat; existing node-exporter supplies scheduler counts only. |
| [2381](https://grafana.com/grafana/dashboards/2381-olympus/), [25711](https://grafana.com/grafana/dashboards/25711-linux-network-performance/), [25710](https://grafana.com/grafana/dashboards/25710-linux-network-performance-deep-dive/) | General host and network hierarchy | Require InfluxDB/Telegraf; use existing Prometheus metrics here. |
| [8677](https://grafana.com/grafana/dashboards/8677-servidores-linux/), [11836](https://grafana.com/grafana/dashboards/11836-suspicious-attempt/) | Host/authentication context | Require Zabbix or Sonicwall/Elasticsearch data; do not infer those sources from SSH messages. |

Longhorn 1.12.1 isolates manager ingress by default. The colocated
`longhorn-networkpolicy.yaml` permits TCP/9500 only from this stack's Prometheus
pods in `cattle-monitoring-system`, preserving the existing Longhorn metrics
scrape without disabling upstream network policies. After an upgrade, verify
all eight manager targets are up and `longhorn_volume_robustness` is present;
the Home Assistant status bridge intentionally rejects missing storage metrics.

Prometheus, Alertmanager, Grafana, the monitoring operator and kube-state-metrics
select control-plane nodes and tolerate `CriticalAddonsOnly=true:NoExecute`.
Thanos Query prefers worker nodes, and its two replicas have required pod
anti-affinity. Node exporter remains node-local across servers and workers,
retaining port `9796`, its host textfile collector, and both `NoSchedule` and
`NoExecute` tolerations so all eight nodes remain covered.

The Linux-only cluster disables the chart's Windows exporter dependency so it
does not render an unschedulable Windows DaemonSet. Grafana's `init-chown-data`
container is explicitly bounded at `5m`/`16Mi` requests and `100m`/`64Mi`
limits; namespace defaults cover other chart-generated hook or init containers
that omit resource keys without adding a generic CPU limit.

Fleet wrapper for upstream monitoring and Rancher dashboard integration in
`cattle-monitoring-system`. It owns three HelmOps: `rancher-monitoring-crd`,
`rancher-monitoring-stack`, and `rancher-monitoring-dashboards`. Prometheus runs two
replicas with hard pod anti-affinity and one retained `64Gi` Longhorn PVC per
replica. Each replica has `30d` retention, a `52GiB` retention-size
cap, a 4Gi memory request, and a 6400Mi memory limit. The size cap keeps Prometheus
near 81 percent of the declared claim capacity so WAL and compaction activity
retain filesystem headroom. The global Prometheus scrape interval is `60s`.
Each Thanos sidecar requests `640Mi` and is limited to `2Gi`. Go's automatic
memory limit targets 75 percent of the cgroup limit, and each StoreAPI request is
capped at 10,000 series and 1.2 million samples. These bounds prevent oversized
reads from exhausting sidecar memory.
Two Thanos Query replicas discover a sidecar on every Prometheus replica through
the chart's headless discovery Service. Query deduplicates the
`prometheus_replica` external label, fails a request when a source is unavailable
instead of silently returning partial data, and has no cloud or object-storage
dependency. Each Query replica is limited to four concurrent queries and two
concurrent selects per query, requests `768Mi`, and has a `3Gi` memory limit with
the same 75-percent Go memory target. Prometheus therefore keeps normal local
TSDB compaction without allowing oversized reads to take down the query plane.

Retained former NFS Prometheus claims are rollback data, not active TSDB storage.
Review retention before deleting them. Grafana, automation
controllers, and `prometheus.home` query Thanos Query. Grafana explicitly
allows partial responses for interactive dashboards; automation retains Query's
fail-closed default. The OpenTelemetry Collector writes every metrics batch to
ordinal-specific Services for both Prometheus replicas.
`thanos-query-health` alerts when either Query replica is unavailable or a
Query pod resolves fewer than both Prometheus sidecars for five minutes.

The chart's stock `KubeJobFailed` alert is disabled because it fires forever for
retained failed Job objects. `kubernetes-job-health` preserves the same 15-minute
failure threshold for Jobs that started within the last 24 hours. The object and
its logs can remain available for diagnosis without turning an old, superseded
run into a permanent alert.

The Prometheus OTLP metrics receiver is enabled for application OpenTelemetry
metrics and promotes common service resource attributes. Its TSDB accepts
samples up to 30 minutes out of order to accommodate collector batching; each
producer still needs a unique service instance identity. Keep dashboard ConfigMaps,
bridge Services, PVCs and datasource identities stable across chart changes.
Grafana also provisions
a `Tempo` datasource for the lightweight Tempo app in this project.
Alertmanager runs two replicas with retained `2Gi` NFS PVCs. Grafana is exposed internally at
`grafana.home`, Prometheus at `prometheus.home`, and Alertmanager at
`alertmanager.home`. Grafana intentionally runs as a single
persisted `2Gi` NFS-backed instance because HA Grafana would need external
database/shared-session work that is not useful for the initial scope.
Grafana's root `init-chown-data` container is disabled on NFS. Its retained
NAS directory must be writable by UID/GID `472`; root-squashed ownership
changes are rejected.
Grafana's `/api/health` readiness probe allows five seconds for a response so
brief storage or node latency does not cause the default one-second timeout. If
readiness timeouts continue, investigate latency and events for the
`rancher-monitoring-grafana-nfs` claim before increasing the timeout again.
Grafana's liveness check starts after ten minutes so slow NFS-backed database
migrations and plugin initialization can finish; required pod anti-affinity
also keeps it off the node running the Loki single-binary pod. Prometheus stays
readiness-sensitive but requires five minutes of failed liveness checks before
restart, avoiding repeated WAL replay during a bounded storage stall. These
probe budgets preserve failure detection and are not a substitute for resolving
prolonged storage latency.
Because Grafana has one replica, database HA coordination is disabled. SQLite
queries and transactions each retry lock contention up to ten times so a
temporary NFS delay cannot make an otherwise healthy Grafana process exit.
Alertmanager loads `AlertmanagerConfig` resources cluster-wide and uses the
`home-lab-slack` config to send non-`Watchdog`, non-`none` severity alert
notifications to Slack.
The Slack incoming-webhook URL is stored in the SOPS-managed
`alertmanager-slack` Secret.

Slack messages show per-alert firing/resolved status, source, severity and
Alertmanager's native notification reason. Explicit telemetry incident labels
correlate related delivery symptoms; DevFeed fast/slow availability burns group
by service. Other alerts retain alert-name grouping. Permanent loss is displayed
first and is never hidden by a new inhibition rule. The four-hour repeat and
five-minute group interval remain unchanged; Alloy's ten-minute recovery hold
bridges brief gaps between drop bursts. See the
[notification runbook](../../../../../docs/runbooks/slack-notifications.md)
for the investigation, recovery semantics and local capture validation.

`kube-state-metrics` mounts host timezone data read-only so it can parse CronJobs
using Kubernetes `.spec.timeZone` values such as `Asia/Kolkata`.

Fleet ignores runtime diffs on the chart-managed admission webhook definitions
because the chart hook injects generated CA bundle data after rendering.

The Prometheus selectors are left open so later app bundles can add
`ServiceMonitor`, `PodMonitor`, `Probe`, `ScrapeConfig`, and `PrometheusRule`
resources without changing the base monitoring install.

`cloudflare-tunnel-dashboard` keeps the connector traffic, capacity, edge, and
origin-health views. The Cloudflare Tunnel app's companion Fleet bundle adds a
controller metrics `Service` and `ServiceMonitor`; the stable Service port
`8080` maps to the controller's metrics listener on `9090` and is restricted to
Rancher Monitoring by NetworkPolicy. `cloudflare-tunnel-health` alerts when
fewer than two connector targets are healthy, a connector has fewer than four
HA edge connections, the connector Deployment loses readiness, connector
configuration versions disagree, origin proxy connections fail, the tunnel's
5xx rate stays above 5% with meaningful traffic, fewer than two controller
metrics targets are healthy, available controller metrics report no leader, or
controller reconciliation reports errors.

K3s metrics use native authenticated kubelet HTTPS endpoints on port 10250.
The `k3s-server` job and `metrics_path` labels are retained for `/metrics`,
`/metrics/cadvisor` and `/metrics/probes`. The first drops duplicate
`apiserver_*` samples; the dedicated API server target retains its SLI histogram.
Cluster identity labels remain `local`. Separate scheduler/controller/proxy
scrapes are disabled because K3s shares a registry. PushProx and Prometheus
Adapter are not part of the runtime configuration.

The 28 October 2026 cardinality review found about 37,135 active series with no
exact references in the 73 provisioned dashboards and 403 alerting/recording
rules inspected. Scrape-time metric relabeling drops these five groups:

- Longhorn internal REST-client latency and workqueue duration histograms
  (bucket, sum and count): 18,044 series.
- Kubelet probe-duration histogram (bucket, sum and count): 7,938 series.
- cAdvisor `container_tasks_state`: 4,765 series.
- Scheduler plugin-duration histogram (bucket, sum and count): 3,726 series.
- `kubernetes_feature_enabled`: 2,662 series.

The scheduler and feature filters cover both API-server and kubelet shared
registries. Probe results, `container_memory_failures_total`, API-server SLI
histograms, and Longhorn volume health/capacity/latency metrics remain collected.
Query logging was disabled during the review, so lack of dashboard/rule references
does not establish that these metrics were never queried manually. Historical
samples remain until normal retention expires; reductions in active series do
not imply proportional CPU, memory or disk savings. Revert the specific drop rule
through Fleet if detailed internal timings are needed again.

The Ansible-managed K3s configuration also disables unused, high-cardinality API
request, response, watch, and etcd histogram families at the source. After
applying that host configuration, roll the K3s servers through
`infrastructure/ansible/playbooks/k3s_server.yml`; the playbook's `serial: 1`
policy preserves etcd quorum and API availability while each server restarts.

When changing metric collection, reconcile Fleet values first and verify both
API server and filtered K3s targets. Host metric configuration changes require
the serialized K3s server play and its recovery gates. Verify target health,
series ingestion, and API SLO rules afterward.

## Resource request baseline

Review requests against sustained CPU and memory use with burst headroom.
Prometheus requests `350m` CPU and `4Gi` memory per replica. Each Thanos sidecar
requests `100m` CPU. Grafana's main and dashboard-sidecar containers request `35m` CPU and
`704Mi` memory in total. Rancher's separate UI proxy has two replicas. The chart-wide `grafana.sidecar.resources` key applies to its
sidecars. Node exporter requests `5m` CPU on each node and remains burstable.
`kube-state-metrics` requests `192Mi` and is capped at `384Mi`; preserve
startup headroom when resizing it.

`traefik-podmonitor` scrapes the bundled K3s Traefik pods in `kube-system` on
their existing internal Prometheus metrics port, `9100`. The metrics port is not
added to the public Traefik LoadBalancer service. `traefik-dashboard` provisions
the official Kubernetes Traefik Grafana dashboard in `cattle-dashboards`.

`cluster-capacity-planning-dashboard` is a Grafana dashboard for node purchase
planning. It separates scheduler pressure from runtime pressure by comparing
CPU/memory requests, limits, and actual usage against live allocatable node
capacity. Forecast and "nodes needed" panels use current Prometheus data rather
than hardcoded hardware sizes, so the dashboard adapts when nodes are added,
removed, or replaced. The top decision row calls out whether to buy now or plan
within 30 days, whether the pressure is CPU, memory, or balanced, how many
current-node equivalents are needed, and the minimum extra CPU/memory needed to
return to the 85% planning line. `kube-state-metrics` exports selected namespace
labels so project-level panels can group dynamically by Rancher project labels.
Request and limit recording rules join against `kube_pod_status_phase` so
completed and failed pods do not inflate scheduling-pressure recommendations.
Per-pod request rules estimate Kubernetes scheduler pressure by taking the
larger of summed app-container requests and max init-container request. Their
ordered PromQL fallback preserves container-only, init-only, and combined pod
shapes, including Cilium's init-only CPU and memory requests. Cluster and
namespace request rules then split assigned pods (`node!=""`) into scheduled
commitment and unassigned Pending pods (`node=""`) into pending demand.
Commitment, headroom, purchase, and forecast panels use only scheduled requests;
pending CPU and memory remain visible in separate headline and trend series.
Runtime usage panels continue to use cAdvisor CPU rate and memory working-set
metrics.

`raspberry-pi-prometheus-dashboard` is a Prometheus-native Grafana dashboard in
`cattle-dashboards`. It uses Rancher's existing node-exporter scrape for ARM64
Raspberry Pi nodes, including `node_hwmon_temp_celsius` for board/NVMe
temperature, so it does not require InfluxDB or Telegraf. Current CPU and NVMe
temperatures are shown as compact bar gauges ordered hottest to coolest, with
the historical trend kept separate for correlation. NVMe temperature panels
use the kernel hwmon
`Composite` sensor so they line up with `smartctl_exporter`'s SMART current
temperature; hotter per-sensor readings remain available in raw hwmon metrics
for deeper troubleshooting. The dashboard also shows Raspberry Pi active cooler
duty as a percentage from node-exporter's `node_hwmon_pwm` metric on the Pi's
0-255 PWM scale, with aligned CPU temperature and cooler duty trend panels for
cooling response correlation. Raspberry Pi firmware throttling state is exported
through node-exporter's textfile collector from `vcgencmd get_throttled`, adding
active and since-boot views for undervoltage, frequency capping, throttling, and
soft temperature limit events.

`raspberry-pi-node-health` adds Prometheus alerts for node-exporter availability,
high CPU temperature, root filesystem pressure, memory pressure, and sustained
iowait while load exceeds one runnable or waiting task per core on the Raspberry
Pi nodes. The load gate distinguishes an I/O queue from normal synchronous
Longhorn writes on an otherwise idle node. It also alerts when Raspberry Pi throttling
metrics cannot be collected, when firmware throttling is active, or when a
throttling condition has occurred since the last reboot.

`smartctl-exporter` scrapes the host-level `prometheus-smartctl-exporter`
service on each Raspberry Pi node for NVMe S.M.A.R.T. health. The host service is
installed by the Ansible `smartctl_exporter` role because the current upstream
container image is not published for arm64. Its `ScrapeConfig` discovers
Kubernetes nodes named `k8s-rpi*`, rewrites each target to the node's InternalIP
on port `9633`, and supplies the node label used by the dashboard variables. A
newly joined Raspberry Pi therefore appears automatically after its host
exporter is installed. `raspberry-pi-nvme-smart-dashboard` adds the Grafana view
for SMART status, NVMe wear, available spare, temperature, media errors,
error-log growth, and lifetime IO.

Operational response procedures:

- [`docs/runbooks/alertmanager-firing-alert-triage.md`](../../../../../docs/runbooks/alertmanager-firing-alert-triage.md)
- [`docs/runbooks/kubernetes-cpu-overcommit.md`](../../../../../docs/runbooks/kubernetes-cpu-overcommit.md)
- [`docs/runbooks/node-saturation-and-zombie-processes.md`](../../../../../docs/runbooks/node-saturation-and-zombie-processes.md)
- [`docs/runbooks/storage/raspberry-pi-high-iowait.md`](../../../../../docs/runbooks/storage/raspberry-pi-high-iowait.md)

Current Grafana NFS capacity is adequate; transient stalls require time-aligned
evidence before changing the storage backend.

## Unsupported ingress dashboards

This cluster uses Traefik, not ingress-nginx. Chart
`rancher-monitoring-dashboards` `110.0.1+up0.1.4` ignores
`dashboardArtifacts.groups.ingressNginx: false` in its dashboard ConfigMap
template (it only respects it in the integration index). The Grafana sidecar's
supported pre-reload script therefore removes exactly `nginx.json` and
`request-handling-performance.json` from its ephemeral provisioning directory.
The chart-owned ConfigMap remains, but its two dashboards are not provisioned.
This survives reconciliation without editing live chart resources. Retain the
false group setting and remove this workaround once an upgraded chart no longer
renders the unwanted ConfigMap. Traefik dashboards and metrics remain enabled.

Validate Helm inputs by rendering their pinned charts before server-side dry runs.
The raw-manifest pre-commit hook excludes `upstream-values.yaml`,
`upstream-crd-values.yaml` and `dashboards-values.yaml`; they are values maps,
not Kubernetes resource documents. YAML syntax validation still covers them.

## Coverage and HA boundary

Prometheus replicas retain local Longhorn volumes and Thanos Query combines their
results without an object store. Grafana uses a single SQLite database; Loki has
one filesystem-backed writer on NFS. Tempo and Pyroscope are single writers on
Longhorn. These services can pause during pod replacement or storage reattachment.
Do not increase Grafana or Loki writer replicas against their existing storage.

Before changing replica counts, storage or query dependencies, verify scrape and
rule coverage, log delivery, historical queries, dashboard UIDs, datasource
references and alert delivery. PDBs cover voluntary eviction; they do not prove
node-failure availability or protect against a NAS outage.

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `cattle-monitoring-system/rancher-monitoring/prometheus` | 400m → 500m | 4Gi → 4Gi | 5Gi → 6400Mi |
| `cattle-monitoring-system/rancher-monitoring/thanos-sidecar` | 25m → 250m | 512Mi → 640Mi | 2Gi → 2Gi |
| `cattle-monitoring-system/rancher-monitoring/grafana` | 25m → 25m | 512Mi → 512Mi | 1Gi → 1280Mi |
| `cattle-monitoring-system/rancher-monitoring/grafana-sidecar` | 10m → 10m | 192Mi → 128Mi | 272Mi → 272Mi |
| `cattle-monitoring-system/rancher-monitoring/kube-state-metrics` | 10m → 10m | 192Mi → 96Mi | 384Mi → 384Mi |
| `cattle-monitoring-system/rancher-monitoring/node-exporter` | 5m → 5m | 48Mi → 32Mi | 192Mi → 96Mi |
| `cattle-monitoring-system/thanos-query/thanos-query` | 100m → 250m | 768Mi → 1408Mi | 3Gi → 3Gi |

The follow-up seven-day review reduces Prometheus from `500m` to `350m` and
each Thanos sidecar from `250m` to `100m`, releasing `600m` across two replicas.
Prometheus CPU p95 was `238–244m` per replica; sidecar p95 was about `66m`.
Memory requests/limits, the Prometheus one-core CPU limit, and the uncapped
sidecar CPU remain unchanged. These savings are on the control-plane nodes.
After reconciliation, verify both replicas, scrape freshness, and Thanos Query
discovery. Revert these two CPU values through Git if contention degrades service.

## Faro retirement

Faro browser monitoring, its two collector/resolver pods, dedicated ingress and
credentials, network grants and seven Faro dashboards were retired on 2026-10-28.
App flags were disabled and frontend bundles rebuilt before collector removal.
Backend traces, profiles, Kubernetes events, node logs and application analytics
remain active. App repository PRs remove the SDK and private source-map routes
from future releases. App-side legacy credential/configuration fields remain
only while the currently deployed images and build-cache keys still expect them.

## Host hang recovery monitoring

All eight nodes export minute host-recovery textfile metrics. Raspberry Pi rules
warn about incomplete netconsole targets, a stopped kernel receiver, stale/missing
health metrics. Boot-time changes remain available as metrics without a repeated-reboot
alert, since planned maintenance and clock adjustments can trigger it. The retired
PID 1 hardware watchdog has no active-state alert. Existing node-exporter-down
alerts cover unreachable nodes. See the [host recovery workflow](../../../../../infrastructure/ansible/roles/os_prep/README.md#remote-node-recovery-and-kernel-evidence).

Kernel receivers run outside Kubernetes on the three control-plane hosts.
Received records reach Loki through Alloy as `node/system` with
`unit="home-lab-kernel-receiver.service"`. The indexed `node` identifies the
receiver; extract journal `MESSAGE` then parse JSON `source_node` to select the failed sender. Critical
kernel forwarding is UDP and does not guarantee capture of an unlogged hang.
