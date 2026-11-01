# Alloy Kubernetes Events

This bundle retains the `alloy-logs` Helm release and two clustered Deployment
replicas for Kubernetes events. Node-local container files and K3s/kernel
journals belong to [alloy-node-logs](../alloy-node-logs/README.md).

The collectors run in `cattle-monitoring-system` on distinct control-plane nodes
with hard hostname anti-affinity, zero-unavailable rolling updates and a
`minAvailable: 1` disruption budget. Both event sources opt into Alloy clustering
so peers distribute ownership. Reassignment can replay events; this is not
exactly-once delivery. The release and ServiceMonitor names remain stable.

Events are JSON with `job="kubernetes-events"` and `cluster="local"`. Request,
trace and event identifiers remain in the body. Output goes through the Loki
gateway at `http://loki-gateway.cattle-monitoring-system.svc.cluster.local/loki/api/v1/push`.
Writes retry HTTP 429 and transient server failures with 1s–1m backoff and
20 retries. Pending batches and clustering state are ephemeral; inspect
`loki_write_dropped_entries_total` and Loki rejections to verify delivery.

Prometheus scrapes both replicas every 60 seconds on TCP/12345. Policies allow
DNS, the Kubernetes API for event reads, Loki gateway writes on TCP/8080, and
bidirectional peer communication on TCP/12345. A Cilium policy restricts API
egress to the `kube-apiserver` entity on 443/6443. Runtime policies explicitly
target `cattle-monitoring-system`; only HelmOp and values belong in `fleet-local`.
Fleet orders installation after `system-helm-repositories` and `loki-helmop`.

Node-local Alloy owns pod logs; this bundle collects Kubernetes events. Do not
enable a duplicate API pod-log source. See the handover and recovery procedure in
[incident coverage](../../../../../docs/runbooks/incident-coverage.md).
Verify both event replicas are Ready on distinct nodes, fresh events reach Loki,
and node pod collection remains healthy after a configuration change.

The pinned chart is Grafana Alloy 1.13.1 (Alloy 1.20.1). Each replica requests 15m CPU and 128Mi memory across Alloy and its config
reloader. Alloy is capped at 100m CPU with `GOMAXPROCS=1`; its reloader is
capped at 25m. Event bursts may take longer to export under these limits.

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom. The CPU ceilings
above supersede the former unlimited burst policy. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `cattle-monitoring-system/alloy-logs/alloy` | 50m → 10m | 192Mi → 96Mi | 256Mi → 384Mi |

## Fleet status refresh

The HelmOp metadata annotation `home-lab.io/status-reconcile-at` records the
latest Git-managed request to refresh its health summary after workload recovery.
Follow the [operational workflow](../../../../../README.md#operational-workflow)
and verify both the child bundle and live workload before requesting another refresh.
