# Applications Project

The Applications project contains public-facing and personal application
workloads. It is where most custom app deployments live, along with Harbor and
Renovate image automation that support the rest of the cluster.

Fleet tracks this project through the `home-lab-applications` GitRepo. Rancher
project metadata is tracked separately from `_project/` by
`home-lab-rancher-projects`.

## Why This Project Exists

Applications are separated from system, database, media, and home-automation
workloads so public app changes do not share the same operational boundary as
cluster infrastructure. This project owns app runtime shape: deployments,
workers, jobs, ingress, services, network policies, PVCs, ConfigMaps, and the
secret contract each app expects.

## App Catalog

| App | What it does | Exposure | Key dependencies |
| --- | --- | --- | --- |
| `applications-helm-repositories` | Registers chart repositories used by this project. | None | Rancher ClusterRepo. |
| `firefly-iii-storage` | Storage support for Firefly III. | None | Longhorn PVCs. |
| `firefly-iii` | Personal finance app. | Internal Traefik at `finance.home`. | PostgreSQL pooler, Longhorn upload PVC, SOPS Secret. |
| `firefly-iii-data-importer` | Import UI for Firefly III. | Internal Traefik at `import.finance.home`. | Firefly service, Longhorn config PVC. |
| `git-rank` | Public GitHub ranking/profile app with frontend, API, webhooks, and workers. | Cloudflare Tunnel at `git-rank.dev` and `api.git-rank.dev`. | PostgreSQL, Valkey, Harbor image, runtime secrets. |
| `harbor` | Local registry and proxy/cache registry. | Internal Traefik at `registry.home`. | PostgreSQL, Valkey, Longhorn, monitoring. |
| `indexly` | Public Next.js app with scheduled sync jobs. | Cloudflare Tunnel at `indexly.cc`. | Harbor image, runtime secrets, CronJobs. |
| `openbao` | Lightweight OpenBao deployment for Wardn-related secret workflows. | Internal Traefik at `secrets.wardn.home`. | Longhorn PVC, manual init/unseal workflow. |
| `personal-blog` | Public personal blog. | Cloudflare Tunnel at `blog.abhimanyu-saharan.com`. | Harbor image, Sanity webhook secret, ConfigMap. |
| `portfolio` | Public portfolio site. | Cloudflare Tunnel at `abhimanyu-saharan.com`. | Harbor image, runtime config. |
| `shipyardhq` | Public app with web, worker, image proxy, build job, and media storage. | Cloudflare Tunnel at `shipyardhq.dev` and image hostnames. | PostgreSQL, Valkey, R2, Longhorn build cache, Harbor image. |
| `wardn-hub` | Wardn Hub backend, frontend, events worker, review webhook, and Codex-backed automation. | Cloudflare Tunnel at `hub.wardnai.dev`. | PostgreSQL, OpenTelemetry, Longhorn Codex state, Harbor image. |
| `zitadel` | Central identity provider for app OIDC/SAML authentication. | Cloudflare Tunnel at `auth.abhimanyu-saharan.com`. | PostgreSQL, SOPS bootstrap secrets, monitoring. |

## Coupling Patterns

Most apps in this project follow the same shape:

1. non-secret runtime settings in a ConfigMap;
2. credentials in SOPS or manually managed Secrets;
3. image pull through namespace-scoped Harbor credentials or public Harbor
   proxy-cache paths;
4. public traffic through Cloudflare Tunnel or internal traffic through Traefik;
5. database access through an app-specific PostgreSQL pooler;
6. optional queue/cache access through Valkey;
7. metrics, traces, dashboards, or alerts when the app needs observability.

This makes app dependencies explicit. A reader can inspect one app directory and
see not just the Deployment, but also how it enters the cluster, where it stores
state, what services it consumes, and what secrets must exist.

## Operating Notes

- Use Cloudflare Tunnel for public hostnames unless there is a specific reason
  to expose a LoadBalancer service.
- Use Traefik for internal `*.home` HTTP routes.
- Keep backend services as ClusterIP unless they need LAN-routable service VIPs.
- Keep app-owned runtime secrets out of Git unless they are SOPS encrypted.
- Add app-specific README files when the app has non-obvious storage, jobs,
  migrations, workers, or webhook behavior.
