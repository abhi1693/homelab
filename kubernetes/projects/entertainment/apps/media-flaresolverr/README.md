# FlareSolverr

This bundle installs FlareSolverr through a Fleet `HelmOp` for indexers that
require browser-challenge handling, and the single DevFeed solver worker.

## Runtime Shape

- Namespace: `media`
- Chart: TrueCharts `flaresolverr`
- Release: `flaresolverr`
- Service: ClusterIP on port `8191`
- Image: Harbor proxy path for `ghcr.io/flaresolverr/flaresolverr`

There is no user-facing ingress. Only Prowlarr and the dedicated DevFeed solver worker are allowed as clients.

## Configuration

The container runs with `LOG_LEVEL=info`, HTML logging disabled, a 60-second
browser timeout, and `https://www.google.com` as the test URL. The service
requests `150m` CPU and `800Mi` memory, and permits `2Gi` memory. There is no
CPU limit: numeric `resources.limits.cpu: 0` disables the TrueCharts default,
allowing browser challenge bursts. On October 21, 2026, the former `1000m`
cap throttled roughly 79–86 percent of CPU periods during DevFeed solver
traffic. Removing the cap addresses that throttling; upstream challenges can
still fail or time out, so verify real solver outcomes as well as readiness.
On September 21,
2026, a browser workload was OOMKilled under the former 1536Mi cap; the sampled
48-hour working-set peak was 1518Mi. The 2Gi cap adds headroom for browser bursts.
Verify restarts and peak memory during real challenge traffic after rollout. DevFeed
serializes its requests through one solver worker and a shared lease; Prowlarr
remains an independent client, so monitor combined concurrency.

## Storage

FlareSolverr uses a bounded `emptyDir` for browser and runtime config. Its state
is disposable, so restarts begin cleanly without consuming replicated Longhorn
capacity or depending on the shared NAS.

## Network Boundary

Ingress is limited to Prowlarr and `devfeed/devfeed-worker-solver` on port `8191`.
Egress permits cluster DNS and public IPv4 HTTP(S) only, excluding private,
loopback, link-local, reserved, multicast and cluster ranges. IPv6 has no allow rule.
This boundary is required because a remote browser follows subresources and
redirects outside DevFeed's DNS-pinned transport. The service must remain internal;
browser behavior and upstream TLS checking are provider-specific.

## Operating Notes

- Keep this service internal; expose indexer workflows through Prowlarr.
- Watch CPU and memory when increasing browser-concurrency behavior.
- Change chart configuration in `values.yaml` and let Fleet reconcile.

The Fleet bundle and HelmOp fetch the pinned chart directly from its OCI repository.
They do not depend on the optional Rancher chart-catalog bundle, whose index refresh
failures must not block solver configuration repairs.
