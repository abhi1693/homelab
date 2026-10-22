# Incident coverage

The system project collects node-local container files, K3s server/agent and
kernel journals, native embedded-etcd metrics, and Cilium/Hubble metrics.
Deployment and configuration changes go through Git and Fleet. Do not restart
K3s, mutate the CNI through its CLI, or change namespace ownership for this work.

## Collection boundaries

[`alloy-node-logs`](../../kubernetes/projects/system/apps/alloy-node-logs/README.md)
runs on every Linux ARM64 node, including tainted control planes. Host log and
journal mounts are read-only. Only its position directory is writable on the
host. Root is needed to read root-owned CRI files; the container drops all
capabilities, has a read-only root filesystem and does not use privileged mode,
host networking or host PID access. Kubernetes discovery is limited to pods.

K3s server and agent units and the kernel transport have separate journal
readers. JSON bodies retain journal details for investigation; boot IDs, pod
UIDs, request IDs and trace IDs are not index labels. Both volatile and persistent
journal directories are mounted. Remote collection preserves entries already
delivered before a node fails. It cannot recover entries lost before collection
from a volatile journal, host loss, file deletion or rotation. Initial journal
backfill is bounded; a quiet kernel need not have a recent log entry.

Positions and journal cursors live at `/var/lib/alloy-node-logs` on each node.
This is not a durable delivery queue: Loki write batches remain in memory with
bounded retries. Check permanent drops, rejections and host disk usage. Do not
claim complete delivery solely from healthy pods or successful metrics scrapes.
Loki remains a single backend with the existing storage failure boundary.

[`alloy-logs`](../../kubernetes/projects/system/apps/alloy-logs/README.md) retains
two clustered replicas for Kubernetes events. Container files have one collection
path after handover. Kubernetes audit logging remains a separate host decision.

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
