# Alloy Logs

This bundle runs Grafana Alloy as the cluster application log collector.

## Runtime Shape

- Namespace: `cattle-monitoring-system`
- Chart: Grafana `alloy`
- Release: `alloy-logs`
- Controller type: single Deployment replica
- Output: Loki gateway at
  `http://loki-gateway.cattle-monitoring-system.svc.cluster.local/loki/api/v1/push`
- Metrics: `ServiceMonitor` enabled

The Alloy configuration discovers running pods, drops noisy system namespaces,
adds stable labels such as namespace, pod, container, node, app, part-of, and
component, then forwards logs to Loki.

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
