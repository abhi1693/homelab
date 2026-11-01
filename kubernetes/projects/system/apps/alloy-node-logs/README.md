# Alloy Node Logs

Fleet runs one Grafana Alloy DaemonSet pod on every Linux ARM64 node. It reads
node-local CRI container files and the complete retained system journal, then
normalizes records into OpenTelemetry and sends OTLP/HTTP to Loki. This includes
kernel, K3s, networking, time synchronization, systemd, storage, authentication,
boot and shutdown records. The `alloy-logs` Deployment owns Kubernetes events;
Faro retains its separate receiver. API audit files are also collected through
a narrow, read-only host directory alias. An explicit file allowlist adds package
installation and bootstrapping evidence that is absent from the journal. No
content redaction is applied.

## Sources and identity

The chart remains pinned to `alloy` 1.13.1 and Alloy 1.20.1. The deployment opts
into `--stability.level=public-preview` because `otelcol.storage.file` is Public
Preview in that version. The native YAML OTel engine is not used. Rolling updates
replace at most one collector per node, and all node taints are tolerated.

Each Alloy container requests 100m CPU/384Mi memory and is capped at 250m CPU
and 640Mi memory. `GOMAXPROCS=1` bounds execution parallelism; the `256MiB`
`GOMEMLIMIT` soft target leaves room for journal mappings and the bbolt queue.
The reloader requests 5m CPU/32Mi memory and is capped at 25m CPU/64Mi memory.
The 64MiB serialized payload budget bounds active queue data; resident mapped
pages and file cache still count against the container limit. CPU and memory
reservations are unchanged by this replay tuning.

Pod discovery still uses `spec.nodeName`; only that node's
`/var/log/pods/*<pod-uid>/<container>/*.log` paths are read. The
`loki.source.file.pods` component and its existing positions remain stable.
Active readers follow renamed files through EOF during rotation. Timestamped or
compressed rotations are not rediscovered after downtime. Deleted Pods can lose
their discovery target, and a collector starting during an API outage cannot
discover new containers. The OS journal readers do not need Kubernetes discovery.
Filesystem-only pod discovery is deferred to a separate handover.

CRI processing retains original timestamps and joins partial records, with a
100-entry, 256KiB-per-entry partial buffer; oversized partials are truncated. The
existing `namespace`, `pod`, `container`, `node`, `app`, `part_of`, `component`,
`job`, `cluster`, and DevFeed `service`/`severity` selectors are retained as OTel
resource attributes, with an explicit Loki index mapping. `filename`, `stream`
and `flags` are removed as before. The OTel schema also adds `k8s.cluster.name`,
`k8s.node.name`, `k8s.namespace.name`, `k8s.pod.name`, `k8s.container.name`,
`host.name` and `service.name`. Dynamic identifiers do not become index labels.

The original `k3s_server`, `k3s_agent` and `kernel` journal component IDs and
cursors remain unchanged. The new `system` reader excludes those sources before
forwarding, leaving one authoritative path per journal record. All four readers
search `/var/log/journal` and `/run/log/journal`. Their explicit `max_age = "0s"` mode reads all bounded retained records, including boot records written with
an incorrect clock; it does not extend host retention. The owning Ansible OS
policy bounds journal disk use and retention independently.

Journal JSON bodies remain unchanged, including `MESSAGE`, `PRIORITY`,
`_SYSTEMD_UNIT`, `_TRANSPORT`, `_BOOT_ID`, and the other fields exposed by Alloy.
OpenTelemetry attributes provide `host.boot.id`, `systemd.unit`,
`journal.transport`, `journal.priority` and source clock metadata when present.
Bounded index selectors remain `cluster`, `node`, `source="journal"`, `unit`
and `job`. K3s/kernel use `node/k3s` and `node/kernel`; remaining services use
`node/system`. A fixed unit allowlist covers common network, time, storage and
authentication services; other units use `unit="other"`, while their exact names
remain queryable through `systemd_unit` or the JSON body. This avoids indexing
every transient session/scope/template instance.

API audit uses `otelcol.receiver.filelog.audit` over
`/var/log/kubernetes-audit/audit*.log`. Ansible creates this alias to the K3s
server log directory on servers and an empty directory on workers; the K3s
credential/configuration tree is never mounted. The file receiver fingerprints
files across active/timestamped rotations and persists offsets separately under
`otel/offsets`, starting unread files from the beginning. It parses a copy of each
JSON record, keeps the original body, and uses `requestReceivedTimestamp` as its
source event time. Audit ID, stage and verb are metadata, with bounded selectors
`source="audit"`, `unit="kube-apiserver"`, `job="node/audit"`, cluster and node.
Malformed records are sent with their original bodies and generate parser errors.
Compressed rotations are outside the current glob; the owning K3s rotation policy
does not enable compression. Validate rotation and restart with the actual audit
writer before claiming complete production coverage. This file receiver is also
Public Preview and has its upstream Stanza volatile emitter/checkpoint window;
receiver retry does not make offsets and payload commits atomic.

OS file evidence uses `otelcol.receiver.filelog.os_files`, with persistent
fingerprint/offset state separate from the audit reader, and reads only:

- `/var/log/apt/history.log` and `term.log`, `/var/log/dpkg.log`, and
  `/var/log/unattended-upgrades/*.log`;
- `/var/log/cloud-init.log` and `cloud-init-output.log`;
- `/var/log/alternatives.log`, `/var/log/rpi-clone.log`, and
  `/var/log/bootstrap.log`;
- controlled native journal exports under
  `/var/log/home-lab-incident-backfill/*.jsonl`.

These paths are exposed through a broader read-only `/var/log` host mount at
`/host/var/log`; the explicit receiver allowlist controls collection. It does not
read `syslog`, `kern.log` or `auth.log` mirrors, binary login/accounting records,
arbitrary application files, or compressed history. Active-file rotation is
fingerprint tracked; historical renamed files outside the allowlist are not
rediscovered after downtime. Missing files on a node are valid. Bodies remain
unchanged and retain any original producer timestamp text. These heterogeneous
formats use observed query time with `timestamp.quality="observed"`, rather than
claiming an accurately parsed producer timestamp. Select them with
`source="os-file"`, `unit="os-file"`, `job="node/os-file"` and filter the
`log_file_path` metadata. Initial retained file history is read from the beginning.

The controlled incident backfill imports native K3s/kernel records from the
private baseline collected on all eight nodes. It recovers retained evidence
that the old five-minute journal policy could skip, without resetting current
reader cursors. JSON bodies preserve native `__CURSOR`, `__REALTIME_TIMESTAMP`,
`__MONOTONIC_TIMESTAMP` and `_BOOT_ID` for reconstruction. Imported records use
observed query time and the same explicit `timestamp.quality="observed"` marker;
filter their `log_file_path` and use `| json` to inspect native time and identity.
This intentional historical backfill can overlap previous central deliveries.
Import counts are not a count of uniquely lost logs. Normal ongoing OS journal
collection and its existing query selectors remain authoritative.

## Timestamps and boot evidence

Journal, audit and CRI records retain `source.timestamp_unix_nano`; every
converted record receives a separate OTel observed timestamp. OS file records
explicitly omit a producer timestamp attribute because their time is unparsed.
Normal journal/audit records keep the original event time. Journal/audit records older than Loki's 14-day acceptance window, or more than
ten minutes in the future, explicitly use observed time for querying. They carry
`clock.timestamp_adjusted=true` and `clock.timestamp_adjustment_reason` equal to
`source_older_than_14d` or `source_more_than_10m_in_future`. Original timestamps,
boot identity and bodies remain intact. These flags report a timestamp policy
adjustment; they do not establish why the source clock differed. CRI age handling
remains unchanged, including its explicit 336-hour expiry filter.

Loki's companion OTLP mapping, ingestion time sharding and recent-query window
must roll out with this pipeline so older valid records remain queryable beside
fresh records. A source clock problem can still affect ordering and delivery
measurements; reconstruct a boot using its original times and native journal.

Alloy's journal reader enumerates journal data fields but does not generally
expose the journal address metadata `__MONOTONIC_TIMESTAMP`. If a monotonic field
is supplied it is preserved as metadata; do not assume every central record has
one. Native `journalctl -o json` evidence remains necessary for precise boot
monotonic timelines. Early records are available centrally after K3s and this
DaemonSet recover, provided the host journal retained them. The DaemonSet cannot
run before K3s or forward from a powered-off/failed node.

## Durable export and remaining loss windows

`/var/lib/alloy-node-logs` preserves existing file offsets and journal cursors.
Payloads have a distinct path,
`/var/lib/alloy-node-logs/otel/payloads`, backed by the owning host role's bounded
4GiB spool filesystem. File storage uses `fsync=true`; the exporters share a
64MiB serialized request budget: 56MiB for bulk logs and 8MiB reserved for OS/kernel
journals. Independent bridges and queues keep K3s/audit catch-up from blocking
current OS evidence. Actual database size includes metadata,
allocation, in-flight data and compaction, so queue size is not a disk quota.
Online compaction reclaims a database allocated above 128MiB after used pages
fall below 32MiB; disk capacity reserves room for its temporary copy. Preserve component IDs, state directories and spool backing
files across rollouts.

The queue has an explicit `hostPath` with `type: Directory` from host
`/var/lib/alloy-node-logs/otel/data`, mounted at the container's
`/var/lib/alloy-node-logs/otel`. Ansible creates the `data` child only after
verifying the parent is the separate bounded filesystem. If that filesystem
fails to mount after a boot, the underlying empty host directory has no `data`
child and kubelet refuses collector startup. It cannot silently create a queue
on the unbounded root filesystem. This also avoids depending on propagation of
the nested mount through the existing parent state mount. File/journal cursor
paths outside this subtree remain unchanged. Do not create the underlying
`data` directory manually or change this volume to `DirectoryOrCreate`.

The OTLP exporter sends to the existing Loki gateway's `/otlp/v1/logs` route.
Each queue has one consumer; both share the same CPU ceiling. The original
`loki` exporter retains its identity and old backlog, including any OS records
queued before the split. New OS/kernel records use the independent `os` exporter.
Full queues block instead of intentionally discarding; retryable failures use
1s–1m backoff with no retry elapsed-time expiry. The smaller queue applies source
backpressure earlier during a backend outage. Existing persisted payloads remain
eligible for replay even if their total exceeds the new capacity; capacity limits
new intake rather than deleting the incident backlog. Batching occurs inside the persistent exporter queue,
using 64–256KiB batches and a two-second flush timeout. There is no standalone
volatile OTel batch processor before that queue.

This improves recovery once a payload is durably enqueued. It does not provide
exactly-once or zero-loss delivery. The Loki-to-OTel bridge is a channel handoff;
source cursor advancement and queue writes are not one transaction. A crash can
lose a record between them. The bridge logs downstream enqueue/storage errors
without replaying the failed entry, so a full or failed spool remains a loss
scenario. Source-side CRI partial buffers are also volatile. Queue records can
be replayed after an uncertain acknowledgement, and permanent backend rejection
still discards data. Node disk loss destroys its local queue. Journald vacuum,
container rotation/garbage collection, discovery gaps, and clock acceptance
limits remain separate recovery boundaries.

The only writable host mount is Alloy's own state directory. Pod/journal files, the OS `/var/log` mount, the narrow audit alias
and `/etc/machine-id` are read-only. Alloy runs as UID/GID 0 to read root-owned
logs, with all capabilities dropped, privilege escalation disabled, a read-only
root filesystem and RuntimeDefault seccomp. There is no host network, host PID,
privileged mode, runtime socket or host-root mount. RBAC remains pods-only.
Full OS/authentication coverage uses the protected Grafana/query boundary
configured in the monitoring bundle; verify that boundary before rollout.

## Rollout, queries and validation

Both Fleet dependency layers accept a deployed Loki bundle in `Ready` or
`NotReady` state. A backend or gateway outage must not block collector recovery
updates; the durable queue and retry policy handle delivery while Loki recovers.
Missing or undeployed prerequisites remain blocked.

Keep `nodeLogs.podLogsEnabled: true` for normal forwarding. The existing priming
option remains available for a separately reviewed pod-reader handover. Repair
through Fleet without deleting positions/cursors or the queue. A rolling
replacement flushes quiet-file checkpoints; a reload alone does not ensure it.
See the [incident coverage runbook](../../../../../docs/runbooks/incident-coverage.md).

```logql
{cluster="local",source="journal",job="node/system"} | json
{cluster="local",source="journal",job="node/k3s"} | json
{cluster="local",source="journal",job="node/kernel"} | json
{cluster="local",source="journal"} | clock_timestamp_adjusted="true"
{cluster="local",source="journal"} | systemd_unit="ssh.service"
{cluster="local",source="audit",job="node/audit"} | json
{cluster="local",source="os-file",job="node/os-file"} | log_file_path=~".*(dpkg|apt).*"
```

```sh
kubectl kustomize kubernetes/projects/system/apps/alloy-node-logs
python3 kubernetes/projects/system/apps/alloy-node-logs/test_pipeline.py
python3 scripts/validate-workload-catalog.py
```

The local Docker pipeline fixture renders both handover stages with the pinned
chart and validates them using Alloy 1.20.1. It checks source offsets, CRI partial
records/rotation, audit parsing/offsets, OTel normalization, preserved bodies/timestamps and durable
export recovery against a local HTTP fixture. It does not write to Loki or the
cluster. Local fixtures do not prove real host coverage, spool mounting,
production retention, query access or end-to-end delivery.

For rollout, server-side dry-run the rendered resources, then check Fleet
convergence, DaemonSet availability, every node's journal reader health, queue
size/capacity and enqueue/export failures. Retain an independent alert path.
Check file/journal read counters and fresh source-specific queries; a Ready pod
alone does not prove ingestion. Quiet kernel sources require reader health and
controlled test evidence rather than a freshness alert demanding a new error.
OTel enqueue failures and terminal delivery failures must remain visible beside
backend availability alerts; their counts are different pipeline stages.

References: [pinned journal source](https://github.com/grafana/alloy/blob/v1.20.1/docs/sources/reference/components/loki/loki.source.journal.md),
[pinned OTel bridge](https://github.com/grafana/alloy/blob/v1.20.1/docs/sources/reference/components/otelcol/otelcol.receiver.loki.md),
[persistent storage](https://github.com/grafana/alloy/blob/v1.20.1/docs/sources/reference/components/otelcol/otelcol.storage.file.md),
[exporter queue](https://github.com/grafana/alloy/blob/v1.20.1/docs/sources/shared/reference/components/otelcol-queue-block.md),
and [exporter batching](https://github.com/grafana/alloy/blob/v1.20.1/docs/sources/shared/reference/components/otelcol-queue-batch-block.md).

## Continuous OS delivery monitoring

Ansible's `home-lab-log-canary.timer` emits an INFO journal record every minute
with `SYSLOG_IDENTIFIER="home-lab-log-canary"`. The JSON message identifies the
node and boot, records emission time, and reports available/capacity bytes of
the bounded OTel spool filesystem. These are informational delivery probes.
They do not inject faults or create artificial error events.

The `alloy-os-log-monitor` Deployment runs two read-only Python query workers on
different control-plane nodes. Every 60 seconds each worker queries Loki for
canary counts over five minutes and the minimum available/maximum capacity spool
bytes reported during that window. Prometheus scrapes both replicas on port
9091. Metrics are:

- `os_log_canary_recent_records{node}`: canaries available through the journal
  collector, transport, Loki ingestion and query path;
- `os_log_queue_available_bytes{node}` and `os_log_queue_capacity_bytes{node}`:
  recent filesystem space, which includes database allocation/compaction rather
  than only the exporter's logical queue;
- `os_log_monitor_query_success` and
  `os_log_monitor_last_success_time_seconds`: query success and its last time.

A failed/malformed query, non-finite sample, stale vector or stalled polling
worker clears exposed node samples and reports query success as zero. A valid
empty result does not retain older node values. Monitor process health is
separate from Loki availability so backend failure remains observable. The
Prometheus rules compare results against `kube_node_info`; adding/removing nodes
does not require a fixed node list in the monitor. Metrics combine replica
results by node, rather than summing duplicate observations.

The monitor uses no Kubernetes API credentials, service-account token, host
mounts, write requests, external packages or notification integrations. Its
non-root containers have a read-only root filesystem and no capabilities.
NetworkPolicy permits DNS, Loki gateway reads and Prometheus scrapes only. The
Python 3.15.0/Alpine 3.23 image is pinned to the registry-verified ARM64 manifest.
Each replica requests 5m CPU/32Mi memory and has a 64Mi memory limit.

This verifies ongoing journal-to-query delivery for each expected node. It does
not certify every source, every record, or survival of a cluster/NAS outage;
independent monitoring remains an explicit requirement. Spool-space telemetry
uses the logging path itself, so it cannot provide an independent warning after
that path fails. Audit/OS-file reader counters and the controlled local fixtures
remain separate coverage checks. A recently replayed canary with an explicitly
adjusted bad source clock can appear within the query window; inspect original
emission/clock metadata when assessing incident timing.

Run the monitor's HTTP, failure, freshness and parsing checks locally:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s kubernetes/projects/system/apps/alloy-node-logs/tests
python3 scripts/check-os-logging-observability.py
```

The `OS logging validation` workflow runs the pinned collector/backend fixture,
monitor, historical-backfill guards and alert scenarios on a native ARM64 runner.
This is isolated recovery validation; it does not inject faults into production.
The first native-journal test builds a cached, digest-pinned Ubuntu 26.04
fixture image and installs `systemd-journal-remote` inside that image. Docker
build and Ubuntu archive access are required; no host package or journal is
changed. The synthetic binary journal exercises the actual journal readers,
including epoch timestamps, ownership filters and persisted cursor recovery.

The known canary syslog identifier receives the bounded index value
`unit="home-lab-log-canary"`. Short-lived logger processes may exit before
journald resolves `_SYSTEMD_UNIT`; the actual original fields remain unchanged.
Health queries select this stream before parsing JSON, avoiding scans of the
full retained-OS backfill.

## Resource review — 28 October 2026

Values use the 28 October historical review in
[the resource policy](../../../../../docs/runbooks/kubernetes-resource-policy.md#2026-10-28-historical-resource-review).
CPU reservations cover measured sustained demand with headroom. The CPU ceilings
below supersede the former unlimited burst policy. Memory caps preserve the observed fourteen-day peaks
and extra headroom where OOM records show clipping.

| Container | CPU request | CPU limit | Memory request | Memory limit |
| --- | --- | --- | --- | --- |
| `alloy-node-logs/alloy` | 100m | 250m | 384Mi | 640Mi |
| `alloy-node-logs/config-reloader` | 5m | 25m | 32Mi | 64Mi |

## CPU protection

Each node collector requests 100m CPU and is capped at 250m, with
`GOMAXPROCS=1` and `GOMEMLIMIT=256MiB`. Its reloader is capped at 25m. Together they can use at most
275m CPU, about 6.9% of a four-core Pi over the CPU quota period. A collector
can take longer to drain retained logs during an incident; existing queue,
delivery-failure and OS-canary alerts expose the resulting backlog or delay.

Pod-file discovery runs every 15 seconds. Audit and OS files poll once per
second, with four concurrent files per receiver and sequential-read cache advice
to reduce source cache pressure. The persistent exporters have one consumer each,
fsync enabled and a combined 64MiB payload bound (56MiB bulk, 8MiB OS/kernel).
The 64–256KiB export batches flush at most every two seconds
when their minimum size has not been reached. Batching remains after durable
enqueue. Source identities, cursor paths, retention and collection coverage
are preserved. New pod-file discovery can take up to 15 seconds; low-volume
export can wait up to two seconds for batching.

The local OTLP recovery fixture reads the configured CPU ceiling and
`GOMAXPROCS`, `GOMEMLIMIT` and memory ceiling into Docker. It exercises HTTP503
recovery, abrupt restart with a backlog exceeding the reduced queue capacity,
OS delivery while bulk export remains blocked,
and unique-record reconciliation under the configured resource ceilings. Local amd64 validation proves
configuration and delivery behavior; ARM64 runtime CPU and queue checks remain
part of live rollout validation.

The follow-up memory review sets each collector request to `384Mi` (from
`512Mi`), releasing `1Gi` across eight nodes. The `640Mi` limit is retained for
replay: the fourteen-day per-container peak was `535Mi`, with no recorded OOM
events. Reloaders, queue durability, memory-limiter settings, and CPU bounds
remain unchanged. Verify all eight nodes and log delivery after reconciliation.

## Remote critical kernel evidence

The bounded system-journal unit index includes the four static host-recovery
units. `home-lab-kernel-receiver.service` records critical kernel messages sent
by the eight nodes to independent LAN receivers. These are `node/system`
records, not duplicate local `node/kernel` collection. The indexed `node` is
the receiver; extract journal `MESSAGE` and parse `source_node` for the sender.
No dynamic peer, boot or message identifiers are added as index labels.
See [host recovery](../../../../../infrastructure/ansible/roles/os_prep/README.md#remote-node-recovery-and-kernel-evidence).
