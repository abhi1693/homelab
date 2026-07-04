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

FlareSolverr has a retained 1Gi Longhorn config PVC. This preserves browser and
runtime state across pod restarts.

## Network Boundary

Ingress is limited to Prowlarr on port `8191`. Egress allows DNS and external
web traffic outside the pod and service CIDRs.

## Operating Notes

- Keep this service internal; expose indexer workflows through Prowlarr.
- Watch CPU and memory when increasing browser-concurrency behavior.
- Change chart configuration in `values.yaml` and let Fleet reconcile.
