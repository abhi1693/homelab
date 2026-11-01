# Home Automation Project

The Home Automation project owns services that model and operate the physical
environment around the cluster: Home Assistant, NetBox and its MCP server,
Cloudflare tunnel ingress control, USB printing, and UPS monitoring.

Fleet tracks this project through the `home-lab-home-automation` GitRepo.

## Why This Project Exists

Home automation services are tightly coupled to physical devices and local
network state. They need Kubernetes desired state, but they also interact with
systems outside Kubernetes: UniFi, UPS hardware, device inventory, Cloudflare
tunnels and local DNS.

Keeping these services in one project makes the boundary clear.

## App Catalog

| App | What it does | Key coupling |
| --- | --- | --- |
| `home-automation-helm-repositories` | Registers chart repositories for this project. | Rancher ClusterRepo. |
| `cloudflare-tunnel-ingress-controller` | Runs the Cloudflare Tunnel ingress controller. | Public app ingress, Cloudflare credentials. |
| `cloudflare-tunnel-ingress-controller-networkpolicy` | Applies network boundaries for tunnel connector traffic. | Public ingress to explicitly allowlisted app services, including the Wardn AI website. |
| `cups` | Shares the HP Deskjet 2510 over LAN IPP at `printer.home:631`. | USB printer on `k8s-rpi1`, Longhorn state, explicit node placement; manual client setup. |
| `home-assistant` | Home automation runtime with commit-pinned source from `abhi1693/home-assistant` and a code-server sidecar. | Family desktop dashboard, UniFi Protect camera wall, Atomberg fans, media integrations, Longhorn config PVC, PostgreSQL Recorder. |
| `home-assistant-go2rtc` | Runs the authenticated WebRTC relay used by Home Assistant camera entities. | Cluster-only signaling API, fixed MetalLB LAN media candidate, and exact Protect RTSPS egress. |
| `home-assistant-mobile-webhook` | Deploys the released [`ha-sensors-gateway`](https://github.com/abhi1693/ha-sensors-gateway) image for native Companion App sensor and location webhooks through Cloudflare Tunnel. | Capability-scoped phone updates without public Home Assistant UI or API access. |
| `home-assistant-status-bridge` | Converts authoritative Prometheus health into one bounded read-only document for Home Assistant. | No Kubernetes credentials; internal-only status endpoint and Grafana/Rancher deep links. |
| `netbox` | Source-of-truth app for IPAM, infrastructure inventory, cabling, DNS, and lifecycle documentation; UniFi Network clients are excluded. | Direct PostgreSQL write service, Valkey data, NFS media, and custom image plugins. |
| `ups-monitoring` | NUT, PeaNUT dashboard, exporter, Grafana dashboard, and alerts. | USB UPS on a specific node, Home Assistant integration, monitoring. |

## Coupling Patterns

- Home Assistant is the local automation runtime, but some safety workflows are
  intentionally kept in Kubernetes controllers instead of Home Assistant.
- NetBox is the source-of-truth system for infrastructure inventory and network
  planning. UniFi Network client observations are not imported. It runs one web
  replica and one worker and connects directly to the shared PostgreSQL write
  service.
- The NetBox MCP server accepts each client's NetBox v2 token and forwards it
  only to the allowlisted in-cluster NetBox service. It stores no shared NetBox
  credential and exposes only an HTTPS endpoint terminated by trusted Traefik.
- UPS monitoring feeds both dashboards/alerts and Home Assistant integration.
- Cloudflare tunnel control lets public apps expose hostnames without opening
  inbound ports on the home gateway.
- The mobile webhook gateway exposes only capability-scoped Companion App
  sensor, location, and explicitly documented metadata commands; forged sensor
  or location values can still trigger Home Assistant automations. Home
  Assistant itself remains LAN-only.

## Operating Notes

- Keep Home Assistant packages, dashboards, themes and bootstrap behavior in the
  dedicated `abhi1693/home-assistant` source repository.
- Pin Home Assistant source revisions and archive checksums in this repository's
  Fleet deployment.
- Keep Home Assistant UI-only state limited to things that are not practical to
  own as YAML.
- Keep NetBox plugins baked into the custom NetBox image for repeatability.
- Treat hardware-bound pods, such as UPS USB access, as special cases with
  explicit node placement and update strategy.

The K8s Recommendation Engine and its profile, CRD, and backup-validation bundles
were retired through Fleet. Resource changes are reviewed and applied through Git.
The dedicated runtime namespace, permissions, and Longhorn state volume are
removed. The NFS backup directory and its PV are also deleted; no recommendation-engine
PVC, PV, or archived state is retained.
