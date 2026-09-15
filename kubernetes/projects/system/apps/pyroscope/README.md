# Pyroscope

Lightweight single-pod Grafana Pyroscope backend for continuous profiling.

This first deployment is intentionally scoped for a k3s home lab:

- one ARM64 pod in `cattle-monitoring-system`;
- local filesystem storage on a `2Gi` `emptyDir`;
- 24-hour v2 retention (`-retention-period`) and query lookback;
- Grafana access through the provisioned `Pyroscope` datasource;
- Prometheus scraping of Pyroscope's own `/metrics`;
- profiling traffic from the instrumented ShipyardHQ web and worker pods.

The pod uses the Pyroscope v2 storage architecture in single-binary mode. The
storage is non-durable by design so this can be evaluated without adding
Longhorn write load. Move this to a PVC only after profile volume and resource
usage are known.

The Raft WAL and snapshots both live under `/var/pyroscope/v2/metastore/raft`.
Set both `-metastore.raft.dir` and `-metastore.raft.snapshots-dir`: the snapshot
path has an independent default inside the container filesystem. Keeping only
the WAL on the volume loses snapshots on container replacement and can cause
`panic: log not found` when Raft replays compacted logs. Container restarts retain
the complete state; deleting or replacing the pod still discards the `emptyDir`.

`GOMEMLIMIT=120MiB` leaves headroom below the container's `160Mi` memory limit.
It is a Go runtime target, not a hard limit; monitor actual memory consumption.

## Recovery and validation

For a missing-snapshot failure, archive the surviving `emptyDir` data before a
Fleet-managed Deployment change replaces the pod. A clean pod starts a new
profiling history; the archive preserves old files for offline recovery but does
not make them queryable. Do not delete the WAL independently of its snapshots.
Do not roll back to a configuration that stores snapshots outside the volume.

Validate changes with a server-side dry run, then verify the Pyroscope Fleet
BundleDeployment's desired and applied deployment IDs match, the new pod is
Ready without restarts, `/ready` succeeds, and a profile can be ingested and
queried through Grafana. Before rollout, use a local container test to create
snapshots and compact the WAL, replace the container while reusing its data
volume, and verify snapshot restoration and profile queries.

```sh
kubectl --kubeconfig ~/.kube/config apply --dry-run=server -f kubernetes/projects/system/apps/pyroscope/deployment.yaml
kubectl --kubeconfig ~/.kube/config -n cattle-monitoring-system get pods -l app.kubernetes.io/name=pyroscope
kubectl --kubeconfig ~/.kube/config -n cattle-monitoring-system logs deploy/pyroscope
```

DevFeed API/frontend and execution processes also send profiles over the private
4040 listener, restricted to namespace `devfeed` and label `devfeed-telemetry=true`.
Python native profiling initializes only after the final RQ fork; parent workers
export their process/execution metrics independently. Default sampling is 19 Hz CPU
and 1 MiB heap allocation intervals. Monitor ingest/storage/memory growth as this
additional workload establishes its baseline; existing 24-hour ephemeral retention
and storage ownership are preserved.
