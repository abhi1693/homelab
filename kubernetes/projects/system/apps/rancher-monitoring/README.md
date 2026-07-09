# Rancher Monitoring

Fleet wrapper for the Rancher Monitoring charts in `cattle-monitoring-system`.

It owns two HelmOps:

- `rancher-monitoring-crd`, which installs the Prometheus Operator CRDs.
- `rancher-monitoring-stack`, which installs Rancher's monitoring stack.

The stack is pinned to chart version `109.0.2+up80.9.1-rancher.8` and starts as
cluster-infrastructure monitoring for Rancher and K3s. Prometheus is configured
for one replica with a `20Gi` Longhorn PVC, `14d` retention, `16GiB` retention
size, and a `3Gi` memory limit. The global Prometheus scrape interval is `60s`.
The Prometheus OTLP metrics receiver is enabled for application OpenTelemetry
metrics and promotes common service resource attributes. Grafana also provisions
a `Tempo` datasource for the lightweight Tempo app in this project.
Alertmanager runs two replicas with `2Gi` PVCs. Grafana is exposed internally at
`grafana.home`, Prometheus at `prometheus.home`, and Alertmanager at
`alertmanager.home`. Grafana intentionally runs as a single
persisted `2Gi` instance because HA Grafana would need external
database/shared-session work that is not useful for the initial scope.
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
`effective_requests` rules estimate Kubernetes scheduler pressure per pod by
taking the larger of summed app-container requests and max init-container
request. Runtime usage panels continue to use cAdvisor CPU rate and memory
working-set metrics.

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
