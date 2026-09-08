# Longhorn 2026-09-05 recovery archive

This directory holds completed one-shot recovery requests and retired temporary
service manifests, outside Fleet reconciliation. It is not a recurring backup
configuration. Do not reapply the Snapshot, Backup, or SystemBackup requests.

## Recovery copies

- Operator PC: `/home/asaharan/Backups/longhorn-20260905/store/backupstore`.
- Server-1 staging copy: `/var/tmp/longhorn-20260905/store/backupstore`.
- NAS: `longhorn-system/longhorn-backups` retained claim, with the S3 store
  beneath `/minio`.

The PC and staging trees contain 18 native application-volume backups and
metadata from this maintenance window. The S3 copy additionally contains
`minio-smoke-20260905`. PostgreSQL and Prometheus history were excluded from
the block-backup scope; PostgreSQL uses its independent base backups and WAL.
These are historical recovery points, not evidence of current backup health.

Preserve the native backupstore layout. Longhorn may remove discovered Backup
CRs after a target is disabled; the request CRs here are not the backup data.
The PC copy is independent of the cluster; the staging copy is not.

## Accessing the archived S3 store

No MinIO service or staging NFS listener is running as part of desired state.
If recovery requires S3 access, review `minio.yaml` and the encrypted
`minio-secret.sops.yaml`, and restore them through an authorized Git/Fleet
change. Use the existing retained NAS claim and original credentials; never
substitute empty storage, reset IAM, or repeat an import with deletion options.
The age identity needed to decrypt the credentials must be available separately.

The archived `minio-init.yaml` and `minio-import.yaml` describe setup of the
original store, not routine recovery steps. Verify retained data and S3 health
before enabling a target. Keep the independent PC copy until recovery and
retention are explicitly reviewed.

After restoring the service, an isolated restore can use the existing helper.
Open a dedicated terminal for a loopback-only listener on server-1:

```sh
ssh asaharan@192.168.3.243 'sudo /usr/local/bin/k3s kubectl -n longhorn-system port-forward service/longhorn-backup-minio 19000:9000 --address=127.0.0.1'
```

In another terminal:

```sh
python scripts/longhorn-minio-restore-smoke.py minio-smoke-20260905
```

The helper passes credentials through SSH stdin and restores to an isolated raw
image, not a production volume. Stop the listener afterward and verify port
19000 is closed. Retain restored images until recovery-data retention is reviewed.

The earlier Prowlarr and OpenBao test images were retained on server-1 at
`/var/tmp/longhorn-minio-restore-fs9iakbw/restored.raw` and
`/var/tmp/longhorn-minio-restore-u9youatj/restored.raw`; verify they still exist
before relying on them.

For a staging-NFS recovery, review
`infrastructure/ansible/playbooks/longhorn_local_backup.yml` and its paired
`longhorn_backup_cleanup.yml` with fresh task-specific authorization.
Cleanup must retain the native stores and restored images.

See [current target and claim status](../../../../kubernetes/projects/system/apps/longhorn-backups/README.md).
