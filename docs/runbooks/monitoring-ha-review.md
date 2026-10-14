# Monitoring coverage and HA review

Reviewed 2026-10-01 against modernization commit `2d6fb957`, its follow-up
acceptance commits through `638e58b4`, current Git values, and the local cluster.
This document distinguishes observed state from prepared changes. No destructive
failure test or storage migration was performed. The changes in this review are
not deployed until published and reconciled by Fleet.

## Evidence

- Eight nodes Ready. All 176 discovered scrape targets were healthy at the
  snapshot; target counts fluctuate with workloads. No rule-evaluation failures
  over one hour, no firing alerts above severity none, and zero reported Alloy
  permanent drops or Loki rejections over 24 hours.
- Prometheus and Alertmanager each had two Ready replicas on separate control
  planes. Two Thanos Query replicas occupied separate workers. All eight node
  exporters and Longhorn manager targets were present.
- Each Prometheus held approximately 543,000 active series. Seven-day per-series
  p95 working set reached 3.32 GiB and CPU reached 0.33 core. Pod replacements
  produce separate series, so these are observations, not a complete load test.
  Keep 4 GiB requests, 5 GiB limits, 60s scrapes and existing retention bounds.
  Recent Thanos Query p95 memory reached 1.30 GiB; do not size it from the much
  smaller idle snapshot. Grafana was upgraded only six hours before review.
- The API and K3s jobs contributed about 99,000 and 116,000 scraped samples.
  Some scheduler/workqueue families are collected by both jobs. Preserve all
  consumers before narrowing either job; never blindly drop all histograms.
- Loki namespace labels confirmed missing `kube-system`, `cattle-system` and
  `longhorn-system`, matching explicit collector exclusions. Zero delivery drops
  therefore did not mean complete coverage. Log throughput before expansion was
  approximately 8.9 kB/s from pod collection plus 0.2 kB/s from Faro.
- `etcd_server_has_leader` was absent. Existing `etcd_requests_total` and similar
  API-client metrics do not prove embedded etcd health coverage. kube-proxy is
  deliberately disabled because Cilium replaces it.
- Alloy's boundary policy was live in `fleet-local`, selecting no collector pods.
  The wrapper's global namespace transform overrode the runtime namespace.

## Prepared changes

1. Run two Alloy Deployment replicas with hard hostname anti-affinity, clustered
   pod/event ownership, zero-unavailable rolling updates and `minAvailable: 1`.
   Include system namespaces and remove the Running-only discovery filter so
   retained completed pods can be discovered. Preserve bounded labels and retries.
2. Collect Kubernetes events as JSON with `job="kubernetes-events"`. Do not turn
   event messages, request IDs, trace IDs or pod UIDs into additional index labels.
3. Place runtime policies and alerts in `cattle-monitoring-system`; keep HelmOp
   and generated values in `fleet-local`. Permit Alloy peers on TCP/12345 and API
   access through Cilium's API-server entity. Alert on lost collector redundancy
   and missing scrape health.
4. Run two Loki gateways with the chart's hard anti-affinity. This removes the
   gateway singleton only; it does not make the Loki backend HA.

Added steady-state requests total 60m CPU and 256 MiB memory: one Alloy/reloader
pair plus one gateway. New system logs add workload-dependent storage and CPU
cost; measure after rollout before reducing retention or raising limits.

## Required work before claiming full HA and coverage

### Loki storage and write availability

There is no existing local HA object store in the inspected system bundles.
Provision a dedicated local S3-compatible store across at least three independent
node/disk failure domains, sized from the expanded log volume. A single object
store process on the NAS would merely move the failure point. Keep cloud storage
out of the default design to preserve the repository's local-only telemetry model.
Select and validate the backend's ARM64 support, quorum and failure behavior before
adding it to Fleet; its resource cost is additional to the prepared changes.

Use three monolithic Loki replicas with replication factor three, distinct nodes,
per-replica durable WAL storage and a disruption budget permitting one unavailable
replica. Keep two gateways. Do not enable the retired simple-scalable topology or
share one filesystem directory among multiple writers. Permit memberlist and gRPC
traffic explicitly in network policies.

Preserve the original filesystem schema period and stored data. Rehearse copying
index/chunks to the selected backend or maintain a separately queryable legacy
read path during the 14-day retention transition. A new S3 schema period alone
does not make existing filesystem history readable from every new replica.
Validate historical queries, new writes and retention before switching producers.
Do not delete the old claim or blindly roll back schema changes.

### Grafana and Alertmanager storage

Reuse the healthy three-instance CNPG cluster for a dedicated Grafana database
and least-privilege role. Manage credentials through encrypted Git secrets or the
existing secret operator. Rehearse a Grafana 13 unified-storage SQLite-to-Postgres
migration against a consistent copy; preserve users, organizations, dashboards,
datasources, encrypted datasource credentials and the Grafana encryption key.
An empty Postgres database with recreated dashboards is not data preservation.

Only after migration verification, use two Grafana replicas with hard anti-affinity,
a shared database, rolling updates, and a disruption budget. Keep plugins and
provisioning identical on both. Inspect Grafana-managed alerting before configuring
its HA peer settings. Stop relying on a single NFS data directory for availability.

Alertmanager replicas still share the NAS failure domain through separate NFS
claims. Migrate each ordinal to independent Longhorn-backed storage sequentially,
preserving silences and notification state and verifying the peer mesh between
steps. Do not recreate both claims or restart both replicas together.

### Host logs and remaining metrics

API-based pod log collection cannot guarantee all rotated, previous-container,
short-lived, or deleted-pod logs. Add a node-local collector on every node with
read-only pod-log and journal mounts, persistent positions and bounded durable
write buffers. Include K3s server/agent and kernel journals. Switch pod collection
from the API sources only after the node collectors are verified, avoiding two
permanent ingestion paths for the same files. Define disk budgets, rotation and
outage buffering explicitly. Kubernetes audit logging is a separate host-level
choice and must not log request bodies or Secrets indiscriminately.

Verify embedded etcd's listener and authentication on all three servers. If host
configuration must change, represent it in the Ansible role, validate syntax and
roll servers one at a time through an operator-approved maintenance workflow.
Expose only the metrics listener to Prometheus; never expose the etcd client API
without authentication. Add Fleet-managed discovery and alerts for leader/quorum,
WAL fsync, backend commit latency, database size and peer health. Confirm Cilium
agent/operator metric coverage separately; Hubble flow retention is not implied
by collecting container logs.

kube-state-metrics and the Prometheus operator are currently singletons. The former
interrupts object-state collection on failure; the latter delays reconciliation
while existing scrapers continue. Evaluate a supported HA/leader-election mode
for the deployed operator. Do not simply double kube-state-metrics scrapes:
recording rules that sum duplicate object series can report incorrect capacity.

## Validation and rollout gates

- Render Alloy chart 1.13.0 and Loki chart 7.3.0 with their actual values, validate
  River using Alloy v1.20.0, and server-dry-run rendered and wrapper manifests.
- Publish through Git/Fleet only. Require each affected BundleDeployment desired
  revision to equal its applied revision and HelmOps to report Ready.
- Verify two Alloy peers and two gateway pods on different nodes. Query logs from
  system namespaces and `{job="kubernetes-events",cluster="local"}`. Include
  completed jobs in checks. Healthy scrape targets alone do not prove log delivery.
- Observe delivery failures, discarded entries, active stream count, process memory,
  ingestion rate and NAS space after broadening collection. Retention stays 14 days;
  NFS PVC size is not an enforced quota.
- Perform separately scheduled one-node-failure acceptance after the storage work:
  continuous metric queries, log writes/reads and alert delivery must survive, and
  historical data, Grafana state and silences must remain available. A PDB only
  governs voluntary eviction and does not prove this behavior.

## References

- [Alloy Kubernetes source clustering](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes/)
- [Alloy Kubernetes event source](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes_events/)
- [Loki monolithic HA](https://grafana.com/docs/loki/latest/setup/install/helm/install-monolithic/)
- [Grafana shared-database HA](https://grafana.com/docs/grafana/latest/setup-grafana/set-up-for-high-availability/)
- [K3s shared metric endpoints](https://docs.k3s.io/reference/metrics)
