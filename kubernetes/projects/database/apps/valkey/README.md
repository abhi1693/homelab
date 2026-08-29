# Valkey

This bundle installs the shared Valkey cache and queue service for the lab
through a Fleet `HelmOp`.

## Runtime Shape

- Namespace: `valkey`
- Chart: Bitnami `valkey` from `oci://registry-1.docker.io/bitnamicharts/valkey`
- Release: `valkey`
- Architecture: replicated Valkey with Sentinel enabled
- Storage: three retained Longhorn-backed 4Gi PVCs, each with three storage
  replicas; `pvc-expansion.yaml` owns the online expansion of the existing
  StatefulSet claims while the chart's immutable claim template remains the
  bootstrap default
- Metrics: chart exporter and `ServiceMonitor` are enabled
- Replica data-container memory: operator-managed `374Mi` request and `768Mi`
  limit covering startup loading, full synchronization, and AOF rewrite
  overhead; the recommendation profile remains observe-only

The chart runs with authentication disabled. Access control is provided by the
cluster network boundary in the separate `valkey-networkpolicy` bundle.

Valkey maintains one primary and two application-level replicas on separate
nodes. `k8s-rpi1` is excluded after its Sentinel repeatedly wedged in DNS-driven
tilt while the colocated Valkey data process remained healthy. The StatefulSet
uses `OnDelete` so placement changes never roll the healthy primary and quorum
automatically; an operator must recreate only the affected ordinal after
verifying the primary, replica, Sentinel quorum, and retained PVC health. Each
backing volume also uses three Longhorn replicas, resulting in 36Gi of nominal
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
- Keep client additions paired with `valkey-networkpolicy` updates.
- Keep the retained PVC policy in mind before deleting or renaming the release.
- Keep `pvc-expansion.yaml` at or above the live retained-claim size. Kubernetes
  does not shrink PVCs, and the chart's StatefulSet claim template cannot resize
  claims that already exist.
- Add any replacement PVC's Longhorn volume ID to the scoped override before
  considering its storage replication reduced. The live volume IDs are pinned
  because Fleet must preserve this immutable binding while expanding a claim.
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
