# Ansible Roles

This directory contains the reusable bootstrap roles for the lab.

## Role Catalog

| Role | What | Why |
| --- | --- | --- |
| `os_prep` | Base host setup. | Establishes common OS assumptions before K3s is installed. |
| `rpi_prep` | Raspberry Pi-specific setup. | Handles Pi-specific kernel, kubelet, and hardware telemetry concerns. |
| `k3s_server` | K3s server config. | Creates the control-plane configuration, API arguments, audit policy, registry mirrors, and secrets settings. |
| `k3s_agent` | K3s agent config. | Joins worker nodes to the server API endpoint with matching kubelet and registry settings. |
| `k3s_system_addons` | K3s add-on customization. | Manages bootstrap add-ons such as CoreDNS and metrics-server overrides. |
| `kube_vip` | API VIP. | Keeps the Kubernetes API registration endpoint stable for joining and operating nodes. |
| `cilium` | CNI, policy, LB IPAM, BGP, Hubble, Traefik config. | Provides pod networking and service exposure through one system. |
| `longhorn` | Distributed storage. | Provides Kubernetes persistent volumes for the app and platform layer. |
| `cert_manager` | Certificate management. | Installs cert-manager and the ClusterIssuer used by cluster services. |
| `rancher` | Rancher management plane. | Installs Rancher and configures Fleet/ImageScan behavior. |
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
