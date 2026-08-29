# NFS CSI Driver

The CSI controller is control-plane-only and tolerates the critical-addons
taint. The node plugin remains a DaemonSet on every ARM64 node and tolerates the
taint without a control-plane selector.

This Fleet bundle installs the upstream Kubernetes NFS CSI driver in
`kube-system` with the official Helm chart. The release is pinned to `4.13.4`
and runs on the cluster's ARM64 nodes with the K3s kubelet root at
`/var/lib/kubelet`.

The driver uses an existing NFS server; it does not run an NFS server or
replicate data. The `nfs-shared-retain` StorageClass dynamically provisions an
isolated `${namespace}/${pvc-name}` directory below
`192.168.1.128:/var/nfs/shared/k3s_shared_storage` on the UNAS Pro 4. Consumer
PVCs opt into this class explicitly; Longhorn remains the default StorageClass.
The current mount is NFSv3 with both NFS and `mountd` forced over TCP. Move the
class to NFSv4.1 only after the UNAS exposes this Shared Drive in its v4
namespace and a real read/write mount succeeds.

CPU requests are sized from the live low-volume workload: each node-sidecar
requests `5m`, and the controller sidecars request `5m` each. CPU limits remain
unset so mount and provisioning operations can burst when needed.

Every Kubernetes node requires the host NFS client utilities used by kubelet
mount operations. Ansible installs and validates Debian's `nfs-common` package
through the shared `os_prep.common_packages` inventory instead of coupling it
to the Longhorn role.

The driver leaves `fsGroupPolicy` unset, so Kubernetes uses its default
`ReadWriteOnceWithFSType` policy. The NFS claims are `ReadWriteMany`, and their
root-squashed NAS exports own permissions; skipping kubelet's recursive
ownership rewrite prevents long pod starts and node I/O saturation while
workload UID/GID access remains explicit in each pod security context.

Static PVs can later reference an existing export root directly. Each PV's
`volumeHandle` must be unique cluster-wide and use the upstream
`server#share#subdirectory` format with an empty subdirectory component when
the export root itself should be mounted.

Longhorn remains the default StorageClass and continues to own replicated
volumes. Moving an existing claim to NFS CSI requires a separate PV/PVC and,
when the destination is not the same existing export, a data migration;
changing only `storageClassName` does not migrate data and bound PVC storage
fields are immutable.

The shared class uses `Retain` both for Kubernetes reclaim policy and the NFS
CSI `onDelete` behavior. Deleting a claim therefore does not delete its NAS
directory. Mount permissions are `0777` because the trusted-cluster consumers
run with several unrelated non-root UID/GID combinations and the NAS export
does not provide per-PVC identity mapping. Kubernetes PV/PVC authorization,
namespace boundaries, and workload mount declarations remain the access
boundary; the NAS directories are isolation units, not independent security
exports.

## Fleet Flow

The `csi-driver-nfs-helmop` source bundle creates a `HelmOp` in `fleet-local`.
That HelmOp installs the chart into `kube-system` and loads values from the
generated ConfigMap. The system Helm repository bundle registers the upstream
chart repository before this bundle reconciles.

## Validation

Render the source bundle and upstream release locally:

```sh
kubectl kustomize kubernetes/projects/system/apps/csi-driver-nfs
helm template csi-driver-nfs csi-driver-nfs \
  --repo https://raw.githubusercontent.com/kubernetes-csi/csi-driver-nfs/master/charts \
  --version 4.13.4 \
  --namespace kube-system \
  -f kubernetes/projects/system/apps/csi-driver-nfs/values.yaml
```

After Fleet reconciliation, inspect the driver without mutating the cluster:

```sh
kubectl -n kube-system get pods -l app=csi-nfs-controller
kubectl -n kube-system get pods -l app=csi-nfs-node
kubectl get csidriver nfs.csi.k8s.io
kubectl get storageclass nfs-shared-retain
```

For blocked mounts, root-squash evidence, and break-glass recovery, follow
[`docs/runbooks/storage/nfs-csi-volume-ownership-storms.md`](../../../../../docs/runbooks/storage/nfs-csi-volume-ownership-storms.md).
