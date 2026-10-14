# Alloy Logs

This bundle runs Grafana Alloy as the cluster pod log and Kubernetes event collector.

## Runtime Shape

- Namespace: `cattle-monitoring-system`
- Chart: Grafana `alloy`
- Release: `alloy-logs`
- Controller type: two clustered Deployment replicas with hard hostname anti-affinity
- Disruption budget: `minAvailable: 1`
- Output: Loki gateway at
  `http://loki-gateway.cattle-monitoring-system.svc.cluster.local/loki/api/v1/push`
- Metrics: `ServiceMonitor` enabled at 60s
- Requests: 55m CPU and 224Mi memory per replica across Alloy and its config reloader

The Alloy configuration discovers pods in every namespace, including system
namespaces and retained completed pods. It adds namespace, pod, container, node,
app, part-of, and component labels. Kubernetes events are collected as JSON with
`job="kubernetes-events"` and `cluster="local"`.

Both pod and event sources opt into Alloy clustering. Peers distribute source
ownership, so adding a replica does not intentionally collect every stream twice.
Hard anti-affinity keeps peers on distinct nodes; rolling updates and the
`minAvailable: 1` budget retain a collector during planned disruption. Transient
replays during reassignment remain possible. This is not exactly-once delivery.

API log collection cannot recover deleted pods or every rotated/previous container
log, and does not collect host journald logs. Positions and pending batches remain
ephemeral. See the [coverage and HA review](../../../../../docs/runbooks/monitoring-ha-review.md)
for the node-local collection and storage migration still required.

## Dependencies

Fleet orders this bundle after `system-helm-repositories` and `loki-helmop`.
Loki should be healthy before this collector is expected to deliver logs.

## Network Boundary

Prometheus can scrape Alloy on port `12345`. Egress allows DNS, Kubernetes API
access for discovery and log/event reads, and writes to Loki on port `8080`.
Peers communicate bidirectionally on TCP/12345. A Cilium policy restricts API
egress to the `kube-apiserver` entity on 443/6443. Runtime policies explicitly
target `cattle-monitoring-system`; only HelmOp and values belong in `fleet-local`.

## Operating Notes

- Keep system namespaces included; control volume with measured retention and
  label budgets rather than hiding incident logs.
- Keep label additions low-cardinality; log labels affect Loki query cost.
- Validate with Loki when changing the write endpoint or relabeling pipeline.
- Verify both replicas are Ready on distinct nodes and see each other before
  draining a node; check drops and rejections after membership changes.

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
