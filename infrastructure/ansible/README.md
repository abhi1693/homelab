# Ansible Bootstrap

This directory contains the bootstrap automation for the home lab. It prepares
hosts, installs K3s, configures core platform components, and validates each
major phase before Rancher Fleet takes over application reconciliation.

## Directory Map

| Path | Purpose |
| --- | --- |
| `ansible.cfg` | Local Ansible defaults for this bootstrap tree. |
| `collections/requirements.yml` | Required Ansible collections. |
| `inventories/home/` | Site-specific inventory and variables for the home cluster. |
| `playbooks/` | Entry points for full-site and role-specific runs. |
| `roles/` | Idempotent role implementations with `main`, `validation`, and where needed `reset` tasks. |
| `scripts/` | Reserved for local Ansible helper scripts. |

## Why Ansible

Ansible is used because the first phase happens before Kubernetes has enough
components to reconcile itself. It is responsible for host-level and
bootstrap-level work:

- installing and configuring K3s;
- installing shared Kubernetes-node packages such as the NFS client utilities;
- writing K3s config files and registry mirror config;
- rendering control-plane and kubelet feature gates for K3s-managed Kubernetes features;
- enabling Cilium kube-proxy replacement behavior and managing cluster DNS add-ons;
- enabling API audit logging and secrets encryption settings;
- installing Cilium through the Cilium CLI;
- creating K3s static manifests such as HelmChart and HelmChartConfig files;
- configuring Longhorn with three replicas by default, plus Rancher,
  cert-manager, kube-vip, and Fleet bootstrap;
- validating the resulting state from outside the GitOps control plane.

Bootstrap-managed Kubernetes components also carry production resource
envelopes in the inventory and rendered chart values. Networking and storage
datapaths keep CPU burstable while declaring CPU/memory requests and memory
limits; finite controllers and init work receive CPU limits as well. The shared
policy and Longhorn exceptions are documented in
[`docs/runbooks/kubernetes-resource-policy.md`](../../docs/runbooks/kubernetes-resource-policy.md).
Longhorn instance managers reserve 12 percent of each node's CPU, and each
Rancher replica requests 200m CPU; both remain able to burst to their configured
limits or the node's available capacity.
The Longhorn role also reconciles existing volume replica counts to the
inventory default, except for explicitly listed replicated-workload namespaces
whose volumes use one storage replica. PostgreSQL and Valkey use this exception
because each already maintains three application-level data copies.

## Execution Model

Install collections:

```sh
ansible-galaxy collection install -r collections/requirements.yml
```

Run a syntax check:

```sh
ansible-playbook --syntax-check playbooks/site.yml
```

Run a role validation entrypoint:

```sh
ansible-playbook playbooks/k3s_server.yml -e k3s_server_entrypoint=validation
```

## Role Entrypoints

Roles follow a consistent variable-driven entrypoint model:

- `main` applies desired state.
- `validation` checks that the expected state exists and is healthy.
- `reset` removes or resets role-managed state when the role supports it.

The playbooks expose those entrypoints through variables such as
`k3s_server_entrypoint=validation` or `fleet_apps_entrypoint=reset`.

## Coupling With Kubernetes

The Ansible layer intentionally stops short of owning every application. It
creates the platform pieces that Fleet needs, then Fleet reconciles the
`kubernetes/` tree.

The important handoff is the `fleet_apps` role. It creates Fleet GitRepo
resources pointing back to this repository, after which app and platform
bundles are reconciled by Rancher Fleet rather than by Ansible.
