# K3s embedded-etcd metrics

Fleet deploys one unprivileged `kube-rbac-proxy` per ARM64 control-plane/etcd
node. Each proxy forwards the existing host-loopback `http://127.0.0.1:2381/metrics`
endpoint, which exposes the native etcd server, disk, database, and peer metrics.
This does not require changing or restarting K3s. K3s's authenticated API and
kubelet endpoints do not expose these native metrics in this cluster.

Prometheus discovers all three proxies through the headless Service and scrapes
each node every 30 seconds as `job="etcd"`, with stable `node` and `instance`
labels. The loopback endpoint shares a registry with other K3s components, so the
ServiceMonitor retains only `etcd_.*`. API server and kubelet metrics keep their
existing scrape ownership. Each scrape has a 2,000-sample and 8MiB body limit.

The `K3s / Embedded Etcd` Grafana dashboard shows per-member leader state, p99
WAL fsync and backend commit latency, database size/quota, leader changes, and
pending proposals. It uses the existing Prometheus datasource.

## Security and failure boundaries

- The only new host listener is HTTPS on the node's internal IP, port `9238`.
  `--allow-paths=/metrics` rejects every other upstream path. The existing
  unauthenticated etcd metrics port `2381` stays on host loopback.
- TLS uses a 90-day certificate issued by the existing `home-local-ca`
  ClusterIssuer, renewed 30 days before expiry. Prometheus checks the CA and the
  `etcd-metrics.cattle-monitoring-system.svc` SAN for every node target. Secret
  volumes are mounted without `subPath` so kube-rbac-proxy can reload renewal.
- Requests need a valid Kubernetes token and delegated authorization for
  `get` on the named `etcd-metrics` Service's `proxy` subresource. Only the
  Prometheus ServiceAccount receives this namespaced grant. Other methods are
  checked using their corresponding verbs; the scrape grant does not allow
  `create`, `update`, `patch`, or `delete`.
- The ServiceMonitor reads Prometheus's existing rotating projected token.
  `bearerTokenFile` is used because the ServiceMonitor's `authorization` schema
  supports Secret selectors rather than credential files. No long-lived token
  Secret is created and no Prometheus pod-volume change is needed.
- The proxy ServiceAccount can only create TokenReviews and SubjectAccessReviews.
  It has no permission to read Secrets, Kubernetes objects, or etcd data. The
  container has no host filesystem mounts, etcd client certificates, elevated
  capabilities, or writable root filesystem, and runs as UID/GID `65532`.
- `hostNetwork` is required to reach host loopback. Ordinary pod NetworkPolicies
  are not relied on to isolate host-network listeners; TLS and request
  authentication/authorization enforce the access boundary. A compromised proxy
  still has host-network reachability, so the immutable image pin and minimum
  privileges matter.
- Delegated authentication and authorization depend on a working API server.
  The proxy caches successful authorization for five minutes. During an API
  outage, missing metrics can indicate a monitoring failure rather than proven
  etcd quorum loss. Check all three hosts directly before recovery.

The image is official `quay.io/brancz/kube-rbac-proxy:v0.23.0`, pinned to its
registry-verified Linux ARM64 manifest
`sha256:da1c385414e8dceb6ee8e89c1a3accfb5bc840640782e2567782d91308b46b33`.
The release's multi-platform index is
`sha256:a6075902738eaf1780390561ea998a53a056ef1d2b312bcbf0e2e81fec084b3c`.

## Alerts and diagnosis

| Alert | Condition | First read-only checks |
| --- | --- | --- |
| `K3sEtcdMetricsMissing` | Fewer than three native leader, WAL fsync, or backend commit metric series for 5 minutes | DaemonSet scheduling, ServiceMonitor discovery, per-target scrape errors, certificate status, RBAC, host loopback metrics |
| `K3sEtcdQuorumUnobserved` | Fewer than two members report a leader for 3 minutes | All three hosts and read-only etcd endpoint status; distinguish actual quorum loss from scrape/API failure |
| `K3sEtcdMemberNoLeader` | A native member reports no leader for 2 minutes | Peer connectivity and other members' state, then kernel/disk latency |
| `K3sEtcdWALFsyncSlow` | WAL fsync p99 exceeds 10ms for 10 minutes | Host storage latency, kernel I/O errors, competing writes |
| `K3sEtcdBackendCommitSlow` | Backend commit p99 exceeds 25ms for 10 minutes | Database size, node disk latency, kernel journal |
| `K3sEtcdDatabaseQuotaNearLimit` | Total database size exceeds 80% of quota for 15 minutes | Compare total versus in-use size and retained Kubernetes objects; free-page fragmentation is separate from quota exhaustion |

The expected member count is three, matching the current K3s control plane. A
membership change must update these alert thresholds in the same Git change.
TCP readiness confirms that the proxy has opened its listener; it does not prove
native metrics are flowing. Missing coverage alerts deliberately check native
metric families rather than only `up`.

For a read-only comparison, SSH to each control-plane node and inspect
`curl -fsS http://127.0.0.1:2381/metrics`. Native metrics should include
`etcd_server_has_leader`, `etcd_server_is_leader`,
`etcd_disk_wal_fsync_duration_seconds_bucket`,
`etcd_disk_backend_commit_duration_seconds_bucket`,
`etcd_mvcc_db_total_size_in_bytes`, and `etcd_server_quota_backend_bytes`.
Do not expose the unauthenticated listener on a node interface or mount etcd
client credentials into a monitoring pod.

## Validation and rollout

```sh
python3 scripts/check-etcd-observability.py
kubectl kustomize kubernetes/projects/system/apps/etcd-metrics > /tmp/etcd-metrics.yaml
kubectl apply --dry-run=server -f /tmp/etcd-metrics.yaml
python3 scripts/validate-workload-catalog.py
```

The Prometheus rule tests cover healthy membership, individual/all missing
targets, a successful scrape with no native metrics, missing disk families,
leader loss/recovery, sustained disk latency/recovery, counter resets, and quota
thresholds. Roll out through Git/Fleet only. No K3s service restart is required.

After Fleet converges, require its desired/applied deployment IDs to match,
the Certificate to be Ready, and the DaemonSet to have three Ready pods without
restarts. Verify both Prometheus replicas independently:

- `up{job="etcd"}`: exactly three healthy targets.
- `count by (instance) (etcd_server_has_leader{job="etcd"})`: all three node names.
- `sum(etcd_server_is_leader{job="etcd"})`: one leader.
- Both native disk histograms, database size, and quota metrics: three members.
- `prometheus_rule_evaluation_failures_total`: no new evaluation errors.
- A direct HTTPS request without credentials is rejected; a valid token without
  the named Service proxy grant is rejected; Prometheus's token succeeds with
  the issued CA and SAN verified. Other paths and non-GET methods must fail.

Rollback is a Git revert of this Fleet app. It removes the metrics proxies,
scrape configuration, dashboard, and alerts without changing K3s or etcd data.

Upstream references:
[K3s metrics listener implementation](https://github.com/k3s-io/k3s/blob/v1.36.5%2Bk3s1/pkg/etcd/etcd.go),
[kube-rbac-proxy resource authorization](https://github.com/kube-rbac-proxy/kube-rbac-proxy/tree/v0.23.0/examples/resource-attributes),
[etcd monitoring](https://etcd.io/docs/v3.6/op-guide/monitoring/), and
[etcd performance guidance](https://etcd.io/docs/v3.6/faq/#what-does-the-etcd-warning-apply-entries-took-too-long-mean).
