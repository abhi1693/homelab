# Rancher Monitoring

The Linux-only cluster disables the chart's `windowsExporter` dependency so it
does not render an unschedulable Windows DaemonSet. Grafana's `init-chown-data`
container is explicitly bounded at `5m`/`16Mi` requests and `100m`/`64Mi`
limits; namespace defaults cover other chart-generated hook or init containers
that omit resource keys without adding a generic CPU limit.

Fleet wrapper for the Rancher Monitoring charts in `cattle-monitoring-system`.

It owns two HelmOps:

- `rancher-monitoring-crd`, which installs the Prometheus Operator CRDs.
- `rancher-monitoring-stack`, which installs Rancher's monitoring stack.

The stack is pinned to chart version `109.0.3+up80.9.1-rancher.14` and starts as
cluster-infrastructure monitoring for Rancher and K3s. Prometheus is configured
for one replica with a retained `20Gi` NFS PVC, `14d` retention, `16GiB` retention
size, a 4Gi memory request, and a 5Gi memory limit. The global Prometheus scrape
interval is `60s`.
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
controller metrics `Service` and `ServiceMonitor` on port `8080`, restricted to
Rancher Monitoring by NetworkPolicy. `cloudflare-tunnel-health` alerts when
fewer than two connector targets are healthy, a connector has fewer than four
HA edge connections, the connector Deployment loses readiness, connector
configuration versions disagree, origin proxy connections fail, the tunnel's
5xx rate stays above 5% with meaningful traffic, the controller has no leader,
or controller reconciliation reports errors.

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
temperatures are shown as compact bar gauges, with the historical trend kept
separate for correlation. NVMe temperature panels use the kernel hwmon
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
iowait on the Raspberry Pi nodes. It also alerts when Raspberry Pi throttling
metrics cannot be collected, when firmware throttling is active, or when a
throttling condition has occurred since the last reboot.

`smartctl-exporter` scrapes the host-level `prometheus-smartctl-exporter`
service on each Raspberry Pi node for NVMe S.M.A.R.T. health. The host service is
installed by the Ansible `smartctl_exporter` role because the current upstream
container image is not published for arm64. `raspberry-pi-nvme-smart-dashboard`
adds the Grafana view for SMART status, NVMe wear, available spare, temperature,
media errors, error-log growth, and lifetime IO.
