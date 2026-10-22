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
- bootstrapping Cilium through the Cilium CLI before handing runtime Helm ownership to Fleet;
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
- `cli` on the Cilium playbook updates only the bootstrap server's Cilium CLI.
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

## Infrastructure upgrade checkpoint (2026-10-02)

Rancher 2.15.2, cert-manager 1.21.2, and kube-vip 1.2.4 have been deployed.
The table records the bootstrap upgrades:

| Component | Previous | Deployed | Deployment entrypoint |
| --- | --- | --- | --- |
| Rancher | 2.15.1 | 2.15.2 | `playbooks/rancher.yml` |
| Cilium CLI | 0.19.4 | 0.20.1 | `playbooks/cilium.yml -e cilium_entrypoint=cli` |
| cert-manager | 1.20.3 | 1.21.2 | `playbooks/cert_manager.yml` |
| Cilium | 1.20.1 | 1.20.1 | `playbooks/cilium.yml` for initial bootstrap; Fleet thereafter |
| kube-vip | 1.2.1 | 1.2.4 | `playbooks/kube_vip.yml` |

The platform-changing entrypoints mutate bootstrap-managed cluster resources
outside Fleet. Under the repository cluster policy, AI execution requires
explicit break-glass approval; changing the inventory alone does not deploy
them. Run them individually, observe readiness after each, and retain existing
values and scheduling constraints.
The Cilium `cli` entrypoint changes only `/usr/local/bin/cilium` on the bootstrap
server. It does not render chart values, run `cilium upgrade`, or restart pods.
Use it when the CLI pin changes independently of the Cilium dataplane version.
The Cilium role detects `fleet-local/cilium` targeting the existing
`kube-system/cilium` release and skips CLI install/upgrade operations after
handoff. Change the [Fleet Cilium bundle](../../kubernetes/projects/system/apps/cilium/README.md)
for runtime updates, keeping the inventory and bootstrap template equal to its
full Helm values. Run `scripts/check-cilium-observability.py` from the repository
root to check that equality. Agent/operator/Hubble metrics are enabled without
Relay or UI; the separate Cilium monitoring bundle owns Prometheus discovery.
Keep the Cilium dataplane on 1.20.1 for the Raspberry Pi OS nodes. Cilium
1.20.2 cannot initialize its socket load-balancing BPF programs on kernels
without BTF, leaving new pods unable to get networking even while the Cilium
DaemonSet reports Ready. All eight current nodes lack
`/sys/kernel/btf/vmlinux`. Upstream tracks this as
[cilium/cilium#48778](https://github.com/cilium/cilium/issues/48778); the
documented workaround is to downgrade to 1.20.1. The role rejects 1.20.2
when any cluster node lacks kernel BTF.
Rancher owns the compatible Fleet, webhook and Turtles versions; do not
upgrade those independently.
Cilium's inventory pins the live cluster name, disabled BGP control plane,
VXLAN routing, and single-node agent and Envoy rollout limits. The operator
uses the third control-plane node for a surge replica while keeping both
existing replicas available. Bootstrap waits for Helm-driven rollouts and does
not force a second Cilium restart. Subsequent runtime rollouts are Fleet-owned;
the read-only validation entrypoint checks readiness and node-local agent and
Hubble metrics.

The upstream Rancher chart hardcodes `maxSurge: 1` and exposes no Helm value for
the Deployment strategy. With three replicas, required hostname anti-affinity,
and three eligible servers, this creates Pending surge pods during a chart
upgrade. The role now refuses a future HelmChart manifest change under those
conditions before mutating bootstrap resources. Keep required anti-affinity;
wait for chart support for `maxSurge: 0` or add eligible server capacity before
the next Rancher upgrade. The inventory's `maxSurge: 0` is reconciled only after
the chart rollout, so it does not remove that upgrade risk.

K3s is pinned to stable `v1.36.5+k3s1`, within Rancher 2.15.2's supported
Kubernetes 1.36 range. Upgrade servers and then workers one at a time through
the rolling playbooks, checking active user-facing endpoints between nodes.
The release updates bundled Traefik to chart 40; this cluster does not configure
the renamed ingress-nginx migration provider. CoreDNS and metrics-server image
overrides match the release's bundled versions. Their manifest-driven rollouts
keep both replicas available by allowing one surge pod at a time. Longhorn remains
1.12.1, the latest chart in its configured Rancher channel. MetalLB 0.16.1,
NFS CSI 4.13.4 and CloudNativePG 1.30.1 are current in their configured channels.
Fleet deployed Rancher Backup chart `110.0.2+up11.0.3` (operator 11.0.3) and
SOPS Secrets Operator chart `0.28.1` (operator 0.21.2); both operators and the
Backup CRD HelmOp became Ready. No UNAS target is configured or used. Cilium
remains at 1.20.1 after the 1.20.2 BTF regression. kube-vip 1.2.4 rolled
across all three control-plane nodes with the API VIP and user-facing routes
available; its three replacement pods have zero restarts.

For cert-manager 1.21, the removed metrics path/port override values must be
absent, and issuers using `serviceAccountRef` require a separate RBAC review.
The current issuers use Cloudflare DNS01, the local CA and self-signed certificates.
The cert-manager rollout retained all nine certificate Secrets with unchanged
data and UIDs; all six new pods, three ClusterIssuers and nine Certificates
became Ready. For Cilium and kube-vip, require
all node agents and the API VIP to recover before proceeding.

Rollback bootstrap chart versions through their original owners using the
previous values. Rancher rollback requires its documented restore procedure;
review available existing recovery points before execution. Do not uninstall
CRDs or delete certificate Secrets, namespaces or storage to perform an upgrade.
