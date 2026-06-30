# Ansible Playbooks

This directory contains executable entry points for the bootstrap roles.

## What These Playbooks Do

Each role has a small playbook wrapper. The wrapper selects the relevant hosts
from inventory and passes control to the role. Most playbooks support role
entrypoint variables so the same playbook can apply, validate, or reset a
subsystem.

| Playbook | Scope |
| --- | --- |
| `site.yml` | Full bootstrap sequence. |
| `os_prep.yml` | Base OS preparation. |
| `rpi_prep.yml` | Raspberry Pi-specific preparation. |
| `k3s_server.yml` | K3s server configuration. |
| `k3s_agent.yml` | K3s agent configuration. |
| `k3s_system_addons.yml` | Core K3s add-ons such as CoreDNS and metrics-server overrides. |
| `kube_vip.yml` | Kubernetes API registration VIP support. |
| `cilium.yml` | Cilium install, upgrade, LB IPAM, BGP, Hubble, and Traefik LoadBalancer config. |
| `longhorn.yml` | Longhorn CRD and chart install. |
| `cert_manager.yml` | cert-manager chart and ClusterIssuer bootstrap. |
| `rancher.yml` | Rancher install and Fleet ImageScan settings. |
| `fleet_apps.yml` | Fleet GitRepo bootstrap for app and project bundles. |
| `smartctl_exporter.yml` | Host-level S.M.A.R.T. metrics service setup. |

## How To Use Them

Run syntax checks from `infrastructure/ansible`:

```sh
ansible-playbook --syntax-check playbooks/site.yml
```

Run the full bootstrap:

```sh
ansible-playbook playbooks/site.yml
```

Run a validation entrypoint:

```sh
ansible-playbook playbooks/cilium.yml -e cilium_entrypoint=validation
```

## Why Separate Playbooks Exist

The full site playbook is useful for initial bootstrap and broad convergence.
Role-specific playbooks are useful during development and operations because
they let one subsystem be validated without rerunning the full stack.
