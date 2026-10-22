# Trace and profile persistence

Tempo and Pyroscope each use a 2Gi `ReadWriteOnce` Longhorn PVC in
`cattle-monitoring-system`. The existing Longhorn StorageClass requests three
replicas on separate storage nodes. Both backends retain 24 hours of telemetry;
retention processing is asynchronous and needs space for WALs and compaction.
The claims are bounded capacity, not an automatically expanding telemetry store.

| Backend | Claim | Durable paths | Runtime |
| --- | --- | --- | --- |
| Tempo | `tempo-data` | `/var/tempo`: trace blocks, live-store WAL/shutdown marker and metrics-generator WAL | One Deployment replica, Recreate |
| Pyroscope | `pyroscope-data` | `/var/pyroscope`: v2 profile blocks, metastore data, Raft WAL and snapshots | One Deployment replica, Recreate |

Keep each backend at one writer. `ReadWriteOnce` alone does not prevent two pods
on the same node from mounting a volume. Recreate updates stop the old writer
before its replacement, with 120 seconds for graceful termination. UID/GID and
filesystem group remain 10001. Do not remove the filesystem group or split Raft
logs and snapshots across different lifecycles.

Longhorn replication provides storage redundancy; it does not make the two
single-instance backends highly available. Queries and ingestion can pause while
a pod restarts or its volume reattaches. Configure and inspect client retry/queue
behavior when investigating a rollout gap. Pending in-memory samples are not
made durable merely by adding a PVC.

## Initial cutover

The old deployments stored roughly 184MiB of traces and 456MiB of profiles in
`emptyDir`. Before replacement, private host archives and representative trace/
profile query exports were saved outside Git. These are evidence copies, not
verified consistent backups: live Raft/WAL/BoltDB files can change while being
read. Do not restore the raw archives over a running service or claim lossless
online migration.

The initial PVC cutover starts new queryable history. The old pod's temporary
history does not become queryable from the new claim. Subsequent pod replacements
reuse the claim and preserve on-disk history, subject to the 24-hour retention.

Deploy through Git and Fleet:

1. Create the PVCs and inventory them in each workload catalog, leaving the
   current pods unchanged. Check binding, capacity and storage scheduling.
   The current manifests pin their assigned `volumeName` fields because Fleet's
   forced Helm replacement must not clear an immutable binding. On a fresh
   cluster, remove the old pins before provisioning, then record the newly
   assigned bindings in Git before updating a backend. Never substitute another
   volume for an existing data claim during routine reconciliation.
2. Save available pre-cutover evidence. Move one backend at a time to its PVC,
   retaining the existing image, services, selectors, data paths and retention.
3. Wait for Fleet desired/applied IDs to agree and both `Installed` and `Ready`
   conditions to be true. Also require pod readiness, healthy volume replication
   and a successful write/query round trip before moving the other. Matching IDs
   alone can coexist with a failed Helm installation.
4. Record a trace ID and fixed profile query window on persistent storage.
   Publish a harmless pod annotation revision through Fleet to replace each pod,
   then retrieve the same historical data after recovery. Record new pod UIDs,
   unchanged PVC UIDs/bindings, readiness and restart counts.

Never use a manual rollout restart, delete, Helm upgrade or live patch for these
steps. Avoid overlapping unrelated storage maintenance or compaction experiments.

## Retention and recovery

Both claims carry `helm.sh/resource-policy: keep` so release removal does not
silently remove the data claim. This does not prevent an explicit PVC deletion:
the Longhorn StorageClass has a Delete reclaim policy. Do not remove claims as
part of an application rollback. Reverting to `emptyDir` would disconnect the
retained history and begin another temporary store.

Keep Pyroscope's `metastore.raft.dir` and `metastore.raft.snapshots-dir` together
on the volume; restoring only a WAL whose earlier entries were compacted can
produce `panic: log not found`. Preserve the entire volume during investigation.
For Tempo, preserve both completed blocks and the live-store WAL. An abrupt stop
can lose samples that had not reached durable storage; successful readiness
alone does not establish historical query recovery.

Replication is not an independent backup. These telemetry claims have no
independent scheduled backup configured. For an independent backup, use a
supported application-consistent procedure and verify restoration before
claiming a recovery guarantee. Inspect PVC free space and volume health through
existing Kubernetes/Longhorn alerts; reduce collection volume or expand through
Git before a claim fills.

## Validation

```sh
python scripts/validate-tempo.py
python scripts/validate-pyroscope.py
kubectl apply --dry-run=server -f kubernetes/projects/system/apps/tempo/pvc.yaml -f kubernetes/projects/system/apps/tempo/configmap.yaml -f kubernetes/projects/system/apps/tempo/deployment.yaml
kubectl apply --dry-run=server -f kubernetes/projects/system/apps/pyroscope/pvc.yaml -f kubernetes/projects/system/apps/pyroscope/deployment.yaml
```

The Docker validators exercise the deployed version and configuration, ingestion,
historical queries, and replacement containers sharing the same data directory.
Pyroscope also exercises Raft snapshots and log compaction. These checks run in
separate ARM64 GitHub workflows. Live acceptance additionally checks both
Prometheus targets, Grafana datasources, OpenTelemetry exports, Fleet and storage
replicas. Full procedure and version-specific recovery details are in the
[Tempo](../../kubernetes/projects/system/apps/tempo/README.md) and
[Pyroscope](../../kubernetes/projects/system/apps/pyroscope/README.md) READMEs.

## Acceptance on 2026-10-19

After both claims were attached, a trace and a uniquely marked profile were
written and queried. Fleet then replaced both pods using storage revision
`2026-10-19-persistent-history`. The new pod UIDs returned the same historical
trace and profile without reinjection. Tempo's normal and completed-block-only
responses matched the pre-replacement trace; Pyroscope returned the same marker
and sample total from the original fixed query window.

Both claims kept their UIDs and PV bindings. Both pods were Ready with zero
restarts and each volume had three healthy running replicas. The separate ARM64
[Tempo](https://github.com/abhi1693/home-lab/actions/runs/39227619771) and
[Pyroscope](https://github.com/abhi1693/home-lab/actions/runs/39227619815)
recovery checks also passed. Private before/after inventories and query evidence
are saved outside Git. OpenTelemetry retried exports during replacement and
its queues drained afterward; no permanent export-drop records were observed.
This verifies the tested graceful replacements, not arbitrary crash recovery or
an independent backup.
