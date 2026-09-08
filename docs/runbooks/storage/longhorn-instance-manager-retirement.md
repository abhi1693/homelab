# Longhorn instance-manager retirement

Requires explicit task-specific break-glass authorization and independently
verified recovery copies. This is not routine GitOps reconciliation.

Live engine upgrades leave engine processes in older instance managers until
their volumes detach. Never force-delete those managers or volume attachments.
See the [upstream procedure](https://longhorn.io/docs/1.12.1/deploy/upgrade/instance-manager-pods-during-upgrade/).

For one controller-owned RWO workload at a time:

```sh
python scripts/longhorn-reattach-pod.py NAMESPACE POD --recovery-verified
```

The helper checks all volumes and three writable replicas, temporarily cordons
the pod's node, normally deletes only that pod, and requires its replacement on
another node to be Ready with its engines in 1.12.1 instance managers. It always
restores node scheduling. No storage objects are deleted, no Fleet desired state
is changed, and a failure stops the sequence for inspection.
For workloads pinned by hostname, it requires full detachment while the
replacement is unscheduled, then permits reattachment on the original node.
Best-effort data locality can build a fourth temporary replica after a move.
Even if the workload is Ready and three replicas remain writable, wait for
that rebuild to finish and the count to settle back to three before continuing.
Large Prometheus volumes can take several minutes; inspect `rebuildStatus`
for forward progress rather than deleting replicas or bypassing the gate.
Check application behavior and replication after each operation. PostgreSQL and Valkey primaries
are rejected: relocate healthy replicas first, perform a controlled switchover,
then relocate the former primary. RWX requires a separate all-client shutdown.

CNPG also initiates a switchover when its primary's node is cordoned for an
unrelated workload. The helper rejects any node hosting a CNPG primary, not
just the primary pod. Perform a controlled `kubectl cnpg promote -n NAMESPACE
CLUSTER INSTANCE` first and verify all instances Ready and streaming before
retrying. For Home Assistant's reviewed single-client RWX claim, the separate
`scripts/longhorn-reattach-home-assistant.py --recovery-verified` helper stops
the client, requires full detachment, and always restores its replica count.

Keep the independent pre-upgrade recovery copy and native backup metadata.
UNAS does not support NFSv4; do not try to repair an unsupported protocol. An
SMB/CIFS target is supported by Longhorn. MinIO over NFS has documented storage
consistency limitations and its community upstream is archived; it must not be
silently substituted as a guaranteed permanent recovery service.

## 2026-09-05 completion

All eleven old instance managers retired automatically. The final state is
eight 1.12.1 managers, 26 running engines, and exactly three writable replicas
per volume (78 total). Both RWX share managers run 1.12.1. All eight nodes are
Ready and uncordoned. PostgreSQL has three Ready instances and two streaming
replicas; Valkey has one primary, two linked replicas, and aligned Sentinels.
Both Prometheus replicas and Home Assistant recovered Ready with zero restarts.
The large Prometheus locality copies were allowed to complete before continuing.

The eleven retired managers released 5.28 CPU cores. Including the new 100m
temporary MinIO server, active regular-container requests fell from 21.12 to
15.94 cores (49.8125% of 32). This is a PodSpec request sum, not CPU utilization
or a claim that all placement constraints disappear. No storage CPU guarantee
was reduced. Full Longhorn Ansible validation passed on all eight hosts.

The temporary S3 target has 19 Completed backups (18 imported and one fresh).
Fresh Prowlarr and imported OpenBao backups passed isolated restore, journal
replay, and read-only filesystem checks. The PC copy remains 6,277 files and
6,427,619,184 bytes; no recovery data was deleted. The restore port-forward is
closed. One stale failed trim Job from August 28 was removed after confirming
the September 5 run succeeded; no CronJob, volume, or backup data was removed.

The Prometheus restarts briefly interrupted each replica-specific OpenTelemetry
export destination. At 09:22:57 UTC, queued metric batches were rejected with
HTTP 400 by the returning second destination and some samples were dropped;
the other Prometheus replica remained available. Subsequent delivery resumed,
with zero export failures over two minutes and empty queues. The corresponding
warning uses a ten-minute lookback, so verify it clears after that window;
do not suppress the alert or mistake an empty queue alone for lossless delivery.
