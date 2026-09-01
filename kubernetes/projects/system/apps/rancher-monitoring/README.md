# Rancher Monitoring

Prometheus, Alertmanager, Grafana, the monitoring operator, adapter,
kube-state-metrics, and the K3s PushProx proxy select control-plane nodes and
tolerate `CriticalAddonsOnly=true:NoExecute`. Thanos Query prefers worker nodes,
and its two replicas have required pod anti-affinity. Node exporter and PushProx
clients remain node-local across servers and workers.

The Linux-only cluster disables the chart's `windowsExporter` dependency so it
does not render an unschedulable Windows DaemonSet. Grafana's `init-chown-data`
container is explicitly bounded at `5m`/`16Mi` requests and `100m`/`64Mi`
limits; namespace defaults cover other chart-generated hook or init containers
that omit resource keys without adding a generic CPU limit.

Fleet wrapper for the Rancher Monitoring charts in `cattle-monitoring-system`.

It owns two HelmOps:

- `rancher-monitoring-crd`, which installs the Prometheus Operator CRDs.
- `rancher-monitoring-stack`, which installs Rancher's monitoring stack.

The stack is pinned to chart version `109.0.5+up80.9.1-rancher.19` and starts as
cluster-infrastructure monitoring for Rancher and K3s. Prometheus runs two
replicas with hard pod anti-affinity and one retained `64Gi` Longhorn PVC per
replica. Each replica has `30d` retention, a `52GiB` retention-size
cap, a 4Gi memory request, and a 5Gi memory limit. The size cap keeps Prometheus
near 81 percent of the declared claim capacity so WAL and compaction activity
retain filesystem headroom. The global Prometheus scrape interval is `60s`.
Each Thanos sidecar requests `256Mi` and is limited to `1Gi`; the original
`256Mi` limit was raised after replica 0 exhausted it while querying the migrated
history.
Two Thanos Query replicas discover a sidecar on every Prometheus replica through
the chart's headless discovery Service. Query deduplicates the
`prometheus_replica` external label, fails a request when a source is unavailable
instead of silently returning partial data, and has no cloud or object-storage
dependency. Prometheus therefore keeps normal local TSDB compaction.

The staged migration first proved both scrapers, sidecars, and Query replicas.
Prometheus was then scaled to zero, and a one-shot Job copied the retained
replica 0 NFS claim into its Longhorn claim. The read-only source and destination
directory, file-content, and symlink digests matched at
`ef834f03e5f61f3da54ea503938d306b02c6aeac89d55206b149ce5679a50b65`.
Replica 1's Longhorn claim remains empty so the new scraper starts with an
independent history. A namespace-scoped cutover Job replaced the immutable
StatefulSet storage owner while the Prometheus resource was paused. The old NFS
claims remain retained for rollback. Grafana, Prometheus Adapter, automation
controllers, and `prometheus.home` query Thanos Query. Grafana explicitly
allows partial responses for interactive dashboards; automation retains Query's
fail-closed default. The OpenTelemetry Collector writes every metrics batch to
ordinal-specific Services for both Prometheus replicas.
`thanos-query-health` alerts when either Query replica is unavailable or a
Query pod resolves fewer than both Prometheus sidecars for five minutes.

The Prometheus OTLP metrics receiver is enabled for application OpenTelemetry
metrics and promotes common service resource attributes. Grafana also provisions
a `Tempo` datasource for the lightweight Tempo app in this project.
Alertmanager runs two replicas with retained `2Gi` NFS PVCs. Grafana is exposed internally at
`grafana.home`, Prometheus at `prometheus.home`, and Alertmanager at
`alertmanager.home`. Grafana intentionally runs as a single
persisted `2Gi` NFS-backed instance because HA Grafana would need external
database/shared-session work that is not useful for the initial scope.
Grafana's root `init-chown-data` container is disabled on NFS; the migration
copy runs as Grafana UID/GID `472`, and the NAS export rejects root-squashed
ownership changes.
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
The monitoring storage migration provisioned retained NFS claims for Prometheus,
both Alertmanager replicas, and Grafana before stopping their writers. One-shot
copy Jobs mounted every Longhorn source read-only, ran as the corresponding
workload UID, and required matching directory, file-content, and symlink digests
before the claim templates changed. During cutover, the Prometheus Operator
resources remain paused and their old StatefulSets are removed before the new
NFS-backed StatefulSets are allowed to start.
Alertmanager loads `AlertmanagerConfig` resources cluster-wide and uses the
`home-lab-slack` config to send non-`Watchdog`, non-`none` severity alert
notifications to Slack.
The Slack incoming-webhook URL is stored in the SOPS-managed
`alertmanager-slack` Secret.

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

K3s control-plane metric collection is deliberately split between the chart's
dedicated API server target and its K3s server target. The chart-generated K3s
`/metrics` endpoint is target-dropped and replaced by an additional
chart-managed ServiceMonitor that drops duplicate `apiserver_*` samples at
ingestion; the original cAdvisor and probe endpoints remain active. This
workaround is necessary because the pinned PushProx subchart replaces custom
endpoint metric relabeling whenever Rancher cluster labels are enabled. The
dedicated API server target retains the SLI histogram used by Rancher's API
availability rules.

The Ansible-managed K3s configuration also disables unused, high-cardinality API
request, response, watch, and etcd histogram families at the source. After
applying that host configuration, roll the K3s servers through
`infrastructure/ansible/playbooks/k3s_server.yml`; the playbook's `serial: 1`
policy preserves etcd quorum and API availability while each server restarts.

Roll this change out in two stages. First let Fleet reconcile the monitoring
values and verify that both the dedicated `apiserver` target and the filtered
K3s server target are healthy. Then run the K3s server playbook from
`infrastructure/ansible/`; it restarts and returns each server before moving to
the next. Afterward, run the role's `validation` entrypoint and compare
`prometheus_tsdb_head_series`, ingestion rate, K3s process RSS, and the API SLO
rules with the pre-change baseline.

## Resource request baseline

Requests are reviewed against 14 days of five-minute CPU and memory samples,
using the busiest replica at each sample before taking p95. Prometheus retains
its 400m CPU request and now requests 4Gi memory; the observed p95 was about
307m CPU and 3,348Mi memory, while p99 memory was about 3,609Mi. Grafana's main,
dashboard-sidecar, and proxy containers request 40m CPU and 528Mi memory in
total, above the pod p95 of about 12m CPU and 449Mi memory. Lower-usage
components, including Alertmanager, the operator, adapter, node exporter,
kube-state-metrics, PushProx, and the chart proxies, use smaller requests with
explicit per-container memory. The Grafana sidecar request is configured at the
chart-wide `grafana.sidecar.resources` path because the chart applies that
single value to its sidecars. Node exporter requests `5m` CPU on each node and
remains CPU-burstable.

`kube-state-metrics` requests `192Mi` and is capped at `384Mi`. The previous
`160Mi` limit was below its startup working set at the cluster's current object
count and caused immediate `OOMKilled` restarts after observability resumed.

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
