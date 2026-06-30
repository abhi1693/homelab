# System Project

Fleet tracks cluster system workloads from `kubernetes/projects/system/apps/*`
with the `home-lab-system` GitRepo.

The Rancher `System` project is built in and is not managed from
`kubernetes/projects/*/_project`. Workloads here should keep their namespaces
assigned to Rancher project `p-zl69x`.

## Bundles

| Path | Bundle | Type | Notes |
|------|--------|------|-------|
| `apps/system-helm-repositories` | `system-helm-repositories` | GitOps | Registers Rancher chart repositories used by system and bootstrap infrastructure. |
| `apps/descheduler` | `descheduler-helmop` | GitOps wrapper | Runs the Kubernetes Descheduler on a conservative interval to rebalance movable workloads across Ready nodes. |
| `apps/external-dns-unifi` | `external-dns-unifi` | Helm | Publishes internal Traefik ingress hosts to UniFi DNS. |
| `apps/external-dns-unifi-networkpolicy` | `external-dns-unifi-networkpolicy` | Raw YAML | Restricts ExternalDNS network access. |
| `apps/cert-manager-secrets` | `cert-manager-secrets` | SOPS | Manages the Cloudflare DNS01 token used by cert-manager. |
| `apps/rancher-backup` | `rancher-backup-helmop` | GitOps wrapper | Creates Rancher Backup CRD and operator HelmOps in `cattle-resources-system`. |
| `apps/rancher-monitoring` | `rancher-monitoring-helmop` | GitOps wrapper | Creates Rancher Monitoring CRD and stack HelmOps in `cattle-monitoring-system`. |
