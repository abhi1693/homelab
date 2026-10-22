# Alloy Node Logs

Fleet runs one Grafana Alloy DaemonSet pod on every Linux ARM64 node. It reads
node-local CRI container files and the K3s server, K3s agent, and kernel journals.
The existing `alloy-logs` Deployment remains responsible for Kubernetes events.

## Collection and storage boundary

The chart is pinned to `alloy` 1.13.1, which runs Alloy 1.20.1. Every node requests
55m CPU and 144Mi memory across Alloy and its configuration reloader, with memory
limits of 256Mi and 32Mi respectively. The chart's HTTP readiness probe and a
60-second ServiceMonitor cover all DaemonSet instances. Rolling updates replace
at most one collector at a time, without running two readers of the same node's
positions file. All node taints are tolerated so control-plane logs are included.

Pod discovery uses the `spec.nodeName` field selector. Only that node's
`/var/log/pods/*<pod-uid>/<container>/*.log` files are read. Active readers follow
a renamed file through EOF during kubelet rotation. Timestamped/compressed
rotated files are not rediscovered after collector downtime: globbing both the
active path and every renamed path would replay the same inode under two names.
Deleted pods lose their API metadata discovery target, and a collector starting
while the API is unavailable cannot discover new containers until it recovers.
The standard stable Alloy components preserve the existing application labels;
filesystem-only orphan discovery/enrichment needs a separate design. CRI parsing joins
partial records and restores their original timestamps before JSON processing.
Partial record buffering is capped at 100 entries of 256KiB each; oversized
partial records are truncated. The existing `namespace`, `pod`, `container`,
`node`, `app`, `part_of`, `component`, `job="<namespace>/<container>"`, and
`cluster="local"` labels are preserved. CRI `filename`, `stream`, and `flags`
are removed before writing. DevFeed JSON retains its `service` and `severity`
labels. Request, trace, job, process, boot, and container IDs remain outside the
stream label set.

Three separate journal sources match exactly `_SYSTEMD_UNIT=k3s.service`,
`_SYSTEMD_UNIT=k3s-agent.service`, and `_TRANSPORT=kernel`. They search both
`/var/log/journal` and `/run/log/journal`, so volatile journals are included. The
JSON body retains `MESSAGE`, `PRIORITY`, `_SYSTEMD_UNIT`, `_BOOT_ID`, and other
original journal metadata. Bounded labels are `cluster`, `node`, `source`,
`unit`, and `job`; use `job="node/k3s"` or `job="node/kernel"` in Loki.
Authentication/session and other host system journals are outside the filters.
Initial journal backfill is limited to five minutes. Quiet kernel sources can
have no recent entries even when their readers are healthy; do not generate
host log messages merely to make a dashboard nonempty.

`/var/lib/alloy-node-logs` is a per-node hostPath on the local NVMe root
filesystem. It stores file offsets and journal cursors, which survive collector
rollouts and node reboots. Keep the component names and this path stable. It is
not a durable delivery queue: pending Loki batches remain in memory. Node loss,
journal vacuuming, deleted pod discovery targets, and kubelet rotation can still
remove unread data. File offsets are checkpointed when a line arrives after the
checkpoint interval or the reader shuts down gracefully. A quiet file consumed
within one interval can retain its first-line checkpoint until shutdown; an
abrupt crash can replay more than one interval from that file. A stale journal
cursor is bounded by the five-minute journal lookback. All sources filter entries older than Loki's 336-hour acceptance
window before batching. Writes use 256KiB batches, retry HTTP 429/transient
failures with 1s–1m backoff, and stop after 20 retries.

The only writable host mount is Alloy's own state directory. Pod logs, both
journal directories, and `/etc/machine-id` are mounted read-only. Host CRI files
are `root:root 0640`, so Alloy runs as UID/GID 0 with every Linux capability
dropped, privilege escalation disabled, a read-only root filesystem and the
runtime default seccomp profile. It has no host networking, host PID namespace,
privileged mode, runtime socket, or host root mount. RBAC grants only
`get/list/watch` on pods. Network policies permit DNS, Kubernetes API discovery,
Loki gateway TCP/8080, and Prometheus ingress on TCP/12345. There is no Alloy
clustering or peer traffic for local files.

## Three-stage pod log handover

The first stage has `nodeLogs.podLogsEnabled: false`. Journals are written to
Loki immediately. File readers use `tail_from_end: false`, consume existing
current/restart log files locally, advance in-memory offsets, and discard their
output with reason `migration_priming`. Quiet-file offsets are fully persisted
when the reader shuts down gracefully; seeking EOF does not persist an initial
offset until the next record arrives. Local backfill uses disk/CPU but never
goes to Loki. The existing API collector continues writing pod logs during this
stage, preventing an uncontrolled replay of historical files into Loki.

1. Let Fleet deploy the initial DaemonSet. Verify every eligible node is Ready,
   the ServiceMonitor is healthy, and each node has discovered and read its
   local files. Check K3s journal delivery and each journal reader's health.
   Establish that current discovered files have drained by comparing per-path
   `loki_source_file_read_lines_total` with read-only file newline counts taken
   immediately beforehand. Checkpointed byte offsets can lag on quiet files
   even after the reader catches up.
2. Set `nodeLogs.podLogsEnabled: true` and add/change the DaemonSet annotation
   `controller.podAnnotations.home-lab.io/log-handover-stage` to a new value,
   such as `forwarding-v1`. Keep the old API pod reader active throughout this
   rollout. A rolling pod replacement is required: the old reader gracefully
   flushes its final positions before the enabled replacement starts. A
   configuration reload alone does not flush quiet-file checkpoints. Existing
   files resume from saved offsets, and new files are read from their
   beginning. Verify all eligible nodes are Ready and forwarding into Loki.
3. In a later Git change, remove only the API pod source and its pod-discovery/
   processing blocks from `alloy-logs`. Keep its clustered Kubernetes event
   source. The overlap intentionally retains pod log coverage during the
   DaemonSet rollout and can duplicate records until this removal finishes.

Record all rollouts' start and completion times. Fleet does not switch two
releases atomically. Check representative pod, event, K3s, and kernel streams;
query permanent drops, Loki rejection reasons, and duplicate timestamps in the
bounded overlap. After cutover, `migration_priming` must stop increasing. Keep
the state directories and component IDs intact across subsequent config changes.

Before the handover, rolling back means retaining the API pod source. After the
handover, prefer repairing the DaemonSet through Fleet; re-enabling API pod
collection can replay logs and should be treated as another measured handover.
Do not delete state directories as a routine recovery step.

## Validation and evidence

```sh
kubectl kustomize kubernetes/projects/system/apps/alloy-node-logs
python3 kubernetes/projects/system/apps/alloy-node-logs/test_pipeline.py
python3 scripts/validate-workload-catalog.py
```

The pipeline check renders both stages with the pinned Helm chart, validates
both configurations with the pinned Alloy binary in local Docker, and runs a
local fixture to check quiet multiline priming, graceful checkpoint flushing,
and offset preservation through handover, CRI partial-line
joining/timestamps, live log rotation, DevFeed labels, and expired-entry rejection. It does not
write to the cluster or Loki.

For deployment validation, use a server-side dry run of the rendered Helm
resources and the Kustomize bundle. After Fleet reconciliation:

```sh
kubectl -n cattle-monitoring-system get daemonset alloy-node-logs
kubectl -n cattle-monitoring-system get pods -l app.kubernetes.io/instance=alloy-node-logs -o wide
kubectl -n cattle-monitoring-system get servicemonitor alloy-node-logs
kubectl -n cattle-monitoring-system logs -l app.kubernetes.io/instance=alloy-node-logs -c alloy --since=10m --prefix
```

Check `loki_source_file_files_active_total`,
`loki_source_file_read_lines_total`, journal read/error counters, and
`loki_write_dropped_entries_total` per collector. Query journals with
`{cluster="local",source="journal",job="node/k3s"} | json` and
`{cluster="local",source="journal",job="node/kernel"} | json`.
Availability alerts compare DaemonSet available/desired nodes and detect missing
scrapes. Existing central logging alerts continue to report rejected/dropped
records; readiness alone does not establish successful end-to-end delivery.

References: [Alloy journal source](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.journal/),
[file source and positions](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.file/),
[CRI processing](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/#stagecri),
and [node-local discovery](https://grafana.com/docs/alloy/latest/reference/components/discovery/discovery.kubernetes/#limit-to-only-pods-on-the-same-node).
