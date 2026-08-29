# Descheduler

This bundle installs the upstream Kubernetes Descheduler as a Fleet-managed
HelmOp. It runs as a 15-minute CronJob so the descheduler is idle between
balancing passes, then lets the default scheduler place evicted replacement pods
on less-loaded nodes.

The policy is tuned for steady rebalancing on the home Raspberry Pi cluster:

- Runs a control-plane profile before the general workload profile. It uses
  live CPU and memory across the cluster, but can evict only explicitly listed
  infrastructure namespaces whose pods already require control-plane nodes.
- Allows single-replica control-plane infrastructure to move when overloaded,
  while preserving PDB enforcement, system-critical priority protection,
  `nodeFit`, and the mandatory prefer-no-eviction annotation. This makes
  singleton Prometheus, Grafana, Loki, and similar NFS-backed services
  rebalancable without making singleton user applications evictable.
- Protects any control-plane pod backed by the `longhorn` storage class. NFS
  monitoring volumes remain movable because they are network-attached and do
  not require a Longhorn RWO detach/attach cycle.
- Uses Kubernetes Metrics Server CPU and memory utilization for
  `LowNodeUtilization`, so descheduling follows actual load instead of being
  blocked by many small pods on otherwise cooler nodes.
- Runs every 15 minutes with `concurrencyPolicy: Forbid` and a 5-minute active
  deadline, while `minPodAge: 10m` keeps freshly recreated pods from being
  churned repeatedly.
- Uses deviation thresholds so nodes are compared against the cluster average
  instead of fixed absolute targets, with a narrow CPU/memory window that keeps
  cooler nodes eligible as destinations when one node remains hot.
- Limits each run to at most four total evictions, two per node, and one per
  namespace.
- Requires `nodeFit` before eviction so a pod is only evicted when it can fit
  somewhere else.
- Skips pods at or above priority value `900000000`, reserving descheduler
  movement for workloads below the Shipyard critical priority tier.
- Protects controller-owned single-replica workloads with `minReplicas: 2`,
  avoiding availability gaps and unnecessary RWO volume detach/attach cycles.
  Workloads with two or more replicas remain eligible for balancing.
- Excludes Valkey from descheduler balancing. Even one-at-a-time evictions can
  create avoidable Longhorn RWO detach/attach churn for the replicated Valkey
  StatefulSet.
- Excludes ZITADEL from descheduler balancing. The login pods recover after
  replacement, but repeated voluntary evictions create unnecessary probe noise
  for the identity provider.
- Excludes PostgreSQL cluster and pooler pods from automated balancing. The
  default scheduler can place CNPG replicas back on the same node, so eviction
  would create repeated database churn without improving placement.
- Rack Ops and Cluster Ops controllers are worker-only and therefore excluded
  from the control-plane allowlist; node-pinned shutdown and thermal DaemonSets
  remain protected by descheduler's DaemonSet and node-fit checks.
- Allows replicated Longhorn/NAS PVC-backed application pods to move when they
  fit elsewhere, while protecting singleton PVC workloads and explicitly
  excluding Valkey.
- Leaves PDB enforcement to the Kubernetes eviction API.
- Keeps cluster/system namespaces excluded from the general workload profile;
  the separate control-plane profile handles only its explicit infrastructure
  allowlist. PostgreSQL, Valkey, and ZITADEL stay excluded.
