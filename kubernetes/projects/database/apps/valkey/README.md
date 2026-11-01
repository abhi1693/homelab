# Valkey

This bundle installs the shared Valkey cache and queue service for the lab
through a Fleet `HelmOp`.

## Runtime Shape

- Namespace: `valkey`
- Chart: Bitnami `valkey` `6.1.11` from
  `oci://registry-1.docker.io/bitnamicharts/valkey`
- Release: `valkey`
- Runtime: Valkey and Sentinel `9.1.2`, pinned to ARM64-capable image digests
- Architecture: replicated Valkey with Sentinel enabled
- Storage: three retained Longhorn-backed 4Gi PVCs, each with three storage
  replicas; `pvc-expansion.yaml` owns the online expansion of the existing
  StatefulSet claims while the chart's immutable claim template remains the
  bootstrap default
- Metrics: chart exporter and `ServiceMonitor` are enabled
- Memory guardrail: replicas use `maxmemory 3gb` with `maxmemory-policy
  noeviction`, leaving approximately 1Gi below the 4Gi container limit for
  allocator, replication, and AOF overhead. The `ValkeyMemoryDatasetHigh`
  alert fires above 2.5Gi, with a critical alert above 2.75Gi; policy drift and
  any evictions are also critical alerts.
- Replica data-container memory: operator-managed `1536Mi` request and `4Gi`
  limit covering startup loading, full synchronization, and AOF rewrite
  overhead; the recommendation profile remains observe-only

The chart runs with authentication disabled. Access control is provided by the
cluster network boundary in the separate `valkey-networkpolicy` bundle.

`noeviction` is intentional: reaching the configured ceiling returns write
errors instead of silently evicting shared queue or cache keys. Treat the
2.5Gi warning as the point to reduce key retention or expand capacity through
GitOps; do not raise the live setting manually.

Valkey maintains one primary and two application-level replicas on separate
nodes through required Pod anti-affinity and topology spread. Placement has no
hostname-specific exclusions. The StatefulSet uses `OnDelete` so placement
changes do not automatically roll the healthy
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

- Change chart behavior in `values.yaml`, not by patching live workloads.
- The chart pin in `helmop.yaml` is excluded from Renovate. Chart updates can
  change the pod revision even when digest-pinned containers stay identical;
  schedule them with the guarded `OnDelete` rollout procedure.
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
- Review historical memory, replication, and persistence metrics before changing
  replica requests or limits. Apply changes through the guarded `OnDelete`
  rollout strategy.
- Validate with a server-side dry run when a cluster context is available.
- Follow
  [`docs/runbooks/statefulset-ondelete-rollout-recovery.md`](../../../../../docs/runbooks/statefulset-ondelete-rollout-recovery.md)
  when revisions differ; never recreate multiple ordinals together.

## Logical database allocation

DevFeed reserves logical database **10** for sessions, RQ queues, job logs,
caches and rate limits. NetBox uses databases **1** and **2**, and ShipyardHQ
uses **20**. Check each consuming application's manifests before allocating a
new logical database. Preserve values and expiration times during any migration;
Redis 8 DUMP payloads are not directly compatible with this Valkey release.

The 4Gi data-container limit provides room for both datasets during `swapdb`
full synchronization, allocator overhead and AOF rewrite activity. Change memory
or chart behavior only through a guarded serial rollout with replication and
Sentinel-quorum checks between members.

## Resource review — 28 October 2026

Fourteen-day data-container working set peaked at 3104Mi and p99 was 2140Mi;
recent p95 was 2099Mi. Each data replica now reserves 2560Mi and 100m CPU,
retaining the 4Gi limit, `maxmemory 3gb`, persistence, Sentinel quorum, and
`OnDelete` update strategy. Memory requests for Sentinel, exporter, and kubectl
helpers are 48Mi, 64Mi, and 64Mi respectively, above observed 33Mi/46Mi/54Mi
peaks. Do not divide the replicated dataset by the replica count.

Applying the new pod template requires the existing replica-first, one-ordinal
at-a-time break-glass recovery procedure, with replication and Sentinel checks
between ordinals; publishing the template alone does not resize existing pods.

Training instructor NetBox reserves logical databases **12** (tasks) and **13** (cache). These share the existing Sentinel service and memory budget.
