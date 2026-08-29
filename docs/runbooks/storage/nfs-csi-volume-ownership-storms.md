---
title: NFS CSI Volume Ownership Storms
---

# NFS CSI Volume Ownership Storms

## Meaning

When the NFS CSI `CSIDriver` advertises `fsGroupPolicy: File`, kubelet applies a
pod's `fsGroup` recursively to every mounted file. Large root-squashed NAS
exports reject those ownership changes, producing
`VolumePermissionChangeInProgress`, long pod starts, `DeadlineExceeded` Jobs,
and sustained Raspberry Pi I/O wait.

`fsGroupChangePolicy: OnRootMismatch` avoids recursion only when the export root
already has the expected group and permission bits. It cannot repair a
root-squashed export whose root is owned by the NAS.

## Impact

- Singleton applications remain unavailable in `PodInitializing`.
- CronJobs can hit `activeDeadlineSeconds` before their container starts.
- A force-deleted pod can leave its kubelet ownership walk running until the
  operation completes or kubelet restarts.
- Unbounded `du`, `find`, or recursive ownership diagnostics amplify the same
  I/O incident.

## Diagnosis

```sh
kubectl get csidriver nfs.csi.k8s.io -o yaml
kubectl -n <namespace> get pod <pod> -o jsonpath='{.spec.securityContext}{"\n"}'
kubectl -n <namespace> get pvc <claim> \
  -o custom-columns='NAME:.metadata.name,ACCESS:.spec.accessModes[*],VOLUME:.spec.volumeName'
kubectl -n <namespace> get events \
  --field-selector reason=VolumePermissionChangeInProgress \
  --sort-by=.lastTimestamp
```

On the affected node, use a bounded journal query. Do not recursively enumerate
the mounted export:

```sh
cd infrastructure/ansible
ansible server-1 -b -m ansible.builtin.shell -a \
  "journalctl -u k3s --since '10 minutes ago' --no-pager \
   | grep -E 'volume_linux.go|VolumePermission|Lchown failed' \
   | tail -100"
```

Confirm the claim is `ReadWriteMany` and that application access is provided by
the workload UID and supplemental NAS groups before disabling kubelet ownership
management.

## Mitigation

This repo's root-squashed NFS exports own their permissions. Keep
`feature.enableFSGroupPolicy: false` in the NFS CSI values so the rendered
`CSIDriver` omits `fsGroupPolicy`; Kubernetes then uses
`ReadWriteOnceWithFSType`, which skips these RWX claims. Keep the workload's
actual NAS groups in `supplementalGroups`.

CronJobs that mount smaller compatible filesystems should still set:

```yaml
securityContext:
  fsGroupChangePolicy: OnRootMismatch
```

Validate both source and upstream render:

```sh
kubectl apply --dry-run=server \
  -k kubernetes/projects/system/apps/csi-driver-nfs

helm template csi-driver-nfs csi-driver-nfs \
  --repo https://raw.githubusercontent.com/kubernetes-csi/csi-driver-nfs/master/charts \
  --version 4.13.4 \
  --namespace kube-system \
  -f kubernetes/projects/system/apps/csi-driver-nfs/values.yaml \
  | sed -n '/kind: CSIDriver/,+12p'
```

In an active outage, changing the live `CSIDriver` and deleting an unstarted pod
are break-glass actions. Commit the Git fix first or immediately afterward.
If a force-deleted pod's old UID is still producing `Lchown failed`, and the
node is one of several healthy control-plane nodes, restart only that node's
k3s service to cancel the orphaned kubelet operation. Verify control-plane
quorum and every workload on that node before and after the restart.

## Verification

- A new pod reaches `Running` without `VolumePermissionChangeInProgress`.
- Application health succeeds and logs show normal startup.
- The old pod UIDs stop appearing in the node journal.
- Five-minute Raspberry Pi I/O wait and load per core no longer jointly exceed
  the `20%` and `1` alert thresholds.
- Fleet reports the NFS CSI and application bundles Ready.

## Rollback

Set `feature.enableFSGroupPolicy: true` only if every affected export supports
the requested ownership changes and workloads require kubelet-managed groups.
Revert through Git and Fleet; expect a recursive walk on the next mount.

## References

- `kubernetes/projects/system/apps/csi-driver-nfs/README.md`
- `kubernetes/projects/entertainment/apps/media-jellyfin/README.md`
- `docs/runbooks/storage/raspberry-pi-high-iowait.md`
- Kubernetes CSIDriver API: <https://kubernetes.io/docs/reference/kubernetes-api/storage/csi-driver-v1/>
- Kubernetes fsGroup policy: <https://kubernetes.io/blog/2020/12/14/kubernetes-release-1.20-fsgroupchangepolicy-fsgrouppolicy/>
