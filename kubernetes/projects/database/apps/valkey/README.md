# Valkey

This bundle installs the shared Valkey cache and queue service for the lab
through a Fleet `HelmOp`.

## Runtime Shape

- Namespace: `valkey`
- Chart: Bitnami `valkey` `6.1.11` from
  `oci://registry-1.docker.io/bitnamicharts/valkey`
- Release: `valkey`
- Architecture: replicated Valkey with Sentinel enabled
- Storage: three retained Longhorn-backed 4Gi PVCs, each with three storage
  replicas; `pvc-expansion.yaml` owns the online expansion of the existing
  StatefulSet claims while the chart's immutable claim template remains the
  bootstrap default
- Metrics: chart exporter and `ServiceMonitor` are enabled
- Replica data-container memory: operator-managed `1536Mi` request and `4Gi`
  limit covering startup loading, full synchronization, and AOF rewrite
  overhead; the recommendation profile remains observe-only

The chart runs with authentication disabled. Access control is provided by the
cluster network boundary in the separate `valkey-networkpolicy` bundle.

Valkey maintains one primary and two application-level replicas on separate
nodes. `k8s-rpi1` is excluded after its Sentinel repeatedly wedged in DNS-driven
tilt while the colocated Valkey data process remained healthy. The StatefulSet
uses `OnDelete` so placement changes do not automatically roll the healthy
primary and quorum. Capacity recovery must proceed one replica at a time,
verifying replication and Sentinel quorum between ordinals. With explicit
break-glass authorization, recreate failed replicas against the expanded
Fleet-managed template, fail over to a healthy expanded replica, then recreate
the former primary. Otherwise use temporary Fleet-managed recovery resources
and partitions, removing those resources and restoring `OnDelete` afterward.

Each backing volume also uses three Longhorn replicas, resulting in 36Gi of nominal
scheduled block capacity and allowing each PVC to tolerate replica loss at the
block layer. Sentinel still provides application-level failover.
This service is not an independent backup, so durable producers must remain
able to reconstruct queue or cache state.

## Client Contract

Applications should connect through Sentinel when they need failover-aware
Redis-compatible access:

```text
valkey.valkey.svc.cluster.local:26379
sentinel set: valkey
```

Clients that cannot speak Sentinel must use the chart-managed writable-primary
service:

```text
valkey-primary.valkey.svc.cluster.local:6379
```

Sentinel updates the `isPrimary` pod label after election, and the service
selects only that pod. The narrowly scoped chart RBAC permits the Valkey service
account to get and patch that label on the three named StatefulSet pods; `get`
is required by `kubectl label` before it sends the patch.

Direct Valkey traffic uses port `6379`; Sentinel uses port `26379`. App READMEs
should document their logical DB index or key namespace when they use this
shared service.

## Network Boundary

`valkey-networkpolicy` allows access from approved clients such as NetBox,
Wardn Hub, ShipyardHQ, and Harbor. Prometheus can scrape metrics on
port `9121`. Valkey pods can also talk to each other on Valkey and Sentinel
ports. Egress to the in-cluster Kubernetes API is limited to the service VIP on
TCP `443`, its three control-plane endpoints on TCP `6443`, and a Cilium policy
for the `kube-apiserver` identity so Service translation remains allowed. The
primary-label controller needs that path to patch the elected pod's `isPrimary`
label.

## Operating Notes

The September 13, 2026 capacity recovery verified all three expanded pods with
zero restarts, two synchronized replicas, Sentinel quorum, and an application
write acknowledged by both replicas. Temporary recovery resources were removed
and the guarded `OnDelete` strategy was restored.

- Change chart behavior in `values.yaml`, not by patching live workloads.
- The chart pin in `helmop.yaml` is excluded from Renovate. Chart updates can
  change the pod revision even when digest-pinned containers stay identical;
  schedule them with the guarded `OnDelete` rollout procedure. The automatic
  `6.2.19` update was reverted because its pod-template changes were only chart
  and application-version labels. The running image digests remain unchanged.
- Keep client additions paired with `valkey-networkpolicy` updates.
- Keep the retained PVC policy in mind before deleting or renaming the release.
- Keep `pvc-expansion.yaml` at or above the live retained-claim size. Kubernetes
  does not shrink PVCs, and the chart's StatefulSet claim template cannot resize
  claims that already exist.
- Preserve each retained PVC's explicit volume binding during expansion.
  Replacement volumes inherit the three-replica storage policy.
- `repl-diskless-load swapdb` prevents full replica synchronization from
  requiring another dataset-sized temporary RDB file on the data volume. Keep
  the data-container limit large enough to hold both datasets during the swap.
- Review recommendation-engine observations before changing the replica
  request or limit; Valkey remains observe-only because automatic changes are
  incompatible with its guarded `OnDelete` rollout strategy.
- Validate with a server-side dry run when a cluster context is available.
- Follow
  [`docs/runbooks/statefulset-ondelete-rollout-recovery.md`](../../../../../docs/runbooks/statefulset-ondelete-rollout-recovery.md)
  when revisions differ; never recreate multiple ordinals together.

## Logical database allocation

DevFeed reserves logical database **10** for its sessions, RQ queues, job logs,
caches and rate limits. Its migration must preserve values and expiration times;
Redis 8 DUMP payloads are not directly compatible with this Valkey release.
The original migration began with approximately 119MiB. By September 13 the
shared dataset had grown beyond 1GiB, while replicas retained approximately
1.4GiB startup datasets. The 4Gi limit provides room for both datasets during
`swapdb` full synchronization, allocator overhead, and AOF rewrite activity.
Existing clients' databases and keys remain unchanged.
