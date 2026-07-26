# Kubernetes Resource Policy

## Meaning

Production Pods must be schedulable from declared resource requests and must
not be able to consume unbounded memory. Directly authored regular and init
containers therefore declare CPU and memory requests plus a memory limit.

CPU limits are required for short-lived init containers, batch work, and small
controllers when the chart exposes the setting. They are intentionally omitted
for latency-sensitive or throughput-sensitive datapaths, including the Cilium
agent and Envoy, Longhorn Manager, and selected application data containers.
Those containers remain bounded by memory and schedulable by both requests.

## Impact

Requests prevent BestEffort scheduling and make node commitments visible.
Memory limits contain leaks and runaway processes. Selective CPU bursting avoids
CFS throttling on networking, storage, databases, and application hot paths.

The initial values are production starting points derived from 14 days of
Prometheus history, with headroom above observed p95/p99 usage. Revisit them
after workload or replica changes rather than treating them as permanent
capacity guarantees.

## Enforcement

The repository uses three enforcement layers:

1. Direct manifests declare resources on every regular and init container.
   `scripts/check-kubernetes-resource-bounds.py` enforces CPU/memory requests
   and memory limits in CI. It also requires recommendation-profile
   `minChangePercent` values to remain below `maxDecreasePercent`, preventing a
   bounded downsize from being discarded by the material-change gate.
2. Bootstrap and application charts use native resource values for Cilium,
   Envoy, cert-manager, Longhorn Manager and CSI sidecars, Fleet controllers,
   Traefik, Rancher Monitoring, ZITADEL helper containers, and other supported
   components.
3. Narrow `LimitRange` defaults cover generated containers whose owning chart
   or operator has no resource field. These defaults are limited to the
   Cloudflare connector, Home Assistant, PostgreSQL Pooler, and Rancher/Fleet
   controller namespaces. Explicit resources always take precedence.

Namespace defaults in shared monitoring and Fleet namespaces provide CPU and
memory requests plus a memory limit without introducing a generic CPU limit.
Controller-only namespaces may also default a conservative CPU limit.

## Longhorn Exception

Do not add a generic `LimitRange` to `longhorn-system`. Longhorn 1.11 exposes
resource values for Manager and system-managed CSI components, and the repo
uses those values. It does not expose equivalent per-workload memory settings
for instance managers, share managers, engine-image DaemonSets, all driver/UI
helpers, or recurring filesystem-trim Pods.

The latest seven-day window measured the four instance managers at about 1.745
CPU cores in aggregate at p95 and 1.968 cores at p99. Per-node p95 ranged from
217m to 1.144 cores because attached engine and replica work is unevenly
distributed. Share managers and CSI helpers are much smaller. One namespace
default would either under-size storage I/O or reserve excessive memory for
every helper. Instance managers therefore retain Longhorn's 12 percent
guaranteed CPU setting, or 480m on each four-core node, while remaining
CPU-unlimited so rebuild and recovery work can burst above the reservation.
Lower settings are not applied while engine instances are running and must not
be forced through instance-manager deletion. Revisit this setting after a
tested Longhorn upgrade/failover rehearsal or when the upstream chart exposes
safe component-specific values.

## Diagnosis

List admitted Pod containers that still have neither requests nor limits. This
view includes values supplied by `LimitRange` admission:

```sh
kubectl get pods -A -o json \
  | jq -r '
      .items[] as $pod
      | (($pod.spec.initContainers // []) + ($pod.spec.containers // []))[]
      | select(((.resources.requests // {}) | length) == 0
          and ((.resources.limits // {}) | length) == 0)
      | [$pod.metadata.namespace, $pod.metadata.name, .name]
      | @tsv' \
  | sort -u
```

LimitRange defaults are applied when Pods are created. Existing Pods retain
their admitted resources until the owning controller rolls them out.

## Verification

Run the direct-manifest policy and normal repository validation:

```sh
python scripts/check-kubernetes-resource-bounds.py
yamllint .
cd infrastructure/ansible
ansible-playbook --syntax-check playbooks/site.yml
```

For Helm-backed changes, render the exact pinned chart with the Git-managed
values and inspect every regular/init container. After push, wait for Fleet
GitRepos and bundles to become ready, then repeat the read-only live audit.

## Rollback

Revert the Git commit and let Fleet or the bootstrap workflow reconcile the
previous values. Do not delete or patch live Pods manually. If a new limit
causes restart loops or throttling, raise or remove that component-specific
limit in Git; keep CPU/memory requests and a memory limit unless the Longhorn
exception above applies.
