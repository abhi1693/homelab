---
title: Loki stale NFS WAL recovery
---

# Loki stale NFS WAL recovery

## Symptoms and impact

`AlloyLogEntriesDropped` means entries were permanently discarded after retries.
In issue [#138](https://github.com/abhi1693/home-lab/issues/138), Loki returned
HTTP 500 with `write /var/loki/wal/00030396: stale file handle` while its pod
remained Ready and historical queries worked. Received-line counters continued
increasing even though successful WAL records did not. `LokiWALWritesStalled`
detects this lack of durable write progress under incoming traffic; it is not
a replacement for querying recent logs through the gateway.

`too_far_behind` rejects old entries relative to each stream's newest entry.
It is separate from a failed WAL append. Increasing the retention period or
ingestion rate does not repair an invalid NFS handle.

## Diagnose without changing live state

1. Read Alertmanager and collect direct Loki and Alloy pod logs. Record UTC
   timestamps, the failed segment, and per-producer drop counters. Use
   [the alert inventory runbook](alertmanager-firing-alert-triage.md).
2. Compare `increase(loki_distributor_lines_received_total[10m])` with
   `increase(loki_ingester_wal_records_logged_total[10m])`. An incoming request
   count alone cannot establish a successful write.
3. Record the pod, node, PVC and PV identities. Inspect the NFS server/export,
   mount options, and node kernel/storage events. Do not assume a WAN failover
   caused a stale handle on a LAN export.
4. If node SSH access is available, resolve the exact PVC mount under
   `/var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~csi/<pv>/mount`.
   Read-only `stat` and a checksum of the exact failed segment establish whether
   a fresh lookup/open works. Do not mount another export or run a write probe.
5. Query a narrow recent window for several known active namespaces and Faro
   through `loki-gateway`, recording newest timestamps. Compare with direct pod
   stdout. Preserve results privately if they contain application data.

On 19 October 2026 around 06:23 UTC, a fresh node-side open read the entire
7,012,352-byte failed segment successfully, while the running process still
returned ESTALE. No matching NFS kernel event was found in the inspected node
journal. This supports reopening the retained files; the server/export event
that invalidated the original handle remains unproven.

## Recovery through Fleet

Keep the existing `storage-loki-0` claim, WAL directory, checkpoints, TSDB data,
and filesystem chunk store. Never delete, rename, truncate or hide the WAL to
make the pod start. Do not disable the WAL.

The Git-managed `singleBinary.podAnnotations.home-lab.io/wal-recovery` value
requests one controlled StatefulSet replacement through Fleet. The
`20261019-issue-138` value identifies this recovery. Keep it stable during normal
reconciliation; change it only for a diagnosed, reviewed recovery. Allow for a
brief ingestion/query interruption because there is one Loki replica. Alloy
retries are bounded and cannot guarantee lossless delivery during downtime.

The values explicitly retain the WAL at `/var/loki/wal`, enable
`ingester.wal.flush_on_shutdown`, and allow 300 seconds for future graceful
shutdowns. The first replacement still uses the old pod's existing grace
period. Loki replays retained WAL on startup. If replay fails, preserve its logs
and files and investigate the exact error before attempting another recovery.

This reopens the failed handle and improves recovery visibility. It does not
eliminate the NAS failure domain. A move to block-backed WAL or object storage
requires a separate migration plan covering WAL replay, retained chunks,
capacity, downtime, and rollback. Do not change an existing PVC's storage class
or overlay an empty WAL volume over retained data.

## Verify and record loss

- Confirm Fleet's system GitRepo, Loki HelmOp and child bundle are Ready at the
  intended commit, and the replacement pod is Ready with zero restarts.
- Inspect startup/replay logs for errors and corruption; verify successful WAL
  records increase and gateway push responses no longer return the WAL error.
- Query fresh logs from several namespaces and Faro through the gateway. A
  successful old query or pod readiness alone is insufficient.
- Observe at least one full ten-minute alert lookback without new final Alloy
  batch drops or WAL errors, and extend monitoring when investigating an
  intermittent NAS fault. The existing drop alert can remain firing briefly
  after successful recovery. Check `too_far_behind` separately.
- Record any remaining rejections and irrecoverable loss. Entries discarded by
  Alloy before recovery are not restored by WAL replay. The exact missing set
  may be unknowable; Prometheus `increase` values are extrapolated estimates.

## Rollback

Revert the scoped values/rule change through Git and Fleet if it regresses.
Retain both the WAL and filesystem data throughout. A values rollback does not
undo already dropped logs or restore an invalidated NFS file handle.

## 19 October 2026 recovery evidence

Fleet replaced the pod at 06:26:25 UTC using the existing claim. Checkpoint and
segment replay completed at 06:26:28 UTC with `errors=false`; the replacement
became Ready with zero restarts. Gateway queries at approximately 06:28 UTC
returned current DevFeed, kube-system, ShipyardHQ and Faro entries. Narrow
historical queries also returned DevFeed and Faro entries from 17 October.
The next atomic WAL checkpoint completed successfully at 06:35:58 UTC.

By 06:35:50 UTC, the Alloy drop and Loki rejection alerts had cleared. The
concurrent Ryokan and PostgreSQL capacity alerts cleared after their separate
Fleet-managed expansions. The DevFeed availability alert remained an independent
application issue; its overview-panel 503s are not repaired by Loki recovery.
That burn alert subsequently expired as the error window improved, leaving
only the expected `Watchdog` at 06:36:51 UTC. Application performance work
remains tracked by DevFeed issues #216, #217 and #243 and their open PRs.

The pre-recovery 24-hour Alloy counter increases were approximately 955,000
entries cluster-wide, including Faro. This is an extrapolated estimate across
all causes, not an exact count of WAL-related loss or evidence those entries
were recovered. The original NAS/export invalidation event remains unknown.

## References

- [Loki WAL durability and replay](https://grafana.com/docs/loki/latest/operations/storage/wal/)
- [Loki app configuration](../../kubernetes/projects/system/apps/loki/README.md)
