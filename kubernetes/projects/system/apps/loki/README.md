# Loki

This bundle installs the local log backend for the Rancher Monitoring namespace
through a Fleet `HelmOp`.

## Runtime Shape

- Namespace: `cattle-monitoring-system`
- Chart: Grafana `loki`
- Release: `loki`
- Mode: single-binary Loki
- Storage: filesystem TSDB on a retained 20Gi NFS PVC
- Retention: 168 hours
- Gateway: enabled
- ServiceMonitor enabled at 60s; unused chart recording rules disabled
- Single-binary requests: 25m CPU and 448Mi memory
- Gateway requests: 5m CPU and 32Mi memory

Read, write, and backend microservice replicas are disabled. This is a compact
home-lab deployment, not a horizontally scaled Loki topology.

The migration stages a retained `loki-data-nfs-migration` claim before Loki is
stopped and copied. The chart fixes the final claim name at `storage-loki-0`,
so the verified staging copy remains the rollback source while Fleet recreates
that final claim on `nfs-shared-retain`. The chart's ARM64 selector is restored
only after the staging-to-final copy produces the same digest as the original
Longhorn-to-staging copy. The copy Jobs run as Loki UID/GID `10001` and require
matching directory, file-content, and symlink digests at both boundaries.
The bundle namespaces only its HelmOp and generated values in `fleet-local`;
the data claim and Loki NetworkPolicy belong in `cattle-monitoring-system`.

The requests use a 14-day p95 review. The Loki pod measured approximately 19m
CPU and 422Mi memory at p95; its rules sidecar separately requests 5m CPU and
96Mi memory so the scheduler accounts for that container too. The 1Gi Loki
memory limit is unchanged.

## Producers and Consumers

`alloy-logs` and `alloy-faro` write logs through the Loki gateway. Grafana and
Prometheus are allowed to query or scrape Loki according to the network policy.

## Network Boundary

`loki-boundary` allows ingress from Alloy log pipelines, Grafana, Prometheus,
and Loki pods themselves. Egress is limited to DNS and Loki internal
communication ports. `loki-apiserver-access` uses Cilium's `kube-apiserver`
entity to allow only the 443/6443 API path required by the rules sidecar.

## Operating Notes

- Increase the Longhorn PVC and memory limits before extending retention
  materially.
- Keep retention changes in `values.yaml`; do not tune the live StatefulSet by
  hand.
- Keep the Loki self-monitor interval aligned with the cluster-wide 60-second
  scrape policy; the previous 15-second chart default added ingestion without
  useful extra resolution for this home-lab workload. The bundled recording
  rules are disabled because their one-minute rate windows require 15-second
  samples, and no live dashboard consumes their output series.
- Validate alongside `alloy-logs` when changing gateway or service naming.
