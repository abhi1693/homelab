# FlareSolverr

This bundle installs FlareSolverr through a Fleet `HelmOp` for indexers that
require browser-challenge handling.

## Runtime Shape

- Namespace: `media`
- Chart: TrueCharts `flaresolverr`
- Release: `flaresolverr`
- Service: ClusterIP on port `8191`
- Image: Harbor proxy path for `ghcr.io/flaresolverr/flaresolverr`

There is no user-facing ingress. Prowlarr is the intended in-cluster client.

## Configuration

The container runs with `LOG_LEVEL=info`, HTML logging disabled, a 60-second
browser timeout, and `https://www.google.com` as the test URL.

## Storage

FlareSolverr uses a bounded `emptyDir` for browser and runtime config. Its state
is disposable, so restarts begin cleanly without consuming replicated Longhorn
capacity or depending on the shared NAS.

The detached PVC from the former persistent configuration was retired after
verifying that the current chart renders the config volume as `emptyDir`.

## Network Boundary

Ingress is limited to Prowlarr on port `8191`. Egress allows DNS and external
web traffic outside the pod and service CIDRs.

## Operating Notes

- Keep this service internal; expose indexer workflows through Prowlarr.
- Watch CPU and memory when increasing browser-concurrency behavior.
- Change chart configuration in `values.yaml` and let Fleet reconcile.
