# Valkey

This bundle installs the shared Valkey cache and queue service for the lab
through a Fleet `HelmOp`.

## Runtime Shape

- Namespace: `valkey`
- Chart: Bitnami `valkey` from `oci://registry-1.docker.io/bitnamicharts/valkey`
- Release: `valkey`
- Architecture: replicated Valkey with Sentinel enabled
- Storage: three retained Longhorn-backed 1Gi PVCs, each with one storage
  replica
- Metrics: chart exporter and `ServiceMonitor` are enabled
- Replica data-container memory: recommendation-managed request with a manually
  maintained `384Mi` limit that leaves headroom for safe request proposals

The chart runs with authentication disabled. Access control is provided by the
cluster network boundary in the separate `valkey-networkpolicy` bundle.

Valkey maintains one primary and two application-level replicas on separate
nodes. The scoped `longhorn-volume-overrides` Fleet bundle therefore reduces
the three backing volumes from three Longhorn replicas to one, lowering
scheduled block capacity from 9Gi to 3Gi. A single PVC no longer survives its
backing disk failing; Sentinel failover to another Valkey pod provides service
availability. This service is not an independent backup, so durable producers
must remain able to reconstruct queue or cache state.

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
Wardn Hub, ShipyardHQ, and Harbor. Prometheus can scrape metrics on
port `9121`. Valkey pods can also talk to each other on Valkey and Sentinel
ports.

## Operating Notes

- Change chart behavior in `values.yaml`, not by patching live workloads.
- Keep client additions paired with `valkey-networkpolicy` updates.
- Keep the retained PVC policy in mind before deleting or renaming the release.
- Add any replacement PVC's Longhorn volume ID to the scoped override before
  considering its storage replication reduced.
- Keep the replica memory limit above recommendation-engine request headroom;
  the engine manages requests but does not update paired limits.
- Validate with a server-side dry run when a cluster context is available.
