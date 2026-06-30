# Descheduler

This bundle installs the upstream Kubernetes Descheduler as a Fleet-managed
HelmOp. It runs as a 15-minute CronJob so the descheduler is idle between
balancing passes, then lets the default scheduler place evicted replacement pods
on less-loaded nodes.

The policy is tuned for steady rebalancing on the home Raspberry Pi cluster:

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
- Allows stateless single-replica workloads to restart on cooler nodes with
  `minReplicas: 1`.
- Allows Valkey Sentinel pods to move one at a time through the eviction API;
  Valkey's PDB uses `maxUnavailable: 1`, and the descheduler policy also caps
  evictions at one pod per namespace per pass.
- Allows PostgreSQL cluster and pooler pods to move only through
  `LowNodeUtilization`; CNPG and pooler PDBs remain the hard gate, including
  the primary PDB with zero voluntary disruptions allowed.
- Allows the Rack Ops controller to move; node-pinned shutdown and thermal
  DaemonSets remain protected by descheduler's DaemonSet and node-fit checks.
- Allows Longhorn/NAS PVC-backed application pods to move when they fit
  elsewhere.
- Leaves PDB enforcement to the Kubernetes eviction API.
- Excludes cluster/system namespaces from utilization and topology-spread
  rebalancing. Valkey and Rack Ops are movable, and PostgreSQL is movable only
  through utilization balancing while remaining excluded from
  duplicate/topology-spread rebalancing.
