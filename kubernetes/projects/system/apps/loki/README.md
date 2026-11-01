# Loki

The runtime is digest-pinned to Loki `3.6.17` on ARM64; chart `7.3.0` is retained.

This bundle installs the local log backend for the Rancher Monitoring namespace
through a Fleet `HelmOp`.

## Runtime Shape

- Namespace: `cattle-monitoring-system`
- Chart: Grafana `loki`
- Release: `loki`
- Mode: single-binary Loki
- Storage: filesystem TSDB on a retained 20Gi NFS PVC
- Retention: 336 hours (14 days)
- Gateway: two replicas with chart-provided hard hostname anti-affinity
- ServiceMonitor enabled at 60s; unused chart recording rules disabled
- Single-binary requests: 250m CPU and 768Mi memory; 2Gi memory limit
- Gateway requests: 5m CPU and 32Mi memory per replica

Read, write, and backend microservice replicas are disabled. This is a compact
home-lab deployment, not a horizontally scaled Loki topology. Two gateways remove
a proxy singleton, but the single Loki process and NAS remain failure points.
Filesystem storage must not simply be scaled up; a multi-writer deployment
requires a supported shared object store and a reviewed topology change.

The bundle namespaces its HelmOp and generated values in `fleet-local`;
the data claim and NetworkPolicy belong in `cattle-monitoring-system`.
The retained `loki-data-nfs-migration` claim is a rollback source, not active
Loki storage. Do not delete it without reviewing data retention.

## Producers and Consumers

`alloy-logs` and `alloy-node-logs` write logs through the Loki gateway. Grafana and
Prometheus are allowed to query or scrape Loki according to the network policy.

## Network Boundary

`loki-boundary` allows ingress from Alloy log pipelines, Grafana, Prometheus,
and Loki pods themselves. Egress is limited to DNS and Loki internal
communication ports. `loki-apiserver-access` uses Cilium's `kube-apiserver`
entity to allow only the 443/6443 API path required by the rules sidecar.

## Operating Notes

- Review NAS capacity and memory budgets before extending retention. The NFS
  claim size does not enforce a NAS quota.
- Keep retention changes in `values.yaml`; do not tune the live StatefulSet by
  hand.
- Keep the Loki self-monitor interval aligned with the cluster-wide 60-second
  scrape policy. The bundled recording
  rules are disabled because their one-minute rate windows require 15-second
  samples, and no live dashboard consumes their output series.
- Validate alongside `alloy-logs` when changing gateway or service naming.

## Stalled NFS WAL recovery

The WAL remains enabled on the retained NFS claim at `/var/loki/wal`. Graceful
shutdown flushes in-memory chunks, with a 300-second termination allowance for
new pods. A stable pod annotation records the Fleet-managed recovery for
[issue #138](https://github.com/abhi1693/home-lab/issues/138); it reopens stale
handles while preserving the WAL for replay. The original NFS invalidation
trigger remains unproven, and the NAS remains a failure point.

`LokiWALWritesStalled` alerts when incoming logs continue but the rolling
ten-minute successful WAL-record increase stays zero for five minutes. Unlike
readiness or received-line counters, it detects failed durable write progress.
It does not detect every partial-delivery failure or missing telemetry; keep
the Alloy drop alerts and verify fresh query results too. Follow the
[recovery runbook](../../../../../docs/runbooks/loki-stale-nfs-wal.md) for data
preservation, replay, loss accounting, rollback and the post-recovery observation
window. Validate alert scenarios with `python scripts/check-loki-observability.py`
from the repository root (requires `promtool` and PyYAML).

## Delivery headroom and alerts

The tenant budget is 8MiB/s with a 16MiB burst, increased from the implicit 4MiB/s
limit after measured replay bursts caused 429s. Alloy retries 429/5xx responses
with 1s–1m backoff for up to 20 retries. This mitigates transient loss, but does
not provide durable end-to-end delivery across collector pod replacement.
The monitoring rules alert on permanent Alloy drops, Loki rejections and Grafana
restarts. Validate log delivery and memory after rollout; revert rate/resource
settings through Git if write latency or memory pressure increases. Retention
and retained storage are unchanged.

`AlloyLogEntriesDropped` reports the last positive rolling ten-minute count per
collector pod and drop reason, rather than lifetime counters or retry attempts.
It fires immediately and stays firing for ten minutes after the expression
stops reporting drops. This bridges brief quiet gaps in a continuing incident;
the retained annotation describes the last positive evaluation, not new loss
throughout that hold. A resolved notification means no recent drops remain in
the evaluation and hold windows; it does not recover discarded evidence.
The fixed `data_loss: permanent` label identifies this loss alert for explicit
protection from availability or severity-based inhibition.

The count can include non-retryable failures: HTTP 4xx other than retry-enabled
429 responses are not retried. `ingester_error` is a generic drop reason and
does not prove retry exhaustion; `queue_is_full` and `batch_too_large` need local
queue/batch investigation. Read collector errors for the HTTP status and Loki
validation error, then compare rejection reasons, write latency, queue pressure,
and fresh query results. `too_far_behind` requires producer timestamp and
per-stream ordering checks; increasing retry counts alone does not fix it.

`LokiLogEntriesRejected` retains its five-minute hold and ten-minute count.
Rejections, collector drops, and WAL stalls carry the bounded
`incident: log-delivery` label so notifications can correlate those observations
without asserting a shared cause. Loki rejection and Alloy drop counters
describe different pipeline stages and must not be summed as unique lost logs.
Permanent-loss alerts must remain visible alongside backend or critical alerts.

Log retention, query lookback, and the maximum accepted entry age are 14 days. Alloy filters
expired Kubernetes entries before batching and counts them separately as
`loki_process_dropped_lines_total{reason="expired_retention"}`. Loki compaction
and asynchronous chunk deletion enforce retention; deletion is not instantaneous
at the 14-day boundary. Prometheus metric retention is independent.

The gateway resolves the Loki Service address when NGINX starts. Its explicit
upstream override avoids per-request DNS resolution. Keep readiness, push and
query paths valid, then verify fresh delivery, Alloy drop counters and gateway
logs after configuration changes.

## Native OTel node logs and retained replay

The existing gateway's `/otlp/v1/logs` route accepts node Alloy OTel export.
Explicit OTLP resource mappings preserve the existing `cluster`, `node`,
`namespace`, `container`, `pod`, `job` and other bounded compatibility labels.
Canonical OTel fields, boot IDs and original/observed timestamps remain
structured metadata. Existing event push clients keep their formats.

Time sharding places old replay into bounded time buckets, permitting replay
alongside newer records without increasing `max_chunk_age`. Both
`querier.query_ingesters_within` and the filesystem-only
`ingester.query_store_max_look_back_period` are 336h. In Loki 3.6.17 the latter
otherwise overrides the querier window with a calculated roughly 2h41m value,
making older ingester replay temporarily invisible. A pinned runtime fixture
checks fresh and three-hour-old records in the same stream. Remove/review the
filesystem-only option as part of an object-storage migration.

WAL replay is capped at 1GB to retain headroom within the existing 2Gi process
limit. This does not remove NFS failure dependencies or establish power-loss
durability. Keep WAL-progress, permanent-drop/rejection and node OTel alerts
visible together. See the [OS incident runbook](../../../../../docs/runbooks/incident-coverage.md)
for coverage, query examples and SSH evidence collection.

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `cattle-monitoring-system/loki/loki` | 250m → 100m | 768Mi → 768Mi | 2Gi → 2560Mi |

## Backend placement

The single-binary backend runs on ARM64 workers and excludes control-plane
nodes. Its retained NFS PVC and WAL remain in place. Two control-plane nodes
lost network connectivity during successive backend placements on 2026-10-28;
this correlation does not establish a root cause. Worker placement protects
embedded-etcd quorum from replay/NAS traffic while that failure is investigated.
The lightweight gateway replicas retain their existing placement.

## Fleet status refresh

The HelmOp metadata annotation `home-lab.io/status-reconcile-at` records the
latest Git-managed request to refresh its health summary after workload recovery.
Follow the [operational workflow](../../../../../README.md#operational-workflow)
and verify both the child bundle and live workload before requesting another refresh.
