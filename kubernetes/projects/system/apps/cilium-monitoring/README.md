# Cilium and Hubble incident coverage

This bundle discovers Cilium agents and operators plus node-local Hubble
metrics through explicit PodMonitors. Resources live in
`cattle-monitoring-system`; selectors discover the existing Cilium pods in
`kube-system`. It depends on the Cilium Fleet handoff and the upstream
kube-prometheus-stack installation, without adding Prometheus dependencies to
the CNI runtime chart.

Each scrape runs every 30 seconds with a 10-second timeout. Per-target sample
limits bound collection: 10,000 for each agent and 5,000 for each operator or
Hubble exporter. An exceeded sample limit fails the scrape and triggers the
coverage alert instead of silently admitting unbounded series. Hubble exports
namespace-scoped aggregates, not IP, pod, workload, or DNS-query labels. DNS
metrics appear only when DNS flows are observed; enabling these metrics does
not install L7 policy or intercept extra traffic.

Expected healthy targets are one agent and Hubble exporter for every cluster
node, plus both configured operators. Coverage rules compare against node and
deployment inventory, so they detect removed targets as well as failed
scrapes. Additional rules detect persistent failing Cilium controllers and
sustained loss from the perf-event ring or observer queue. Hubble history-ring
overwrites are excluded because they concern the bounded recent-flow cache,
not the metrics consumer. Packet and policy drops remain diagnostic metrics;
expected denied traffic does not produce a blanket Slack alert.

Use these PromQL queries during an incident:

```promql
count by (job) (up{job=~"cilium-agent|cilium-operator|hubble"} == 1)
max by (node) (cilium_controllers_failing)
sum by (node, reason, direction) (rate(cilium_drop_count_total[5m]))
sum by (node, source, destination, reason) (rate(hubble_drop_total[5m]))
sum by (node, source) (rate(hubble_lost_events_total[5m]))
```

For unhealthy coverage, inspect the selected PodMonitor, Prometheus target
error, Cilium readiness, and listeners 9962/9963/9965. Read agent/operator logs
from the node-local log collector. Check CPU, memory, and event loss when
investigating missing Hubble observations; a successful scrape alone does not
prove every flow was observed. Cilium/Hubble and K3s/kernel logs should be
correlated by the `node` label.

Validate configuration and alert behavior with
`scripts/check-cilium-observability.py`. Validate the rendered bundle using
`kubectl kustomize kubernetes/projects/system/apps/cilium-monitoring`, then a
server-side dry run when cluster access is available. Live changes reconcile
through Fleet.
