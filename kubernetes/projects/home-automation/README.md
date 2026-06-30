# Home Automation Project

The Home Automation project owns services that model and operate the physical
environment around the cluster: Home Assistant, NetBox, rack operations,
Cloudflare tunnel ingress control, and UPS monitoring.

Fleet tracks this project through the `home-lab-home-automation` GitRepo.

## Why This Project Exists

Home automation services are tightly coupled to physical devices and local
network state. They need Kubernetes desired state, but they also interact with
systems outside Kubernetes: UniFi, UPS hardware, device inventory, Cloudflare
tunnels, rack power, and local DNS.

Keeping these services in one project makes the boundary clear.

## App Catalog

| App | What it does | Key coupling |
| --- | --- | --- |
| `home-automation-helm-repositories` | Registers chart repositories for this project. | Rancher ClusterRepo. |
| `cloudflare-tunnel-ingress-controller` | Runs the Cloudflare Tunnel ingress controller. | Public app ingress, Cloudflare credentials. |
| `cloudflare-tunnel-ingress-controller-networkpolicy` | Applies network boundaries for tunnel connector traffic. | Public ingress to app services. |
| `home-assistant` | Home automation runtime with Git-managed packages and code-server sidecar. | UniFi integration, device tracking, Longhorn config PVC. |
| `netbox` | Source of truth for IPAM, device inventory, cabling, DNS, lifecycle, and BGP documentation. | PostgreSQL, Valkey, Longhorn media, custom image plugins. |
| `rack-ops-controllers` | Rack and node automation controllers. | Kubernetes API, Home Assistant webhooks, smart queues, thermal policy. |
| `ups-monitoring` | NUT, PeaNUT dashboard, exporter, Grafana dashboard, and alerts. | USB UPS on a specific node, Home Assistant integration, monitoring. |

## Coupling Patterns

- Home Assistant is the local automation runtime, but some safety workflows are
  intentionally kept in Kubernetes controllers instead of Home Assistant.
- NetBox is the source-of-truth system for inventory and network planning.
- UPS monitoring feeds both dashboards/alerts and Home Assistant integration.
- Cloudflare tunnel control lets public apps expose hostnames without opening
  inbound ports on the home gateway.
- Rack operations bridge Kubernetes state and physical actions such as node
  power or cooling workflows.

## Operating Notes

- Keep Home Assistant packages in Git when they represent desired automation.
- Keep Home Assistant UI-only state limited to things that are not practical to
  own as YAML.
- Keep NetBox plugins baked into the custom NetBox image for repeatability.
- Treat hardware-bound pods, such as UPS USB access, as special cases with
  explicit node placement and update strategy.
