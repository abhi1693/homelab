# Rancher Backup

Fleet wrapper for the Rancher Backup operator charts in
`cattle-resources-system`.

It owns two HelmOps:

- `rancher-backup-crd`, which installs the Rancher Backup CRDs.
- `rancher-backup`, which installs the backup/restore operator.

The operator is pinned to chart version `110.0.2+up11.0.3` and configured for
the Cloudflare R2 bucket `home-lab-rancher-backups`. The R2 credentials are
managed by `rancher-backup-secrets` through SOPS as both the active
`rancher-backup-cloudflare-r2` Secret and the legacy `cloudflare-r2` fallback.

Chart 110 targets Rancher 2.15 and Kubernetes 1.34–1.36. Fleet upgrades the CRD
HelmOp before the operator. Preserve R2 settings and backup resources during
upgrades; no UNAS backup target is configured.

## Fleet status refresh

The HelmOp metadata annotation `home-lab.io/status-reconcile-at` records the
latest Git-managed request to refresh its health summary after workload recovery.
Follow the [operational workflow](../../../../../README.md#operational-workflow)
and verify both the child bundle and live workload before requesting another refresh.
