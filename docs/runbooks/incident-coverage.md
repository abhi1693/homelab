# Incident coverage

The system project collects node-local container files, the complete retained
system journal, Kubernetes API audit files, selected OS package/bootstrap files,
native embedded-etcd metrics, and Cilium/Hubble metrics.
Deployment and configuration changes go through Git and Fleet. Do not restart
K3s, mutate the CNI through its CLI, or change namespace ownership for this work.

## Collection boundaries

[`alloy-node-logs`](../../kubernetes/projects/system/apps/alloy-node-logs/README.md)
runs on every Linux ARM64 node, including tainted control planes. Host log and
journal mounts are read-only. Only its position directory is writable on the
host. Root is needed to read root-owned CRI files; the container drops all
capabilities, has a read-only root filesystem and does not use privileged mode,
host networking or host PID access. Kubernetes discovery is limited to pods.

K3s server and agent units and the kernel transport retain their separate journal
readers and cursors. An additional reader forwards every other journal record,
excluding those three sources to preserve one authoritative path. JSON bodies
retain journal details for investigation; boot IDs, pod
UIDs, request IDs and trace IDs are not index labels. Both volatile and persistent
journal directories are mounted. Remote collection preserves entries already
delivered before a node fails. It cannot recover entries lost before collection
from a volatile journal, host loss, file deletion or rotation. Readers include
all locally retained history, even when a bad boot clock puts it outside the
normal timestamp window. Retention and disk quotas bound the source history;
a quiet kernel need not have a recent log entry.

Positions and journal cursors live at `/var/lib/alloy-node-logs` on each node.
These positions are separate from the OTel payload queue, which fsyncs outgoing
records into the Ansible-managed 4GiB local filesystem at
`/var/lib/alloy-node-logs/otel`. Its combined 64MiB serialized queue budget
(56MiB bulk, 8MiB OS/kernel) leaves
filesystem/compaction headroom and applies source backpressure earlier during
backend outages. Independent OS/kernel and bulk queues have one replay consumer
each and share the existing 250m CPU ceiling, keeping current OS evidence separate
from bulk catch-up. Check final export failures, enqueue failures, rejections and
host disk usage. Do not
claim complete delivery solely from healthy pods or successful metrics scrapes.
Loki remains a single backend with the existing storage failure boundary.

[`alloy-logs`](../../kubernetes/projects/system/apps/alloy-logs/README.md) retains
two clustered replicas for Kubernetes events. Container files have one collection
path after handover. API audit uses a separate filelog reader and the narrow
`/var/log/kubernetes-audit` host alias; worker aliases are empty directories.

## OS source inventory and investigation

| Source | Owner and collection path | Correlation and limits |
| --- | --- | --- |
| Kernel, K3s, systemd services, networking, DNS/time clients, authentication and shutdown | Ansible owns journald persistence; Fleet Alloy reads the retained system journal | Original body, boot ID, actual systemd unit, priority, source/observed time. Dynamic units remain metadata rather than index labels. |
| API audit | K3s writes existing Metadata-level audit; Alloy filelog reads active and rotated files | Audit ID, request timestamp, verb, stage and unchanged JSON body. |
| APT, dpkg, unattended upgrades, cloud-init and selected bootstrap/clone logs | Explicit Alloy file allowlist under the read-only OS log mount | Original body and file path. Records without parsed producer time explicitly use observed time. Compressed history is excluded. |
| Container stdout/stderr | Existing node-local file reader and CRI parser | Existing selectors, component IDs and positions are preserved. Pod discovery still depends on the API; orphan/rotated-file discovery after downtime remains a separate gap. |
| Kubernetes events and Faro | Existing collectors | Their ownership and body formats remain unchanged. Their current delivery semantics are separate from the node OTel queue. |

`/var/log/syslog`, `kern.log` and `auth.log` mirror journal sources and are not
read a second time. Binary login/accounting files, compressed file history,
device-local switch/PoE/NAS/UPS events, and logs never emitted to these sources
are not covered by this OS pipeline. Inventory another explicit source when
an incident needs one; do not infer its contents from a healthy collector.

Use **OS / Host Metrics** (stable UID `os-incident-evidence`) for host CPU,
memory, disk, I/O, network, uptime and readiness. It reads only Prometheus and
links to the separate **OS / Logs** dashboard (`os-logs`) with node/time selection.

In **OS / Logs**, select a node and one source:

- **System journal** includes kernel, K3s, OS services, authentication and sudo.
  Use Service to focus a program or unit, such as `kernel`, `k3s`,
  `ssh` or `sudo`.
- **Kubernetes API audit** shows requests as readable action/resource/actor/
  stage/HTTP-result messages. RequestReceived is an attempt, not confirmation
  of success.
- **OS files and saved journals** includes package/setup files and imported
  native journal snapshots. Original saved-journal messages are decoded for
  display; plain files remain readable even though they are not JSON.

Search is case-sensitive plain text, with an empty value showing all
messages. Level recognizes native journal priority, explicit application levels
inside MESSAGE and audit HTTP errors. Records without a known level remain
Unspecified. Select multiple levels to combine them, or choose All levels. Filters run
on the complete message; the table displays a
320-character excerpt. Click Message for the unchanged original and surrounding
records for that node/source. There are no static explanation panels.

All times in the log dashboard are UTC. **Event time** is the producer's original
timestamp when available. **Stored time** is the Loki timestamp used by the time
picker. These normally agree, but saved journals are stored at import time and
out-of-range journal/audit source times are stored at collection time. Their
original event time and a readable Time context remain in the same row.
Plain OS files without a separately parsed producer time show Unknown event
time; dates can still be present in the message. An old timestamp alone does
not establish a faulty clock or a new incident. Full boot/monotonic identity
remains in original records for investigations that need it.

The default log window is 30 minutes and automatic refresh is off. The browser
requests at most 100 records from the selected source. Select Errors in Level
to inspect the actual error messages, then use Service and Search to focus the
records. The primary host view stays responsive while an explicit long log
search runs.

Grafana requires authentication. Original bodies are preserved without
redaction, including records that cannot be parsed for presentation. Source
coverage is monitored independently by informational host canaries and the
existing logging rules; healthy metrics do not certify every quiet reader.

Useful LogQL queries:

```logql
{cluster="local",source="journal",node="k8s-rpi3"} | json
{cluster="local",source="journal",node="k8s-rpi3"} | json | _BOOT_ID="BOOT_ID"
{cluster="local",source="journal",node="k8s-rpi3"} | json | PRIORITY=~"[0-4]"
{cluster="local",source="journal",node="k8s-rpi3"} | json | _SYSTEMD_UNIT="systemd-timesyncd.service"
{cluster="local",source="journal",node="k8s-rpi3"} | clock_timestamp_adjusted="true"
{cluster="local",source="audit",node="k8s-rpi3"} | json
{cluster="local",source="os-file",node="k8s-rpi3"}
```

For journal/audit records whose source time is older than 14 days or more than
10 minutes in the future, the OTel pipeline explicitly uses observed time for
the Loki timestamp. It preserves `source_timestamp_unix_nano`,
`clock_timestamp_adjusted` and `clock_timestamp_adjustment_reason` as structured
metadata. This makes clock-damaged evidence queryable without claiming the
replacement time is the original event time. A historical record can trigger
the age rule without proving a faulty clock. Compare boot identity and native
monotonic timestamps when reconstructing ordering. Alloy's journal API does not
expose every native journal address field; the original retained journal is the
authority for missing monotonic metadata.

Every node emits an informational `home-lab-log-canary` journal record once a
minute through an Ansible-managed timer. Two read-only checkers query its last
five minutes through the actual Loki gateway. Prometheus compares returned node
coverage against `kube_node_info`, checks query failures and monitors the
payload filesystem capacity reported by canaries. A missing canary detects an
OS-source-to-query gap; it does not certify every quiet reader or archive.
The checker/Prometheus/Alertmanager path still shares cluster dependencies.

## Evidence when Loki or Kubernetes is unavailable

```sh
python3 scripts/collect-os-incident.py --node k8s-rpi3 --boot 0
python3 scripts/collect-os-incident.py --node k8s-rpi3 --boot=-1
python3 scripts/collect-os-incident.py --since '2026-10-26 10:00:00 UTC' --until '2026-10-26 11:00:00 UTC'
```

The helper uses SSH directly, does not call Kubernetes, and saves original
journal JSON including boot/monotonic timestamps plus bounded host/time/network/
disk/pressure evidence. It writes a private directory outside the repository,
compresses records, records capture failures/truncation, and prints only status
and paths. Default limits are 256MiB per command and 120 seconds per remote
capture. An unreachable host is an explicit evidence gap. Keep the manifest
with the captures; these records are not redacted and must not be committed.

Before reducing journal retention, preserve incident evidence. The initial
rollout captured all eight current boot journals outside Git before changing
the journald policy. This is an incident snapshot, not a backup/restore plan.

## Diagnosis and validation contract

Build a timeline of impact, last normal operation, first abnormal host/device
event, system response and recovery. Correlate the same node/boot/time range
with metrics, traces, image/kernel/package versions and Git/Fleet/Ansible
changes. Separate initiating faults from consequences such as Longhorn rebuild
load. Record confirmed facts, competing explanations and the next capture/test
that distinguishes them; do not infer the original rpi3 connectivity cause from
its later clock/certificate delay or successful recovery.

`python3 kubernetes/projects/system/apps/alloy-node-logs/test_pipeline.py`
uses the pinned Alloy/Loki versions locally. It reconciles identifiable records
through real OTLP queries, mixed source identities, clock jumps, retained old
replay, backend HTTP 503 and collector SIGKILL. Original source files are removed
before restart to establish payload recovery separately from source rereading.
Local x86 validation is not ARM64 performance proof or a production outage test.

The source-to-queue handoff still has journal-bridge/Stanza/parser memory
windows; persistent payload queues do not make cursor advancement atomic.
Permanent node/disk loss, full/broken queue storage, permanent HTTP errors,
source rotation/deletion, API discovery gaps and source-side journal rate
limiting can lose evidence. Local journald retention is capped at 512MiB and
seven days, with a 2GiB free-space reserve and 30-second sync interval; the
actual retained duration can be shorter. Existing journal cursors do not replay
records already skipped before this change. A separate controlled backfill is
needed for those records:

```sh
python3 scripts/prepare-os-log-backfill.py --bundle /tmp/PRIVATE-BUNDLE --output /tmp/PRIVATE-REPLAY
cd infrastructure/ansible
ansible-playbook playbooks/os_log_backfill.yml -e os_log_backfill_directory=/tmp/PRIVATE-REPLAY
```

Preparation rejects failed/truncated captures and validates native cursor,
realtime, monotonic, boot and host identity fields. It selects K3s/kernel records
only, preserving original JSON bytes, and writes a private checksum/count
manifest. Ansible stages immutable root-only files, capped at 256MiB per node,
without resetting any source cursor. Their `source="os-file"` query timestamps
are explicitly observed time; use `| json` to read native original timestamps
and boot identity. The historical copy can overlap records delivered earlier;
its count is not a count of uniquely recovered loss. Query and reconcile the
manifest before removing files or staging another snapshot. Keep local replay
files within the incident retention budget.

Loki remains single-backend/NAS-dependent, with
14-day central retention and no newly claimed independent disaster recovery.

## Container-log handover

1. Deploy node collectors with `nodeLogs.podLogsEnabled: false`. File readers
   prime persistent positions while discarding their pod-log output; journal
   forwarding is active. The existing API reader remains authoritative.
2. Verify every node collector, its mounts, discovery, persistent position files,
   journal readers and Loki writes. Treat `migration_priming` drops as intentional
   only during this stage. Verify no Loki write failures or rejections.
3. Enable node pod-log forwarding and add the handover pod annotation to force
   a graceful DaemonSet rollout. Keep the API reader active during this stage.
   Preserve file-source identity and positions: graceful termination checkpoints
   the latest consumed offsets before the enabled replacement starts. Alloy can
   otherwise retain an older on-disk offset for quiet files. Read new files from
   their beginning after handover.
4. Verify all eight enabled collectors deliver fresh pod logs, then remove the
   API pod source from `alloy-logs`, retaining its event sources. Wait for both
   event replicas and confirm the API source is absent. Record the UTC overlap
   window. Independent rolling updates are not atomic: this sequence prefers a
   bounded overlap over a collection gap. Delivery is not exactly once.

To roll back collection, first restore and verify the API reader before disabling
node pod forwarding in a later Git change. Keep journals active. Do not erase
positions or replay all retained files as an incident workaround.

## Native etcd metrics

[`etcd-metrics`](../../kubernetes/projects/system/apps/etcd-metrics/README.md)
proxies the existing `127.0.0.1:2381` listener on each of three control planes.
Its HTTPS listener binds the node IP on port 9238, verifies Prometheus's rotating
service-account token and authorizes only the named metrics service proxy.
Certificates come from the existing local CA. Port 2379 and etcd client
credentials are not exposed. Only native `etcd_*` samples are retained.

Missing scrapes and missing leaders are different failures. Inspect all three
members, leader agreement, WAL fsync/backend commit latency, database size and
host storage health together. The authentication proxy depends on the Kubernetes
API and can lose scrapes during an API outage even when etcd is running.

## Cilium and Hubble

[`cilium`](../../kubernetes/projects/system/apps/cilium/README.md) adopts the
existing same-version Helm release with its complete values before enabling
metrics. Adoption must render identically to the existing Helm manifest. After
Fleet is Ready, enable agent/operator metrics and bounded Hubble flow, drop,
TCP, ICMP and DNS metrics through the chart. Relay and UI stay disabled.
Do not add endpoint IP or DNS query labels.

[`cilium-monitoring`](../../kubernetes/projects/system/apps/cilium-monitoring/README.md)
owns separate PodMonitors and rules, avoiding a startup dependency from the CNI
on monitoring CRDs. Roll agent configuration changes with at most one unavailable
agent. Verify networking and public application readiness during the rollout.
After adoption, change the Fleet values for runtime configuration; Ansible retains
initial bootstrap and read-only validation duties.

### Rancher agent regeneration during a Cilium rollout

The 2026-10-19 rollout exposed a Rancher/Fleet interaction. Rancher 2.15.2
[adds control-plane taints to local Fleet agent tolerations](https://github.com/rancher/rancher/blob/v2.15.2/pkg/controllers/provisioningv2/fleetcluster/fleetcluster.go#L106).
Cilium temporarily adds `node.cilium.io/agent-not-ready:NoSchedule` while agents
restart. Changes to that toleration regenerated both Fleet agent pods at
07:59 UTC, interrupting an in-progress Helm upgrade. Fleet automatically rolled
back and retried the same desired Cilium configuration successfully. Both public
application probes remained HTTP 200 in the sampled rollout checks.

Keep Cilium's scheduling taint guard. Rancher's customization appends tolerations
and has no override for this list; adding a duplicate static toleration does not
stabilize the generated manifest. An upstream exclusion/deduplication fix needs
separate validation. Before future CNI rollouts, inspect Fleet agent stability,
watch Helm release state, and allow Fleet to recover an interrupted operation.
Do not manually run a competing Helm operation or disable the networking guard.

## Initial rollout evidence

On 2026-10-19, the unchanged Cilium adoption preserved all 18 agent/operator/Envoy
pod UIDs and restart counts. Metrics were enabled in a later commit. Both
Prometheus replicas then scraped eight agents, two operators and eight Hubble
exporters. Three native etcd targets, their leader/disk/database families and the
new eight-panel dashboard were verified; unauthenticated proxy requests failed.

Node collectors primed 580 nonempty files (about 775 MB) locally into the discard
stage. All eight nodes delivered K3s and kernel journal streams. The forwarding
rollout ran from 08:00:33 to 08:03:41 UTC, with all nodes Available by 08:04:00.
The API reader remained active until a separate retirement change. Every new
collector delivered additional container records, and all observed Loki pushes
returned 204 without retries or permanent drops. This bounded overlap can contain
duplicate records; it was not an exactly-once handover.

New etcd telemetry exposed intermittent WAL/backend latency on `k8s-rpi2`.
There was no pre-change native-metrics baseline to establish when that began.
Keep the ten-minute alert holds and correlate host disk/kernel evidence before
attributing or repairing it.

## Acceptance checks

- All eight nodes and node collectors Ready; both event collectors Ready on
  different nodes. Node log scrapes healthy on both Prometheus replicas.
- Fresh container and K3s log evidence from each node. Journal readers/cursors
  healthy even when no new kernel message exists. Never emit artificial failure
  events just to populate a graph.
- Three healthy etcd scrapes, three members reporting a leader and exactly one
  leader. Native `etcd_server_*` and `etcd_disk_*` series present.
- Eight Cilium agent, two operator and eight Hubble scrapes healthy on both
  Prometheus replicas; native metric families present. Traffic-driven families
  can be absent until matching traffic occurs.
- No new permanent log drops, Loki rejections or rule evaluation failures.
  Existing dashboards, datasource UIDs and monitoring PVC bindings preserved.
- Fleet desired and applied revisions agree. Inspect resource requests and
  measured memory/CPU before increasing scrape frequency or metric labels.

Run `python scripts/check-etcd-observability.py` and the component-specific
validation commands linked above before publishing. Use
`scripts/monitoring-migration-state.py` to capture private before/after inventories
outside Git and compare preservation; snapshots are inventories, not backups.
