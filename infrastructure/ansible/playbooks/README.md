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
| `add_worker.yml` | Onboard the final worker, `worker-6` (`k8s-rpi9`), with an explicit single-host limit, OS/Pi preparation, agent join and NVMe monitoring validation. |
| `os_prep.yml` | Base OS preparation, cloning-tool cleanup/validation, time-only NTP convergence/validation, package plans, rolling OS upgrades and reboots, and persistent security validation. |
| `rpi_prep.yml` | Raspberry Pi-specific preparation. |
| `k3s_server.yml` | Serial K3s server changes with Node, etcd, and platform recovery gates. |
| `k3s_server_tools.yml` | Prepare the checksum-pinned etcd client before server maintenance; no restarts. |
| `k3s_agent.yml` | K3s agent configuration. |
| `k3s_system_addons.yml` | HA CoreDNS and Metrics Server overrides with inventory-managed resources. |
| `kube_vip.yml` | Kubernetes API registration VIP support. |
| `cilium.yml` | Cilium install and upgrade, Hubble, and Traefik-to-MetalLB integration; `cilium_entrypoint=cli` updates only the host CLI. |
| `longhorn.yml` | Longhorn CRD and chart install. |
| `cert_manager.yml` | cert-manager chart and ClusterIssuer bootstrap. |
| `rancher.yml` | Rancher install and Fleet settings. |
| `fleet_apps.yml` | Fleet GitRepo bootstrap for app and project bundles. |
| `smartctl_exporter.yml` | Host-level S.M.A.R.T. metrics service setup. |
| `node_image_cache_prune.yml` | Break-glass prune of unused K3s image cache on explicitly selected nodes with bounded cache-size diagnostics. |

## How To Use Them

Run syntax checks from `infrastructure/ansible`:

```sh
ansible-playbook --syntax-check playbooks/site.yml
```

Run the full bootstrap:

```sh
ansible-playbook playbooks/site.yml
```

For the planned final worker, use the dedicated
[onboarding workflow](../README.md#final-worker-k8s-rpi9) after its IP is
confirmed. `add_worker.yml` requires `--limit worker-6`; its local assertions
reject a wider selection before gathering facts or preparing hosts. It does not
rerun control-plane or platform bootstrap.

Run a validation entrypoint:

```sh
ansible-playbook playbooks/cilium.yml -e cilium_entrypoint=validation
```

Upgrade OS packages after reviewing the transaction, starting with a worker canary:

```sh
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=os_updates_plan
os_update_canary=worker-2 # Choose a worker without a database primary in the plan.
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=os_updates --limit "$os_update_canary"
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=os_updates
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=os_updates_validation
```

The [OS role instructions](../roles/os_prep/README.md) explain primary placement,
serial host ordering, bounded recovery waits, HTTPS source policy,
verified downloads, transaction checks, reboot recovery gates, persistent security
baselines, and container trust stores.

Update only the bootstrap server's Cilium CLI:

```sh
ansible-playbook playbooks/cilium.yml -e cilium_entrypoint=cli
```

Run the node image cache prune playbook only as a targeted break-glass action:

```sh
ansible-playbook playbooks/node_image_cache_prune.yml \
  -e node_image_cache_prune_target_hosts=worker-1 \
  -e node_image_cache_prune_confirm=true \
  -e 'node_image_cache_prune_reason=Longhorn schedulable space below alert threshold'
```

## Why Separate Playbooks Exist

The full site playbook is useful for initial bootstrap and broad convergence.
Role-specific playbooks are useful during development and operations because
they let one subsystem be validated without rerunning the full stack.

K3s startup time gates can be converged serially without package changes or
service restarts using `os_prep.yml -e os_prep_entrypoint=time_startup_gate`;
`time_startup_gate_validation` checks configuration and the current clock. See
[timeout and failure behavior](../roles/os_prep/README.md#k3s-startup-waits-for-chrony).
