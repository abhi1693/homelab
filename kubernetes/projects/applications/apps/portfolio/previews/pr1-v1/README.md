# Yashika PR 1 preview v1

Static preview of https://github.com/yashikavarshney/yashikavarshneyy/pull/1
at source commit `e6dcf46fa4ab47014b2910aae8949f0a42f8b72f`.

URL: https://preview-pr1-v1-e6dcf46fa4ab47014b2910aae8949f0a42f8b72f.abhimanyu-saharan.com/
Readable route: append `portfolio/`.

Fleet's existing portfolio bundle owns the isolated Deployment, Service,
Ingress and NetworkPolicies in resources.yaml. A dedicated policy in the
cloudflare namespace permits tunnel connector egress only to the preview
pods on TCP 8080. It reuses the existing registry
identity and Cloudflare Tunnel. The main portfolio selectors and hosts are unchanged.

Astro retains static output, served by server.mjs using Node's built-in APIs.
There is no Nginx, SSR adapter or runtime npm dependency. The image contains
Node 24.22.2 and its required libraries, without a shell or package manager.
The pod runs as UID/GID 1000 with read-only storage, dropped capabilities,
no service-account token, a 128Mi memory limit and /healthz probes.
The server preserves safe static routing, media ranges, request limits,
security headers and noindex protection. Cache-Control no-transform preserves
the static HTML and email links through the public proxy. Tunnel-only ingress and application
egress restrictions remain; the existing namespace-wide policy permits CoreDNS.

## Build and push locally

Use an independent checkout of the source revision on the Home Lab build host.
Run npm ci --ignore-scripts, npm run check, npm test, npm audit, then build with:

```sh
SITE_URL=https://preview-pr1-v1-e6dcf46fa4ab47014b2910aae8949f0a42f8b72f.abhimanyu-saharan.com/ npm run build
```

Copy server.mjs, Dockerfile.preview and Dockerfile.preview.dockerignore beside dist.
Build and push from the local build machine using its existing registry access:

```sh
docker build --platform linux/arm64 -f Dockerfile.preview -t registry.home/home/yashika-preview:pr1-v5-node-e6dcf46fa4ab47014b2910aae8949f0a42f8b72f .
docker push registry.home/home/yashika-preview:pr1-v5-node-e6dcf46fa4ab47014b2910aae8949f0a42f8b72f
```

The manifest pins the published digest. Do not overwrite this version; use
a new image version for later changes. No preview build workflow is added.

After Fleet reconciles, verify the public HTTPS URL, revision, both routes,
assets, media and browser behavior before sharing it on the source PR.

## Rollback

Revert the preview change through Git/Fleet. Confirm removal of the isolated
workload, Service, Ingress, both NetworkPolicies and catalog entry, and of the
tunnel controller's DNS record/route. Preserve the portfolio namespace,
main app and registry identity. Unused images follow normal Harbor retention.
