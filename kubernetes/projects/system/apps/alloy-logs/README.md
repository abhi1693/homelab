# Alloy Logs

This bundle runs Grafana Alloy as the cluster application log collector.

## Runtime Shape

- Namespace: `cattle-monitoring-system`
- Chart: Grafana `alloy`
- Release: `alloy-logs`
- Controller type: single Deployment replica
- Disruption budget: `minAvailable: 1`
- Output: Loki gateway at
  `http://loki-gateway.cattle-monitoring-system.svc.cluster.local/loki/api/v1/push`
- Metrics: `ServiceMonitor` enabled
- Requests: 55m CPU and 224Mi memory across Alloy and its config reloader

The Alloy configuration discovers running pods, drops noisy system namespaces,
adds stable labels such as namespace, pod, container, node, app, part-of, and
component, then forwards logs to Loki.

The collector remains a singleton because a second independent Kubernetes log
source would ingest the same pod streams twice. Its PodDisruptionBudget blocks
voluntary eviction, including descheduler balancing, so log collection does not
develop a known gap while the pod is healthy.

The requests retain headroom over the 14-day pod p95 of approximately 25m CPU
and 179Mi memory.

## Dependencies

Fleet orders this bundle after `system-helm-repositories` and `loki-helmop`.
Loki should be healthy before this collector is expected to deliver logs.

## Network Boundary

Prometheus can scrape Alloy on port `12345`. Egress allows DNS, Kubernetes API
access for discovery, and writes to Loki on port `8080`.

## Operating Notes

- Update namespace filters in `values.yaml` when adding or removing noisy
  system namespaces.
- Keep label additions low-cardinality; log labels affect Loki query cost.
- Validate with Loki when changing the write endpoint or relabeling pipeline.
- Remove or relax the PodDisruptionBudget deliberately before a voluntary node
  drain that must move the singleton collector.
