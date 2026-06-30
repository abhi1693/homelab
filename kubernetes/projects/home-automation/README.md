# Home Automation Project

Fleet tracks Home Automation workloads from `kubernetes/projects/home-automation/apps/*`
with the `home-lab-home-automation` GitRepo.

The Rancher project object is tracked separately from
`kubernetes/projects/home-automation/_project` by `home-lab-rancher-projects`.
Project metadata uses non-forcing drift correction because Rancher `Project`
objects include immutable fields.

## Bundles

| Path | Bundle | Type | Notes |
|------|--------|------|-------|
| `apps/home-automation-helm-repositories` | `home-automation-helm-repositories` | GitOps | Registers Rancher chart repositories used by Home Automation workloads. |
| `apps/cloudflare-tunnel-ingress-controller` | `cloudflare-tunnel-ingress-controller` | Helm | Deploys the Cloudflare Tunnel ingress controller and managed cloudflared connector. |
| `apps/cloudflare-tunnel-ingress-controller-networkpolicy` | `cloudflare-tunnel-ingress-controller-networkpolicy` | GitOps | Applies Cloudflare tunnel network boundaries. |
| `apps/home-assistant` | `home-assistant` | GitOps | Deploys Home Assistant through the K3s HelmChart controller. |
| `apps/rack-ops-controllers` | `rack-ops-controllers` | GitOps | Runs rack-operation controllers such as qBittorrent Smart Queues and Raspberry Pi thermal controls in the `rack-ops` namespace. |
| `apps/netbox` | `netbox-helmop` | GitOps wrapper | Creates `HelmOp/netbox` and `ConfigMap/netbox-values`. |
| `apps/netbox` | `netbox` | HelmOps | Deploys the NetBox chart from `oci://ghcr.io/netbox-community/netbox-chart/netbox`. |
| `apps/ups-monitoring` | `ups-monitoring` | GitOps | Runs NUT for the APC USB UPS on `k8s-rpi1` and exposes PeaNUT at `ups.home`. |

HelmOps apps use the app name for the `HelmOp`, Helm release, and workload.
The GitOps wrapper bundle keeps the `-helmop` suffix because Fleet also creates
a child bundle with the app name.

## Reconcile Order

`rancher-project-home-automation` and `home-automation-helm-repositories` must
be ready before Home Automation app bundles. `postgresql`,
`postgresql-networkpolicy`, `valkey`, and `valkey-networkpolicy` must also be
ready before NetBox. The shared database bundles are managed by the Database
project.

## Operating Model

Make desired-state changes in Git and let Fleet reconcile them. Direct cluster
changes should be limited to resources Fleet cannot own, such as manually
provisioned secrets, or to fixing ownership metadata so Fleet can take over.
