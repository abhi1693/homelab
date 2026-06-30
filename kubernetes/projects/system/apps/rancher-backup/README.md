# Rancher Backup

Fleet wrapper for the Rancher Backup operator charts in
`cattle-resources-system`.

It owns two HelmOps:

- `rancher-backup-crd`, which installs the Rancher Backup CRDs.
- `rancher-backup`, which installs the backup/restore operator.

The operator is pinned to chart version `109.0.3+up10.0.3` and configured for
the Cloudflare R2 bucket `home-lab-rancher-backups`. The R2 credentials are
managed by `rancher-backup-secrets` through SOPS as both the active
`rancher-backup-cloudflare-r2` Secret and the legacy `cloudflare-r2` fallback.
