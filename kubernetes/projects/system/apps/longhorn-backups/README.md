# Longhorn recovery storage

Longhorn has no active backup target or recurring backup schedule. This Fleet
bundle keeps the default target disabled and retains the NAS claim; it does
not deploy an object-storage service.

## Retained storage

- PVC: `longhorn-system/longhorn-backups`, RWX, `256Gi`.
- StorageClass: `nfs-shared-retain` (NFSv3).
- Export: `192.168.1.128:/var/nfs/shared/k3s_shared_storage`.
- Directory: `longhorn-system/longhorn-backups`.
- Bound PV: `pvc-2144e5f9-b332-4455-9a62-7de350473980`.

The claim size is a Kubernetes declaration, not a NAS quota. Both the claim and
NAS directory are retained. Preserve the explicit `volumeName`: changing it
on this bound claim is not a migration. For a replacement cluster, provision a
retained PV for the same directory and update the binding before reconciliation.

The [archived recovery guide](../../../../../docs/runbooks/storage/longhorn-20260905/README.md)
identifies the existing backup copies and the manifests needed to access them.
They are recovery points, not current backups. Do not delete or rewrite their
backupstore files outside a reviewed retention operation.

## Before maintenance

UNAS does not support NFSv4, so this working NFSv3 claim is not a directly usable
Longhorn NFS backup target. Establish a supported target through a reviewed
configuration change; do not restart or reconfigure the NAS to force NFSv4.

Require target availability, completed backups for the approved scope, a Ready
SystemBackup, and a tested isolated restore before upgrading. Longhorn block
backups are crash-consistent; PostgreSQL's independent base backups and WAL
archive remain its database recovery path. Replicas and filesystem trim jobs
are not backups.

## Validation

```sh
kubectl -n longhorn-system get pvc longhorn-backups
kubectl -n longhorn-system get backuptargets.longhorn.io,systembackups.longhorn.io,backups.longhorn.io
kubectl apply --dry-run=server -f kubernetes/projects/system/apps/longhorn-backups/pvc.yaml
kubectl apply --dry-run=server -f kubernetes/projects/system/apps/longhorn-backups/backup-target.yaml
```
