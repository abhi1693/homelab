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

The claim is bounded at `2Gi`, matching the previous ephemeral cap. The current
24-hour retention and query limits remain in place. V2 retention operates on
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
the complete state, and the PVC now also retains it when the pod is replaced.
The pod has 120 seconds to shut down Raft and in-flight compaction cleanly.

The pod requests `128Mi` of memory and has a `256Mi` container limit, while
`GOMEMLIMIT=120MiB` keeps the Go runtime target conservative. The runtime target
does not bound all resident memory. On 5 October 2026 the previous `160Mi` cap
caused repeated OOM kills during v2 compaction, including a restart killed just
after a level-2 job began. Prometheus recorded about `160Mi` resident/container
memory despite a Go heap peak of about `81Mi`; the working-set peak was about
`133Mi`. The higher container cap leaves room for compaction and memory outside
the Go runtime without increasing the runtime target.

`-compaction-worker.job-concurrency=1` limits compaction to one job at a time.
The default uses the node's CPU count, which started four workers on these
Raspberry Pi nodes. Serial compaction reduces overlapping memory demand; monitor
completed jobs, ingestion, memory peaks, and restarts before increasing it.
Changing the Deployment replaces the pod while preserving its profiling history
on the existing claim.

## Recovery and validation

The first `emptyDir` to PVC cutover starts a new queryable profiling history.
Archive the surviving old data and export representative profiles before the
Fleet-managed replacement. An archive taken while ingestion continues is best
effort and is not a consistent backup. It preserves files for offline recovery
but does not make old profiles queryable in the new backend. Later replacements
reuse the claim and preserve their existing history.

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
additional workload establishes its baseline; existing 24-hour retention and
storage ownership are preserved.

Upstream references: [v2 architecture](https://grafana.com/docs/pyroscope/latest/reference-pyroscope-v2-architecture/about-pyroscope-v2-architecture/),
[metastore persistence](https://grafana.com/docs/pyroscope/latest/reference-pyroscope-v2-architecture/components/metastore/),
and the [v2.4.0 Raft configuration](https://github.com/grafana/pyroscope/blob/v2.4.0/pkg/metastore/raftnode/node.go).
