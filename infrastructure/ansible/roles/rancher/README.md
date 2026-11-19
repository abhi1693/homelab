# Rancher

Ansible owns Rancher's K3s HelmChart and bootstrap manifest on server-1.
Fleet owns workload bundles after Rancher starts. Applying this role changes
live cluster resources and requires explicit break-glass authorization under
the repository cluster policy.

## Three-server upgrade and drift repair

The Rancher chart hardcodes `maxSurge: 1`. Required hostname anti-affinity with
three replicas on three servers leaves no room for an upgrade surge pod.
The `main` entrypoint checks live deployment capacity even when its bootstrap
manifest is missing, and blocks a chart change without spare capacity.

Run the staged workflow from `infrastructure/ansible`:

```sh
ansible-playbook --syntax-check playbooks/rancher_upgrade.yml
ansible-playbook playbooks/rancher_upgrade.yml
ansible-playbook playbooks/rancher.yml -e rancher_entrypoint=validation
```

The workflow first restores the manifest at the installed chart version with
two replicas, validates that stage, upgrades at two replicas, validates again,
then restores inventory's three replicas and validates the final state. Required
anti-affinity stays enabled. The role restores `maxSurge: 0` before its final
deployment rollout wait. Each stage must succeed before the next play starts;
on failure, stop and inspect Rancher and the Helm install Job before retrying.
Do not override `rancher` through extra variables when running this wrapper,
because that would override its stage-specific version and replica values.

The temporary two-replica state reduces redundancy during maintenance. Do not
combine this workflow with node maintenance or another Rancher chart writer.
Check Rancher readiness and Fleet reconciliation after completion; role
validation alone does not prove that every application bundle is healthy.
