# FlareSolverr

This bundle installs FlareSolverr through a Fleet `HelmOp` for indexers that
require browser-challenge handling, and the planned single DevFeed solver worker.

## Runtime Shape

- Namespace: `media`
- Chart: TrueCharts `flaresolverr`
- Release: `flaresolverr`
- Service: ClusterIP on port `8191`
- Image: Harbor proxy path for `ghcr.io/flaresolverr/flaresolverr`

There is no user-facing ingress. Only Prowlarr and the dedicated DevFeed solver worker are allowed as clients.

## Configuration

The container runs with `LOG_LEVEL=info`, HTML logging disabled, a 60-second
browser timeout, and `https://www.google.com` as the test URL. A single real browser request exhausted the former 496Mi memory cap. The service
now requests 512Mi and permits 1536Mi memory with a 1000m CPU limit. DevFeed
serializes its requests through one solver worker and a shared lease; Prowlarr
remains an independent client, so monitor combined concurrency.

## Storage

FlareSolverr uses a bounded `emptyDir` for browser and runtime config. Its state
is disposable, so restarts begin cleanly without consuming replicated Longhorn
capacity or depending on the shared NAS.

## Network Boundary

Ingress is limited to Prowlarr and `devfeed/devfeed-solver-worker` on port `8191`.
Egress permits cluster DNS and public IPv4 HTTP(S) only, excluding private,
loopback, link-local, reserved, multicast and cluster ranges. IPv6 has no allow rule.
This boundary is required because a remote browser follows subresources and
redirects outside DevFeed's DNS-pinned transport. The service must remain internal;
browser behavior and upstream TLS checking are provider-specific.

## Operating Notes

- Keep this service internal; expose indexer workflows through Prowlarr.
- Watch CPU and memory when increasing browser-concurrency behavior.
- Change chart configuration in `values.yaml` and let Fleet reconcile.
