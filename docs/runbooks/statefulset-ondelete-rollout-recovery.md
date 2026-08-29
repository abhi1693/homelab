---
title: StatefulSet OnDelete Rollout Recovery
---

# KubeStatefulSetUpdateNotRolledOut With OnDelete

## Meaning

An `OnDelete` StatefulSet can have a valid new update revision while old pods
remain indefinitely. The controller intentionally waits for an operator to
delete each ordinal. In this cluster, Valkey uses this strategy to avoid an
automatic primary and Sentinel quorum disruption.

## Impact

- `KubeStatefulSetUpdateNotRolledOut` continues firing until every ordinal uses
  the update revision.
- Deleting the current primary first can cause an avoidable failover or outage.
- Deleting multiple replicas together can lose Sentinel quorum and data-service
  availability even though all PVCs are healthy.

## Diagnosis

```sh
kubectl -n valkey get statefulset valkey-node \
  -o custom-columns='NAME:.metadata.name,READY:.status.readyReplicas,UPDATED:.status.updatedReplicas,CURRENT:.status.currentRevision,UPDATE:.status.updateRevision'

kubectl -n valkey get pods -l app.kubernetes.io/name=valkey \
  -o custom-columns='NAME:.metadata.name,READY:.status.containerStatuses[*].ready,REVISION:.metadata.labels.controller-revision-hash'

kubectl -n valkey exec valkey-node-0 -c valkey -- \
  valkey-cli -p 26379 SENTINEL MASTERS

for ordinal in 0 1 2; do
  kubectl -n valkey exec "valkey-node-${ordinal}" -c valkey -- \
    valkey-cli INFO replication \
    | grep -E '^(role|master_host|master_link_status|connected_slaves):'
done
```

Use the Sentinel output's actual master-set name. The local set is `valkey`;
do not assume a generic name such as `mymaster`. Confirm all Longhorn-backed
PVCs are healthy before changing an ordinal.

## Mitigation

Normal changes belong in Git and Fleet. Recreating live ordinals is a
break-glass operation and must be sequential:

1. Delete one old-revision replica ordinal.
2. Wait for that exact ordinal to become Ready on the update revision and for
   `master_link_status:up`.
3. Repeat for the other old-revision replica.
4. If the old revision remains on the primary, ask Sentinel to fail over using
   the discovered set name.
5. Wait until the new primary reports both replicas connected and both replicas
   report an up master link.
6. Delete the final old-revision ordinal and wait for it to rejoin.

Example commands:

```sh
kubectl -n valkey delete pod valkey-node-1
kubectl -n valkey wait --for=condition=Ready pod/valkey-node-1 --timeout=180s

kubectl -n valkey exec valkey-node-0 -c valkey -- \
  valkey-cli -p 26379 SENTINEL FAILOVER valkey
```

Do not proceed to the next ordinal until replication and Sentinel agree.

## Verification

- `readyReplicas` and `updatedReplicas` equal the StatefulSet replica count.
- Every pod has the update revision label.
- One pod is primary, two are replicas, the primary has two connected replicas,
  and both replica links are up.
- Alertmanager no longer contains `KubeStatefulSetUpdateNotRolledOut`.

## Rollback

Do not roll back by deleting every pod. Revert the chart or values in Git, let
Fleet publish the prior revision, and use the same one-ordinal-at-a-time process.

## References

- `kubernetes/projects/database/apps/valkey/README.md`
- Kubernetes StatefulSet update strategies: <https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/#update-strategies>
