---
title: Longhorn Disk Available Space Alerts
---

# LonghornDiskAvailableSpaceAlerts

## Meaning

The `LonghornDiskAvailableSpaceLow` and
`LonghornDiskAvailableSpaceCritical` alerts fire when a Longhorn node disk has
too little schedulable space remaining.

The local alert rules calculate schedulable free space as:

```text
100 * (capacity - reservation - usage) / capacity
```

The warning alert fires below `15%` for 15 minutes. The critical alert fires
below `10%` for 10 minutes.

This is not the same as raw `df` free space. Longhorn subtracts the configured
disk reservation before deciding whether the disk has useful scheduling
headroom. Because Longhorn uses the filesystem that contains
`/var/lib/longhorn/`, non-Longhorn consumers on the same filesystem, such as
containerd image cache, can also reduce the alert value.

## Current Snapshot

On July 1, 2026, Prometheus was firing these Longhorn disk space alerts:

```text
LonghornDiskAvailableSpaceLow       warning   k8s-rpi1   11.8%
LonghornDiskAvailableSpaceLow       warning   k8s-rpi3    9.0%
LonghornDiskAvailableSpaceCritical  critical  k8s-rpi3    9.0%
```

The Longhorn orphan replica cleanup setting was already applied:

```text
orphan-resource-auto-deletion: replica-data
applied: true
orphan count: 0
```

The remaining alert pressure is therefore expected to come from active volume
data, host filesystem usage, or node-local runtime cache, not from known
cleanable Longhorn orphan CRs.

## Impact

- Longhorn may stop scheduling new replicas on affected node disks.
- Volume expansion or replica rebuilds can fail or remain pending.
- A second node or disk failure has less recovery headroom because Longhorn has
  fewer eligible places to rebuild replicas.
- If the Longhorn data path shares the node root filesystem, unrelated growth
  in containerd or logs can also create kubelet and system pressure.

## Diagnosis

Check the active Prometheus alerts:

```sh
kubectl get --raw \
  '/api/v1/namespaces/cattle-monitoring-system/services/http:rancher-monitoring-prometheus:http-web/proxy/api/v1/alerts' \
  | jq -r '
      .data.alerts[]
      | select(.labels.alertname | startswith("Longhorn"))
      | [
          .labels.alertname,
          .labels.severity,
          .state,
          .activeAt,
          (.labels.node // ""),
          (.labels.disk // ""),
          (.annotations.description // "")
        ]
      | @tsv'
```

Calculate the same schedulable free percentage from Longhorn node status:

```sh
kubectl -n longhorn-system get nodes.longhorn.io -o json \
  | jq -r '
      .items[] as $node
      | $node.status.diskStatus
      | to_entries[]
      | [
          $node.metadata.name,
          (.value.storageMaximum / 1024 / 1024 / 1024),
          (($node.spec.disks[.key].storageReserved // 0) / 1024 / 1024 / 1024),
          (.value.storageAvailable / 1024 / 1024 / 1024),
          ((.value.storageMaximum - .value.storageAvailable) / 1024 / 1024 / 1024),
          ((.value.storageAvailable - ($node.spec.disks[.key].storageReserved // 0)) / 1024 / 1024 / 1024),
          ((.value.storageAvailable - ($node.spec.disks[.key].storageReserved // 0)) / .value.storageMaximum * 100)
        ]
      | @tsv' \
  | awk '
      BEGIN {
        printf "%-10s %8s %8s %8s %8s %10s %7s\n", "NODE", "CAP", "RES", "AVAIL", "USED", "SCHEDFREE", "SFREE%"
      }
      {
        printf "%-10s %8.1f %8.1f %8.1f %8.1f %10.1f %7.1f%%\n", $1, $2, $3, $4, $5, $6, $7
      }'
```

Check whether Longhorn has cleanable orphan resources:

```sh
kubectl -n longhorn-system get settings.longhorn.io \
  orphan-resource-auto-deletion \
  -o jsonpath='{.value}{"\n"}{.status.applied}{"\n"}'

kubectl -n longhorn-system get orphans.longhorn.io
```

List the largest active Longhorn volumes by actual allocated size:

```sh
kubectl -n longhorn-system get volumes.longhorn.io -o json \
  | jq -r '
      .items[]
      | [
          .metadata.name,
          (.status.kubernetesStatus.namespace // ""),
          (.status.kubernetesStatus.pvcName // ""),
          (((.status.actualSize // 0) | tonumber) / 1024 / 1024 / 1024),
          (.status.robustness // "")
        ]
      | @tsv' \
  | sort -k4,4nr \
  | head -20
```

Check volume health. Space cleanup should not hide degraded or faulted volumes:

```sh
kubectl -n longhorn-system get volumes.longhorn.io -o json \
  | jq -r '
      .items[]
      | select((.status.robustness // "") != "healthy")
      | [
          .metadata.name,
          (.status.kubernetesStatus.namespace // ""),
          (.status.kubernetesStatus.pvcName // ""),
          (.status.robustness // "")
        ]
      | @tsv'
```

Use Ansible for read-only host filesystem inspection. The current node mapping
is `server-1` to `k8s-rpi1`, `server-2` to `k8s-rpi2`, `server-3` to
`k8s-rpi3`, and `worker-1` to `k8s-rpi4`.

```sh
cd infrastructure/ansible

ansible 'server-1,server-3' \
  -m ansible.builtin.shell \
  -a '
      set -eu
      hostname
      df -h /var/lib/longhorn /var/lib/rancher/k3s/agent/containerd 2>/dev/null || true
      sudo du -xhd1 /var/lib /var/lib/longhorn /var/lib/rancher/k3s/agent/containerd 2>/dev/null \
        | sort -h \
        | tail -40
    '
```

## Mitigation

Do not delete files manually from `/var/lib/longhorn/replicas` or other
Longhorn data directories. Clean active volume data through the owning
application or PVC workflow, and keep intended cluster state in Git.

First, confirm orphan cleanup is enabled. If it is not enabled, set
`longhorn.orphan_resource_auto_deletion` to `replica-data` in
`infrastructure/ansible/inventories/home/group_vars/k3s_nodes.yml`, then apply
and validate the Longhorn role:

```sh
cd infrastructure/ansible
ansible-playbook playbooks/longhorn.yml -e longhorn_target_hosts=server-1
ansible-playbook playbooks/longhorn.yml \
  -e longhorn_target_hosts=server-1 \
  -e longhorn_entrypoint=validation
```

If orphan cleanup is already enabled and the orphan count is zero, find whether
the pressure is active Longhorn data or non-Longhorn host usage.

For a healthy volume with only this condition:

```text
Scheduled=False
reason=LocalReplicaSchedulingFailure
message=insufficient storage
```

check whether the volume uses `dataLocality=best-effort` and is trying to place
a local replica on a node with too little scheduled-capacity headroom:

```sh
kubectl -n longhorn-system get volumes.longhorn.io <volume-name> \
  -o jsonpath='{.spec.dataLocality}{"\n"}{.spec.nodeID}{"\n"}'
```

If the owning workload does not need local replica affinity, prefer a
volume-level `dataLocality=disabled` override rather than reducing disk
reservation, increasing over-provisioning, or changing the global Longhorn
default. In this repo, current build-cache overrides are managed by
`kubernetes/projects/system/apps/longhorn-volume-overrides/`.

For active Longhorn data growth:

- Clean data through the owning application, for example registry garbage
  collection, monitoring retention changes, build cache cleanup, or media
  download cleanup.
- Commit durable retention, size, or scheduling policy changes to the
  relevant Fleet-managed app manifests.
- Avoid reducing Longhorn's disk reservation just to silence the alert. The
  current `25%` reservation is intentional root-disk headroom.

For node-local containerd image cache growth, prune unused images on the
affected hosts. This changes only node-local cache; running containers continue
to use their images, and future starts may need to re-pull images.

```sh
cd infrastructure/ansible

ansible 'server-1,server-3' \
  -m ansible.builtin.shell \
  -a 'sudo k3s crictl rmi --prune'
```

If image cache growth repeats, add durable kubelet image garbage collection
settings through `k3s_server.kubelet_args` and `k3s_agent.kubelet_args` in
Ansible after validating the current K3s kubelet flags. Apply the K3s role only
through the existing Ansible playbooks.

If the alert remains after cache cleanup and app-level data cleanup, treat it
as a capacity issue:

- add more disk capacity;
- move Longhorn data to a dedicated disk or filesystem;
- rebalance replicas only through supported Longhorn operations.

## Verification

Confirm Prometheus no longer reports firing Longhorn disk space alerts:

```sh
kubectl get --raw \
  '/api/v1/namespaces/cattle-monitoring-system/services/http:rancher-monitoring-prometheus:http-web/proxy/api/v1/alerts' \
  | jq -r '
      .data.alerts[]
      | select(.labels.alertname | test("^LonghornDiskAvailableSpace"))
      | [.labels.alertname, .labels.severity, .state, (.labels.node // ""), (.annotations.description // "")]
      | @tsv'
```

The command should return no `firing` alerts after the `for` windows expire.

Confirm every Longhorn disk is above the warning threshold:

```sh
kubectl get --raw \
  '/api/v1/namespaces/cattle-monitoring-system/services/http:rancher-monitoring-prometheus:http-web/proxy/api/v1/query?query=100%20*%20(longhorn_disk_capacity_bytes%20-%20longhorn_disk_reservation_bytes%20-%20longhorn_disk_usage_bytes)%20%2F%20longhorn_disk_capacity_bytes' \
  | jq -r '
      .data.result[]
      | [
          .metric.node,
          .metric.disk,
          ((.value[1] | tonumber) | tostring)
        ]
      | @tsv'
```

Expected result: every node is at or above `15`.

Confirm Longhorn volume health did not regress:

```sh
kubectl -n longhorn-system get volumes.longhorn.io -o json \
  | jq -r '
      .items[]
      | [
          .metadata.name,
          (.status.kubernetesStatus.namespace // ""),
          (.status.kubernetesStatus.pvcName // ""),
          (.status.robustness // "")
        ]
      | @tsv' \
  | sort -k4,4
```

Expected result: no `degraded` or `faulted` volumes.

## Rollback

There is no meaningful rollback for deleted cache or application data. Images
removed by `crictl rmi --prune` are re-pulled when workloads need them again.
Do not prune image cache while the local registry or upstream registry path is
unhealthy.

If `orphan-resource-auto-deletion` must be disabled because it causes a
Longhorn regression, revert `longhorn.orphan_resource_auto_deletion` in
`infrastructure/ansible/inventories/home/group_vars/k3s_nodes.yml`, apply the
Longhorn role, and validate it. Reverting this setting does not restore orphan
replica data that Longhorn already deleted.

If a Git-managed retention or scheduling change causes a workload regression,
revert that commit and let Fleet reconcile the affected app.

## References

- `kubernetes/projects/system/apps/rancher-monitoring/longhorn-rules.yaml`
- `infrastructure/ansible/inventories/home/group_vars/k3s_nodes.yml`
- `infrastructure/ansible/roles/longhorn/templates/longhorn-helmchart.yaml.j2`
