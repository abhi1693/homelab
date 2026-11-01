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
allowing browser challenge bursts. The 2Gi memory limit bounds browser usage.
Verify solver outcomes, timeouts, restarts and peak memory under real traffic;
readiness alone does not establish successful challenge handling. DevFeed
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

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `media/flaresolverr/flaresolverr` | 150m → 200m | 800Mi → 1024Mi | 2Gi → 2560Mi |

## CPU reservation

CPU request is 75m; browser work retains its uncapped CPU burst policy.
