# Valkey

This bundle installs the shared Valkey cache and queue service for the lab
through a Fleet `HelmOp`.

## Runtime Shape

- Namespace: `valkey`
- Chart: Bitnami `valkey` from `oci://registry-1.docker.io/bitnamicharts/valkey`
- Release: `valkey`
- Architecture: replicated Valkey with Sentinel enabled
- Storage: Longhorn-backed 1Gi primary and replica PVCs with retained volume
  policy
- Metrics: chart exporter and `ServiceMonitor` are enabled

The chart runs with authentication disabled. Access control is provided by the
cluster network boundary in the separate `valkey-networkpolicy` bundle.

## Client Contract

Applications should connect through Sentinel when they need failover-aware
Redis-compatible access:

```text
valkey.valkey.svc.cluster.local:26379
sentinel set: valkey
```

Direct Valkey traffic uses port `6379`; Sentinel uses port `26379`. App READMEs
should document their logical DB index or key namespace when they use this
shared service.

## Network Boundary

`valkey-networkpolicy` allows access from approved clients such as NetBox,
GitRank, Wardn Hub, ShipyardHQ, and Harbor. Prometheus can scrape metrics on
port `9121`. Valkey pods can also talk to each other on Valkey and Sentinel
ports.

## Operating Notes

- Change chart behavior in `values.yaml`, not by patching live workloads.
- Keep client additions paired with `valkey-networkpolicy` updates.
- Keep the retained PVC policy in mind before deleting or renaming the release.
- Validate with a server-side dry run when a cluster context is available.
