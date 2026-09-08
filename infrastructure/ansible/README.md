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
- configuring every host-networked kube-vip replica to use its node-local K3s
  API so the registration VIP survives any one control-plane outage;
- installing Cilium through the Cilium CLI;
- creating K3s static manifests such as HelmChart and HelmChartConfig files;
- configuring Longhorn with three replicas by default, plus three-replica Rancher,
  cert-manager, kube-vip, and Fleet bootstrap with two hostname-separated local
  agents so GitOps remains available through one control-plane maintenance event;
- validating the resulting state from outside the GitOps control plane.

Bootstrap-managed Kubernetes components also carry production resource
envelopes in the inventory and rendered chart values. Networking and storage
datapaths keep CPU burstable while declaring CPU/memory requests and memory
limits; finite controllers and init work receive CPU limits as well. The shared
policy and Longhorn exceptions are documented in
[`docs/runbooks/kubernetes-resource-policy.md`](../../docs/runbooks/kubernetes-resource-policy.md).
Each Longhorn instance-manager pod reserves 12 percent of its node's CPU;
multiple manager versions on a node each reserve that amount. Each
Rancher replica requests 200m CPU; both remain able to burst to their configured
limits or the node's available capacity.
Fleet HelmOps requests 192Mi and is capped at 384Mi so a repository-wide
reconciliation can render concurrent chart updates without being OOM-killed.
The Longhorn role also reconciles every existing Longhorn volume replica count
to the inventory default of three, including PostgreSQL and Valkey volumes that
also maintain application-level replicas.
Longhorn permits up to five concurrent replica rebuilds per node so one slow
recovery does not block unrelated degraded volumes. Operators should monitor
the Raspberry Pi nodes' shared root NVMe and 1 GbE utilization while several
rebuilds are active.
Automatic engine upgrades remain disabled during normal operation. For a
reviewed Longhorn chart upgrade, use the separate CRD, manager, and serial engine
phases in [the Longhorn upgrade runbook](roles/longhorn/README.md). Each engine
must regain three writable replicas before the next is upgraded. Keep the
automatic engine upgrade limit at zero throughout this procedure.
After live engine upgrades, retiring older instance managers requires a
separate, authorized detach/reattach sequence. Use the
[instance-manager retirement runbook](../../docs/runbooks/storage/longhorn-instance-manager-retirement.md)
with application and database recovery gates; never delete active managers
just to reclaim CPU requests.
Check [backup target status](../../kubernetes/projects/system/apps/longhorn-backups/README.md)
and establish verified recovery copies before storage maintenance.

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

The [home inventory](inventories/home/) owns server and worker hostnames,
addresses, and role membership.

The `k3s_agent` play processes workers in inventory order with `serial: 1` and
stops all remaining batches if one worker fails. After pending restart handlers
run, it requires the local service to be active, a fresh Kubernetes Node lease,
the inventory-pinned kubelet version, and a `Ready` Node condition before moving
to the next worker. The readiness queries use the first `k3s_servers` inventory
host by default; set `k3s_agent_readiness_delegate` to another healthy server
when intentionally using a different control-plane path.
During initial `site.yml` provisioning, `k3s_agent_rollout_mode: bootstrap`
defers only Node Ready until Cilium exists; service, lease, and version gates
remain in effect. Subsequent worker runs default to `rolling` and require Ready.

The `k3s_server` play also stops all remaining batches on failure. Established
clusters default to `rolling` mode, which requires Node, API, etcd consensus,
storage, and critical workload health before each change and after all restart
handlers. Prepare the checksum-pinned ARM64 etcd client beforehand with
`ansible-playbook playbooks/k3s_server_tools.yml`; the rollout never downloads
its health tooling. Two successful samples 20 seconds apart are required.
`site.yml` explicitly uses `bootstrap` for its server passes because Cilium and
platform workloads do not yet exist. See the
[server gate documentation](roles/k3s_server/README.md) for checks and failure handling.

The `k3s_server` role declares and reconciles
`CriticalAddonsOnly=true:NoExecute` on the three server Nodes one at a time.
Registration-time config and live Node state are both validated. Run the taint
transition only after Fleet has reconciled the matching control-plane selectors
and tolerations for all platform workloads.
The Longhorn role also reconciles every generated node-local DaemonSet with the
critical-addons toleration, including existing CSI plugin and engine-image
DaemonSets that cannot adopt a changed Longhorn setting while volumes are attached.

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
