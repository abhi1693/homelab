# Applications Project

Fleet tracks public application workloads from explicit app directory paths
under `kubernetes/projects/applications/apps/` with the
`home-lab-applications` GitRepo.

The Rancher project object is tracked separately from
`kubernetes/projects/applications/_project` by `home-lab-rancher-projects`.
Project metadata uses non-forcing drift correction because Rancher `Project`
objects include immutable fields.

## Bundles

| Path | Bundle | Type | Ingress hosts |
|------|--------|------|--------------|
| `apps/applications-helm-repositories` | `applications-helm-repositories` | Rancher ClusterRepo | N/A |
| `apps/firefly-iii-storage` | `firefly-iii-storage` | Raw YAML | N/A |
| `apps/firefly-iii` | `firefly-iii` | Raw YAML | `finance.home` |
| `apps/firefly-iii-data-importer` | `firefly-iii-data-importer` | Raw YAML | `import.finance.home` |
| `apps/git-rank` | `git-rank` | Raw YAML | `git-rank.dev`, `api.git-rank.dev` |
| `apps/harbor` | `harbor-helmop` | HelmOp | `registry.home` |
| `apps/indexly` | `indexly` | Raw YAML | `indexly.cc` |
| `apps/personal-blog` | `personal-blog` | Raw YAML | `blog.abhimanyu-saharan.com` |
| `apps/portfolio` | `portfolio` | Raw YAML | `abhimanyu-saharan.com`, `www.abhimanyu-saharan.com` |
| `apps/shipyardhq` | `shipyardhq` | Raw YAML | `shipyardhq.dev`, `www.shipyardhq.dev`, `img.shipyardhq.dev` |

## Exposure

Public application ingress resources use the `cloudflare-tunnel` ingress class.
Internal-only ingress uses the `traefik` ingress class. Harbor is internal-only
at `registry.home` through UniFi split DNS. Backend services
remain ClusterIP services inside their app namespace.

## Network Policy

Application namespaces use default-deny network policies. Public ingress is
limited to the Cloudflare tunnel connector pods in the `cloudflare` namespace.
Internal ingress is limited to Traefik pods in the `kube-system` namespace.

## Operating Model

Most app workloads are normal Kubernetes resources, so GitOps raw YAML remains
the right fit. Rancher `ClusterRepo` bundles only register chart catalogs for
operator-driven installs. Make desired-state changes in Git and let Fleet
reconcile them. Direct cluster changes should be limited to resources Fleet
cannot own, such as manually provisioned secrets, or to fixing ownership
metadata so Fleet can take over.
