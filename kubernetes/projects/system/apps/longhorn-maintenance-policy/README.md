# Longhorn maintenance policy

Fleet owns the existing `node-drain-policy` and
`concurrent-replica-rebuild-per-node-limit` Settings in `longhorn-system`.
It also owns snapshot-heavy-task-concurrent-limit. It adopts those manager-created Settings, retains them if the bundle is
removed, and does not create or relabel the namespace. Bootstrap inventory and
the Longhorn chart template declare the same values.

`block-for-eviction` requires Longhorn to evacuate every replica before allowing
a node drain to complete. This is stricter than the upstream
`block-if-contains-last-replica` default, which protects the last copy but can
leave other local replicas in place or restart them before a reboot.

Complete evacuation moves more data and can make drains slower or refuse a
drain without enough remaining disk capacity. Plan worker CPU/memory and disk
headroom before maintenance; never bypass disruption budgets, replica counts,
Longhorn anti-affinity or replenishment safety to force progress. Before taking
a worker offline, verify that no replica remains starting/running/stopping on
it. Existing stopped/failed historical replica records are retained for
inspection and are not manually deleted.

Replica recovery admits one incoming rebuild per node. Concurrent recovery on
the shared root NVMe disks can delay embedded etcd and applications; serial
admission trades longer queues for disk and network headroom. Existing copies
finish without interruption. Replica counts, timeouts and backups stay intact.

The separate [storage pools bundle](../longhorn-storage-pools/README.md)
reconciles control-plane/worker tags and volume selectors. This bundle owns
the replica rebuild admission limit.

References: [Longhorn 1.12.1 node drain policy](https://longhorn.io/docs/1.12.1/references/settings/#node-drain-policy).


Heavy snapshot operations (purge/clone) are admitted one at a time per node,
reduced from five. This is separate from the one-rebuild-per-node limit.
Admission serializes new heavy work rather than cancelling running operations;
recovery can take longer while foreground applications retain more disk/CPU
headroom. Replica counts, instance-manager guarantees and fsync stay intact.

The system-managed CSI resource Setting is also Git-owned. Its JSON matches
bootstrap inventory and the Fleet HelmChartConfig override, so an existing
installation receives the reviewed requests without waiting for a bootstrap
playbook. Only the three node-sidecar CPU requests change.
