# Pyroscope

Lightweight single-pod Grafana Pyroscope backend for continuous profiling.

This deployment is scoped for a k3s home lab:

- one ARM64 pod in `cattle-monitoring-system`;
- local filesystem storage on the retained `2Gi` Longhorn RWO claim
  `pyroscope-data`;
- 24-hour v2 retention (`-retention-period`) and query lookback;
- Grafana access through the provisioned `Pyroscope` datasource;
- Prometheus scraping of Pyroscope's own `/metrics`;
- profiling traffic from the instrumented ShipyardHQ web and worker pods.

The pod uses the Pyroscope v2 storage architecture in single-binary mode. The
Deployment keeps one writer and uses `Recreate` so replacements release the RWO
volume before the next pod attaches it. Longhorn uses the storage class's three
replicas. Profiles, metadata, Raft state, WAL and snapshots all live below the
same `/var/pyroscope` mount and survive pod replacement. Longhorn replication
does not provide an application backup or make this single-pod backend highly
available; replacement briefly interrupts ingestion and queries.

The claim is bounded at `2Gi`, with 24-hour retention and query limits. V2 retention operates on
partitions and deletes objects asynchronously, so 24 hours is not a strict disk
quota or an exact deletion deadline. Watch PVC capacity, metastore cleanup,
compaction, ingestion and memory. Increase the requested storage through Git
before the claim fills. Do not use v1 `pyroscopedb` disk-retention flags for this
v2 deployment.

The Raft WAL and snapshots both live under `/var/pyroscope/v2/metastore/raft`.
Set both `-metastore.raft.dir` and `-metastore.raft.snapshots-dir`: the snapshot
path has an independent default inside the container filesystem. Keeping only
the WAL on the volume loses snapshots on container replacement and can cause
`panic: log not found` when Raft replays compacted logs. Container restarts retain
the complete state, and the PVC retains it across pod replacement.
The pod has 120 seconds to shut down Raft and in-flight compaction cleanly.

The pod requests `128Mi` of memory and has a `256Mi` container limit, while
`GOMEMLIMIT=120MiB` keeps the Go runtime target conservative. The runtime target
does not bound all resident memory. Review cgroup usage, compaction peaks,
readiness and ingestion after resource changes. The configured memory limit
must leave room for Go heap, mapped files, Raft and compaction buffers.

`-compaction-worker.job-concurrency=1` serializes compaction to bound overlapping
memory demand. Monitor compaction, ingestion and memory peaks before increasing
concurrency.

## Recovery and validation

For a missing-snapshot failure, retain and archive the entire PVC before an
operator recovery action. Do not delete the WAL independently of its snapshots,
and do not roll back to a configuration that stores snapshots outside the
volume. The PVC has `helm.sh/resource-policy: keep`; removing the workload is not
authorization to remove its history. Storage administrators must separately
review PVC/PV deletion and the underlying storage class's reclaim policy.

Validate changes with a server-side dry run, then verify the Pyroscope Fleet
BundleDeployment's desired and applied deployment IDs match with `Installed`
and `Ready` true, the new pod is Ready without restarts, `/ready` succeeds,
and a profile can be ingested and
queried through Grafana. Before rollout, the local Docker validation below uses
the deployed image, memory bounds, UID and arguments. Only its fixture lowers the
Raft snapshot threshold, interval and trailing-log count. It ingests a uniquely
named profile, creates a snapshot and compacts the WAL, replaces the container
while reusing its data volume, and queries the same historical profile after
snapshot restoration. It needs Docker and Python with PyYAML; the disposable
cleanup helper uses `busybox:1.37.0`.

```sh
python scripts/validate-pyroscope.py
kubectl --kubeconfig ~/.kube/config apply --dry-run=server -f kubernetes/projects/system/apps/pyroscope/pvc.yaml
kubectl --kubeconfig ~/.kube/config apply --dry-run=server -f kubernetes/projects/system/apps/pyroscope/deployment.yaml
kubectl --kubeconfig ~/.kube/config -n cattle-monitoring-system get pods -l app.kubernetes.io/name=pyroscope
kubectl --kubeconfig ~/.kube/config -n cattle-monitoring-system logs deploy/pyroscope
```

DevFeed API/frontend and execution processes also send profiles over the private
4040 listener, restricted to namespace `devfeed` and label `devfeed-telemetry=true`.
Python native profiling initializes only after the final RQ fork; parent workers
export their process/execution metrics independently. Default sampling is 19 Hz CPU
and 1 MiB heap allocation intervals. Monitor ingest/storage/memory growth as this
profiling workload changes; preserve 24-hour retention and storage ownership.

Upstream references: [v2 architecture](https://grafana.com/docs/pyroscope/latest/reference-pyroscope-v2-architecture/about-pyroscope-v2-architecture/),
[metastore persistence](https://grafana.com/docs/pyroscope/latest/reference-pyroscope-v2-architecture/components/metastore/),
and the [v2.4.0 Raft configuration](https://github.com/grafana/pyroscope/blob/v2.4.0/pkg/metastore/raftnode/node.go).

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom; existing burst
policies remain in place. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container / value path | CPU request | Memory request | Memory limit |
| --- | --- | --- | --- |
| `cattle-monitoring-system/pyroscope/pyroscope` | 10m → 100m | 128Mi → 224Mi | 256Mi → 256Mi |
