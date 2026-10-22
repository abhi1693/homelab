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

The API pod-log source was removed during the node collector handover. Do not
restore it alongside permanent node pod forwarding: use the staged handover and
rollback procedure in [incident coverage](../../../../../docs/runbooks/incident-coverage.md).
Verify both event replicas are Ready on distinct nodes, fresh events reach Loki,
and node pod collection remains healthy after a configuration change.

The pinned chart is Grafana Alloy 1.13.1 (Alloy 1.20.1). Requests remain 55m CPU
and 224Mi memory per replica across Alloy and its config reloader. Use measured
usage before changing these bounds.
