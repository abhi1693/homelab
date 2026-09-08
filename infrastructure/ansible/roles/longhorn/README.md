# Longhorn

Ansible owns the paired K3s HelmCharts on server-1. Fleet owns only the ancillary
backup resources; do not migrate chart ownership during an upgrade.

## Reviewed upgrade

`playbooks/longhorn_upgrade.yml` is a narrow maintenance workflow, not the
bootstrap `main` entrypoint. It requires task-specific break-glass authorization
and independently verified recovery copies. It does not run the bootstrap
replica-count, disk-reservation, multipath, or placement reconciliation tasks.

Run these phases separately, inspecting volume, replica, node, and application
health between them:

```sh
ansible-playbook --syntax-check playbooks/longhorn_upgrade.yml
ansible-playbook playbooks/longhorn_upgrade.yml \
  -e longhorn_upgrade_phase=crd -e longhorn_upgrade_recovery_verified=true
ansible-playbook playbooks/longhorn_upgrade.yml \
  -e longhorn_upgrade_phase=manager -e longhorn_upgrade_recovery_verified=true
ansible-playbook playbooks/longhorn_upgrade.yml \
  -e longhorn_upgrade_phase=engines -e longhorn_upgrade_recovery_verified=true
```

The CRD gate checks the actual deployed Helm release, not just CRD existence
or the requested HelmChart version. Engines upgrade serially, requiring each
volume to become healthy, attached, and on the target image before proceeding.
Automatic engine upgrades stay disabled. Never force-delete an old instance
manager that still hosts active engines.

Manager reconciliation recreates CSI controller deployments without the
bootstrap role's controller-only node selectors. The manager upgrade phase
restores that existing placement policy serially, with a rollout gate for each
controller. Do not substitute a global system-managed node selector: that also
restricts node-local storage components and is not a controller-only policy.

Review source-to-target compatibility for the paired Rancher charts before
changing the inventory pin. Recovery must use verified backups and a supported
Longhorn version; reverting a chart pin is not a rollback procedure.

Check [backup target and retained storage status](../../../../kubernetes/projects/system/apps/longhorn-backups/README.md).
No active target is configured. Approve a fresh backup scope and verify recovery
before each maintenance window; a previous upgrade's scope is not standing authorization.

After engine upgrades, use the
[instance-manager retirement procedure](../../../../docs/runbooks/storage/longhorn-instance-manager-retirement.md)
if older managers remain. Preserve application availability and storage recovery
gates rather than deleting active managers to reclaim CPU requests.

Post-upgrade checks use `ansible-playbook playbooks/longhorn.yml -e
longhorn_entrypoint=validation`. Validation waits for active pods, not terminal
Job pods; review failed Jobs separately. It permits only the explicitly listed
`longhorn.validation_allowed_pvcs` ancillary claims (the Fleet-owned retained NAS
backup claim), while rejecting unexpected component persistence.
