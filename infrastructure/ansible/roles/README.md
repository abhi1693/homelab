# Ansible Roles

This directory contains the reusable bootstrap roles for the lab.

## Role Catalog

| Role | What | Why |
| --- | --- | --- |
| `os_prep` | Base host setup and shared packages, including NFS client utilities. | Establishes common OS assumptions and storage clients before K3s is installed. |
| `rpi_prep` | Raspberry Pi-specific setup. | Handles Pi-specific kernel, kubelet, and hardware telemetry concerns. |
| `k3s_server` | K3s server config. | Creates the control-plane configuration, API arguments, audit policy, registry mirrors, and secrets settings. |
| `k3s_agent` | K3s agent config. | Joins worker nodes to the server API endpoint with matching kubelet and registry settings. |
| `k3s_system_addons` | K3s add-on customization. | Manages bootstrap add-ons such as CoreDNS and metrics-server overrides. |
| `kube_vip` | API VIP. | Keeps the Kubernetes API registration endpoint stable for joining and operating nodes. |
| `cilium` | CNI, policy, Hubble, and Traefik config. | Provides pod networking and integrates LAN service exposure with Fleet-managed MetalLB. |
| `longhorn` | Distributed storage. | Provides Kubernetes persistent volumes for the app and platform layer. |
| `cert_manager` | Certificate management. | Installs cert-manager and the ClusterIssuer used by cluster services. |
| `rancher` | Rancher management plane. | Installs Rancher and configures Fleet behavior. |
| `fleet_apps` | Fleet GitRepo bootstrap. | Hands post-bootstrap desired state to Fleet. |
| `smartctl_exporter` | Host S.M.A.R.T. metrics. | Provides disk health metrics where host-level installation is more reliable than a container. |

## Role Shape

Most roles follow this structure:

| Path | Purpose |
| --- | --- |
| `tasks/main.yml` | Apply desired state. |
| `tasks/validation.yml` | Assert the resulting state is correct. |
| `tasks/reset.yml` | Remove role-managed state when supported. |
| `meta/argument_specs.yml` | Document and validate role variables. |
| `templates/` | Rendered K3s, HelmChart, HelmChartConfig, Cilium, or Kubernetes manifests. |
| `handlers/` | Service restarts and related handlers. |

## Design Notes

The roles are intentionally explicit. Many tasks read current state before
mutating anything so they can avoid unnecessary restarts or detect unsafe
changes. Validation is part of the design because infrastructure changes need a
post-change health check, not just a successful Ansible exit code.

The `cilium` role treats Traefik's `loadBalancerClass` as immutable. If the
desired class differs, it recreates the Service through Helm before updating
the packaged K3s `HelmChartConfig`, then waits for MetalLB to restore the
requested VIP.

The `k3s_server` role also renders inventory-managed kube-apiserver arguments.
The home inventory uses that path to disable unconsumed, high-cardinality
control-plane histogram families before they consume K3s process memory or
Prometheus ingestion capacity. The server playbook applies configuration one
host at a time so component-argument changes preserve embedded-etcd quorum.
