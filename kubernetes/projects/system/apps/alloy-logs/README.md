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
voluntary eviction so log collection does not develop a known gap while the pod
is healthy.

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

DevFeed JSON logs add bounded `service` and `severity` stream labels through the
namespace-specific processing stage. Request, job and trace identifiers remain in
the JSON body for investigation and Tempo links; they are not promoted to labels.
Other namespaces retain their existing processing.

Loki writes explicitly retry HTTP 429 and transient server failures with 1s–1m
backoff and 20 retries. Monitor `loki_write_dropped_entries_total` alongside Loki
rejections; successful HTTP readiness alone does not prove complete delivery.

Entries older than 336 hours are filtered before Loki batching, matching its
14-day retention/acceptance window. This prevents expired replay entries from
causing HTTP 400 batches. Monitor `loki_process_dropped_lines_total` with reason
`expired_retention` separately from permanent delivery failures. Keep this age
aligned with Loki when changing retention.
