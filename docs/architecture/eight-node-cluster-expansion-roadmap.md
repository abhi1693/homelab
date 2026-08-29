# Eight-Node Cluster Expansion Roadmap

## Status

Implementation in progress. All five workers are joined; workload segregation
is being rolled out through Ansible and Fleet.

- **Last updated:** 2026-08-21
- **Target topology:** three K3s control-plane/etcd nodes and five K3s workers
- **Planning owner:** cluster operator
- **Change ownership:** Ansible for host and K3s bootstrap, Rancher Fleet for
  post-bootstrap Kubernetes desired state

## Executive Summary

The cluster now has eight Raspberry Pi 5 nodes. Keep the three K3s servers as
the control-plane/etcd pool and use `k8s-rpi4` through `k8s-rpi8` as the
five-worker application pool.

Prometheus, Grafana, Alertmanager, Rancher, Fleet, and other platform services
remain on the control-plane pool. User-facing applications, shared PostgreSQL,
Valkey, media services, and development workspaces move to workers. Node-local
agents such as Cilium, Longhorn, monitoring exporters, and CSI components
continue to run wherever their DaemonSet or storage responsibilities require.

At the 2026-08-16 baseline, this layout is expected to use about 56% of worker
CPU requests and 43% of worker memory requests in normal operation. After one
worker is lost, the remaining four workers are expected to use about 67% CPU
and 52% memory by requests. The target therefore provides comfortable N+1
scheduler capacity and preserves the control-plane nodes from application load.

The migration must be incremental. Do not join all nodes, relocate all pods, or
evacuate all Longhorn replicas in one operation. Every phase has a health gate
and a rollback boundary.

## Goals

- Reach eight homogeneous ARM64 nodes: three control-plane/etcd and five
  workers.
- Keep Kubernetes management and observability workloads on control-plane
  nodes.
- Keep user workloads off control-plane nodes during normal scheduling.
- Preserve three Longhorn replicas for every Longhorn volume without
  per-volume replica-count overrides.
- Maintain zero pending demand in steady state and safe N+1 worker capacity.
- Preserve CNPG, Valkey/Sentinel, Rancher, Fleet, ingress, and observability
  availability throughout staged migration.
- Make node-pool capacity and placement visible in Prometheus and Grafana.
- Keep every intended state change in Git and use the repository's normal
  Ansible or Fleet ownership boundary.

## Non-Goals

- Adding more control-plane or etcd members.
- Increasing Longhorn volumes above three replicas.
- Treating two simultaneous worker failures as a service-level availability
  guarantee. Three-member databases, caches, and storage replicas remain
  principally N+1 designs.
- Using ad hoc `kubectl patch`, `kubectl taint`, `kubectl label`, or manual
  Longhorn volume overrides as the final desired state.
- Changing application replica counts solely because more nodes exist.
- Combining the node expansion with K3s, Cilium, Rancher, or Longhorn version
  upgrades.

## Current Baseline

The baseline is a dated planning snapshot, not a permanent capacity promise.
Re-run the same measurements immediately before implementation.

### Topology

| Pool | Current nodes | Current behavior |
| --- | --- | --- |
| Control plane | `k8s-rpi1`, `k8s-rpi2`, `k8s-rpi3` | K3s server and embedded etcd; being restricted to critical platform workloads. |
| Worker | `k8s-rpi4` through `k8s-rpi8` | K3s agents and the ordinary application pool. |

The servers already have the standard
`node-role.kubernetes.io/control-plane=true` label. The segregation rollout
adds the K3s-recommended `CriticalAddonsOnly=true:NoExecute` taint after every
platform workload has been made eligible for it. Workers need no custom pool
label: their lack of that taint is the ordinary workload boundary.

### Capacity

| Metric | Baseline |
| --- | ---: |
| Cluster allocatable CPU | 16 cores |
| Cluster allocatable memory | 63.35 GiB |
| Scheduled CPU requests | 13.16 cores, 82.25% |
| Scheduled memory requests | 46.68 GiB, 73.68% |
| Seven-day CPU usage p95 | 23.2% of current cluster capacity |
| Seven-day memory usage p95 | 52.8% of current cluster capacity |
| Pending CPU and memory demand | 0 |
| User-workload CPU requests | 8.235 cores |
| User-workload memory requests | 28.36 GiB |
| User-workload seven-day CPU p95 | 1.95 cores |
| User-workload seven-day memory p95 | 20.09 GiB |

Scheduled requests, rather than live CPU usage, are the immediate constraint.
Capacity checks must continue to separate scheduled requests from pending
demand so rolling replacements are not counted as steady-state reservations.

### Storage and stateful services

- Longhorn defaults and all existing volumes are intended to use three
  replicas with strict inter-node anti-affinity.
- The Longhorn concurrent replica rebuild limit is five per node. That is a
  ceiling, not a target; migration must still limit the number of nodes being
  evacuated at once.
- Longhorn replica rebuild traffic can saturate a Raspberry Pi's 1 GbE link and
  increase NVMe I/O wait and temperature.
- CNPG currently has three PostgreSQL instances and uses PgBouncer for shared
  application access.
- Valkey has three data pods with Sentinel. Quorum and pod distribution must be
  verified after every stateful relocation.
- Prometheus, Grafana, Alertmanager, Rancher, and Fleet remain in the
  control-plane pool in the target design.

## Target Architecture

### Node inventory

The names below follow the existing inventory convention. Addresses, MACs,
serial numbers, switch ports, and lifecycle data must be assigned in NetBox
before inventory is committed.

| Ansible host | Kubernetes hostname | Role | Target pool |
| --- | --- | --- | --- |
| `server-1` | `k8s-rpi1` | K3s server and etcd | `control-plane` |
| `server-2` | `k8s-rpi2` | K3s server and etcd | `control-plane` |
| `server-3` | `k8s-rpi3` | K3s server and etcd | `control-plane` |
| `worker-1` | `k8s-rpi4` | K3s agent | `worker` |
| `worker-2` | `k8s-rpi5` | K3s agent | `worker` |
| `worker-3` | `k8s-rpi6` | K3s agent | `worker` |
| `worker-4` | `k8s-rpi7` | K3s agent | `worker` |
| `worker-5` | `k8s-rpi8` | K3s agent | `worker` |

### Scheduling contract

Use the standard K3s control-plane label and critical-addons taint. Do not add a
parallel home-lab pool label:

```text
node-role.kubernetes.io/control-plane=true
CriticalAddonsOnly=true:NoExecute
```

| Workload class | Required pool | Tolerates control-plane taint | Examples |
| --- | --- | --- | --- |
| Control-plane host processes | Control plane | Not applicable | K3s server, API server, scheduler, controller manager, embedded etcd. |
| Platform deployments | Control plane | Yes | Rancher, Fleet controllers and GitJob, Prometheus, Grafana, Alertmanager, monitoring operators. |
| Node-local platform agents | Applicable nodes | Yes when required | Cilium, Longhorn manager/CSI node components, node exporter, SMART exporter. |
| User stateless workloads | Worker | No | Wardn, ShipyardHQ, Harbor, portfolio, personal blog, application APIs and workers. |
| User stateful workloads | Worker | No | PostgreSQL, Valkey, Home Assistant, NetBox, media services, OpenBao, Coder workspaces. |
| Batch and CronJob workloads | Worker unless explicitly platform-owned | No | Media maintenance and application jobs. |

Platform Deployments, StatefulSets, controllers, and platform CronJobs require
`node-role.kubernetes.io/control-plane=true` and exactly tolerate
`CriticalAddonsOnly=true:NoExecute`. Node-local DaemonSets tolerate the taint
without a control-plane-only selector so they continue serving workers.

User workloads must not tolerate `CriticalAddonsOnly`. They require no custom
worker selector: once `NoExecute` is applied, existing user pods are evicted
from servers and both existing and replacement pods can schedule only on the
untainted workers. Host-bound infrastructure is an explicit exception; for
example, UPS monitoring remains on `k8s-rpi1` because its USB device is there
and therefore receives the critical toleration.

### Capacity model

Each worker contributes approximately 4 allocatable CPU cores and 15.84 GiB of
allocatable memory. Current node-local DaemonSet and Longhorn instance-manager
requests add approximately 0.61 CPU and 1.20 GiB per worker.

| Worker condition | Available workers | Capacity | Planned requests | Request utilization |
| --- | ---: | ---: | ---: | ---: |
| Normal | 5 | 20 CPU / 79.19 GiB | 11.29 CPU / 34.34 GiB | 56.4% CPU / 43.4% memory |
| N+1 | 4 | 16 CPU / 63.35 GiB | 10.68 CPU / 33.14 GiB | 66.7% CPU / 52.3% memory |
| N+2 planning case | 3 | 12 CPU / 47.51 GiB | 10.07 CPU / 31.95 GiB | 83.9% CPU / 67.2% memory |

This model assumes platform deployments remain on control-plane nodes. If an
implementation leaves ordinary platform workloads on workers, the N+1 worker
CPU request ratio can rise to approximately 82%; that state is acceptable only
as a transition, not as the target placement contract.

The existing platform and node-agent requests are expected to use roughly 36%
of the three-node control-plane pool's CPU and memory. Re-measure after pinning
platform workloads because singleton placement, especially Prometheus, can make
one control-plane node materially heavier than the pool average.

### Storage contract

- Keep `longhorn.default_class_replica_count` and
  `longhorn.default_replica_count` at three.
- Keep strict replica anti-affinity. A volume must not be created with fewer
  replicas merely because placement is temporarily unavailable.
- Do not add application-specific or volume-specific replica-count overrides.
- Make all five worker NVMe disks eligible before removing any control-plane
  disk from replica scheduling.
- Use a shared Longhorn node/disk scheduling policy or tags to prefer the worker
  storage pool. Do not encode the policy separately on every PVC or volume.
- Evacuate control-plane replica data one node at a time only after the compute
  migration is stable. Wait for every volume to return healthy before starting
  the next node.
- Longhorn node components may remain on control-plane nodes even after their
  disks stop accepting application replicas; the exact chart-generated
  DaemonSet behavior must be preserved.

## Repository Workstreams

| Workstream | Primary paths | Required result |
| --- | --- | --- |
| Inventory | `infrastructure/ansible/inventories/home/hosts.yml`, `host_vars/worker-*.yml` | Five workers with unique identity and NetBox-backed addressing. |
| K3s node identity | `group_vars/k3s_nodes.yml`, `roles/k3s_server/` | Declarative `CriticalAddonsOnly` taint support, live reconciliation, and validation. |
| Platform placement | Rancher role values, Rancher Monitoring values, Fleet chart values, system app manifests | Platform controllers require the standard control-plane label and tolerate the critical taint. |
| User placement | Project app manifests and Helm values under `kubernetes/projects/` | User PodTemplates have no critical toleration and no legacy control-plane hostname pin. |
| Longhorn placement | Longhorn inventory, role templates/tasks, validation | Three replicas and a global worker-storage scheduling policy with no volume overrides. |
| Capacity observability | `capacity-planning-rules.yaml`, `capacity-planning-dashboard.yaml`, alerts | Separate control-plane and worker capacity, scheduled requests, pending demand, and N+1 headroom. |
| Documentation | Root, infrastructure, project, and app READMEs | Current topology, placement ownership, validation, and rollback stay synchronized. |

## Phased Roadmap

### Phase 0: Establish the pre-change gate

- **Owner:** cluster operator
- **Effort:** half a day
- **Mutation:** none

1. Confirm the repository branch and Fleet source are synchronized.
2. Confirm all eight nodes are `Ready`, time-synchronized, and free of
   `DiskPressure`, `MemoryPressure`, and active Raspberry Pi throttle states.
3. Require zero active unhealthy Longhorn volumes and zero running replica
   rebuilds. Do not begin expansion while PostgreSQL or another critical volume
   is degraded.
4. Confirm all 23 current Longhorn volumes still request three replicas.
5. Confirm CNPG is healthy at 3/3 instances, replication lag is normal, the
   latest scheduled backup succeeded, and PgBouncer has no sustained waiting
   clients.
6. Confirm all three Valkey data endpoints and Sentinel quorum are healthy with
   no current evictions or rejected connections.
7. Capture worker and control-plane CPU, memory, disk, network, temperature,
   pod placement, and restart baselines from Prometheus.
8. Confirm Fleet child bundles and direct workloads are healthy. Do not rely
   only on a parent HelmOp or GitRepo status that may be stale.
9. Freeze unrelated K3s, Cilium, Rancher, Longhorn, and storage migrations until
   the eight-node expansion reaches its final soak gate.

**Exit gate:** every stateful service is healthy, no rebuild is active, no pod
is pending, and the dated baseline is attached to the implementation change.

**Rollback:** not applicable; this phase is read-only.

### Phase 1: Add the declarative critical-addons boundary

- **Owner:** infrastructure/Ansible
- **Effort:** one to two days
- **Mutation:** repository first; no taint applied yet

1. Add role-scoped inventory inputs for the server taint and managed taint keys.
2. Extend the K3s server config template so rebuilt and newly joined servers
   receive the intended taint at registration.
3. Add validation for:
   - the standard control-plane label on K3s servers;
   - the absence or presence of the control-plane taint according to the
     current migration phase.
4. Define an idempotent, repository-owned transition for existing Node objects.
   Do not depend on registration-only configuration to retroactively update
   nodes and do not make ad hoc labels or taints the lasting state.
5. Leave the live control-plane nodes untainted until platform placement is
   rendered, deployed, and verified.

**Validation:** Ansible syntax checks, role validation entrypoints, rendered K3s
config inspection, and read-only verification of the four live Node objects.

**Exit gate:** the three servers retain their standard control-plane label and
the taint is fully declarative but has not been applied before its preflight.

**Rollback:** revert the pool-identity commit and run the matching idempotent
Ansible transition. Labels are metadata; do not reset or rejoin nodes.

### Phase 2: Prepare hardware, network, and inventory

- **Owner:** cluster operator and infrastructure/Ansible
- **Effort:** one day before joins
- **Mutation:** NetBox and Git inventory

For each proposed worker:

1. Record board, serial number, MAC address, NVMe identity, power source, rack
   position, switch port, and lifecycle owner in NetBox.
2. Reserve a LAN address and internal DNS name. Do not place private identifiers
   in the public README.
3. Verify the switch has four available 1 GbE ports and sufficient backplane
   capacity for concurrent east-west Longhorn traffic.
4. Verify UPS capacity, power distribution, and cooling for four additional
   Raspberry Pi 5 systems and NVMe devices.
5. Match the existing hardware envelope: four ARM64 cores, approximately
   15.8 GiB allocatable memory, 500GB-class NVMe, and wired 1 GbE.
6. Add `worker-2` through `worker-5` to the home inventory and add individual
   host variables for `k8s-rpi5` through `k8s-rpi8`.
7. Run inventory parsing, Ansible syntax checks, and role validation before any
   host is contacted.

**Exit gate:** inventory is complete and reviewable, power/network capacity is
confirmed, and no node has joined the cluster.

**Rollback:** remove an uncommissioned host from inventory. Do not reuse an IP,
hostname, or Longhorn disk identity until NetBox is corrected.

### Phase 3: Join and soak four workers individually

- **Owner:** infrastructure/Ansible
- **Effort:** one worker per change window
- **Mutation:** one new host and its node-local Kubernetes agents per window

Repeat the following sequence for `worker-2`, then `worker-3`, `worker-4`, and
`worker-5`. Never target the whole `k3s_workers` group for the first join.

1. Run OS preparation and Raspberry Pi preparation for only the selected host.
2. Run their validation entrypoints and resolve kernel, cgroup, time, storage,
   or registry-mirror failures before K3s installation.
3. Join the node with the K3s agent role through the kube-vip registration VIP.
4. Validate the K3s agent service, node identity, kubelet hardening, image GC,
   registry mirror, and `LimitNOFILE` settings.
5. Wait for Cilium, node exporter, SMART exporter, Longhorn manager/CSI, and
   other required DaemonSets to become ready on the node.
6. Validate Cilium endpoint health and east-west connectivity without creating
   diagnostic pods unless separately authorized.
7. Validate NVMe SMART health, temperature, filesystem free space, Longhorn disk
   readiness, and the 25% minimum/reserved-space policy.
8. Confirm the added DaemonSet and instance-manager requests match the capacity
   model, approximately 0.61 CPU and 1.20 GiB memory per worker.
9. Soak the worker for at least one normal monitoring interval before joining
   the next node. A longer soak is required after any network, thermal, or disk
   anomaly.

**Per-node exit gate:** the worker is `Ready`, reports the correct labels, has
no pressure or throttle state, all expected node agents are ready, Longhorn is
healthy, and no existing workload degraded during the join.

**Rollback:** stop after the affected node. Use the repository's K3s agent reset
entrypoint only after confirming it owns the target host and that Longhorn has
no replica or attachment on it. Never reset multiple workers together.

### Phase 4: Pin platform workloads to control-plane nodes

- **Owner:** platform GitOps
- **Effort:** two to three days
- **Mutation:** Fleet-managed platform PodTemplates

Complete this phase before applying the control-plane taint.

1. Add the standard control-plane selector and exact critical-addons toleration
   to Rancher. Preserve its required pod anti-affinity and two-replica rolling
   update behavior.
2. Configure Fleet controller, GitJob, agent-management, and other local Fleet
   control-plane deployments through supported chart values. Validate rendered
   manifests rather than assuming a value affects every Fleet component.
3. Add control-plane affinity and tolerations to Prometheus, Alertmanager,
   Grafana, Prometheus Operator, kube-state-metrics, and other non-node-local
   Rancher Monitoring components.
4. Audit every live Deployment, StatefulSet, DaemonSet, Job, and CronJob, not
   only named examples. Keep cluster management, policy, observability,
   operators, and telemetry backends on control-plane nodes; keep node-local
   DaemonSets eligible wherever they must observe, network, or serve storage.
5. Preserve hard anti-affinity for replicated platform services across the
   three control-plane hostnames.
6. Roll out one platform bundle at a time and verify child Fleet bundles,
   Deployment/StatefulSet readiness, services, EndpointSlices, ingress, and
   fresh logs.
7. Re-measure per-control-plane request and live-use balance. Prometheus must not
   make one node breach the placement gate while the pool average appears safe.

**Exit gate:** all selected platform pods run on `control-plane` nodes, all
node-local agents remain ready on eight nodes, Rancher and Fleet reconcile, and
monitoring has no scrape gaps attributable to placement.

**Rollback:** revert only the affected platform placement commit. Confirm the
old ReplicaSet or StatefulSet becomes ready before rolling back another
component.

### Phase 5: Migrate stateless and low-risk user workloads

- **Owner:** application GitOps
- **Effort:** one to two days
- **Mutation:** Fleet-managed application PodTemplates

1. Remove any legacy control-plane hostname pins from stateless workloads and
   confirm they do not tolerate `CriticalAddonsOnly`.
2. Move application groups in small batches, ordered from low dependency impact
   to high dependency impact.
3. Preserve existing pod anti-affinity and topology spread constraints; extend
   them to use `kubernetes.io/hostname` across the five workers where needed.
4. Ensure batch Jobs and CronJobs inherit the same no-critical-toleration
   contract as their owning application.
5. Verify every changed child Fleet bundle and direct workload. Check fresh pod
   image IDs, readiness, EndpointSlices, ingress, logs, and application probes.
6. Confirm there is no pending demand and that worker-pool scheduled requests
   remain below the phase capacity gate.

**Exit gate:** selected stateless workloads have zero pods on control-plane
nodes, all replicas are ready, and worker-pool requests remain below 70% CPU and
65% memory in normal operation.

**Rollback:** revert the latest workload batch. Do not change the control-plane
taint because it has not been applied yet.

### Phase 6: Migrate databases and stateful user workloads

- **Owner:** database/application GitOps and cluster operator
- **Effort:** two to four maintenance windows
- **Mutation:** one stateful failure domain at a time

Order stateful moves so each dependency is healthy before its consumers move.

#### PostgreSQL

1. Confirm a recent successful CNPG backup and a valid first recoverability
   point.
2. Preserve inter-pod anti-affinity/topology spread and ensure CNPG-managed
   database pods do not tolerate the control-plane taint. Only the CNPG
   operator itself is pinned to control plane.
3. Relocate one replica at a time. Keep two healthy instances while the moved
   instance catches up.
4. Move or switch the primary only after both standbys are streaming and
   PgBouncer endpoints are healthy.
5. Require 3/3 ready instances, normal replication lag, active replication
   slots, healthy poolers, and a successful post-migration backup.

#### Valkey and Sentinel

1. Preserve three distinct hostnames and ensure Valkey does not tolerate the
   control-plane taint.
2. Move one pod at a time and require master-link health before proceeding.
3. Verify the master, two replicas, Sentinel quorum, connected clients, and zero
   new evictions or rejected connections.

#### Singleton and RWO applications

1. Inventory every singleton, `Recreate` deployment, StatefulSet, and Longhorn
   RWO attachment before changing placement.
2. Schedule a maintenance window for workloads with a real serving gap, such as
   singleton `Recreate` applications.
3. Let Fleet change the PodTemplate and wait for CSI detach/attach to complete.
   Do not manually delete VolumeAttachments.
4. Verify application-specific state, database connectivity, ingress, and fresh
   logs before the next singleton moves.

**Exit gate:** PostgreSQL and Valkey are healthy on distinct workers; all moved
stateful workloads serve successfully; there are no stuck attachments, pending
pods, or degraded volumes caused by the migration.

**Rollback:** stop at the affected workload. Revert its placement commit and
wait for the storage attachment and application to recover before any other
stateful change. Restore data only when integrity evidence requires it; do not
use backup restoration as a scheduling rollback shortcut.

### Phase 7: Move Longhorn replica placement to workers

- **Owner:** storage platform and cluster operator
- **Effort:** variable; one control-plane disk evacuation per maintenance
  window
- **Mutation:** Longhorn replica placement, not replica count

This phase is deliberately separate from workload scheduling.

1. Confirm all five worker disks are Ready, schedulable, healthy, and above
   Longhorn's minimum/reserved-space thresholds.
2. Implement the global worker storage policy in the Longhorn-owned inventory,
   role, or StorageClass surface. Keep the default replica count at three and
   remove no existing guardrail.
3. Stop if any volume is already degraded or rebuilding.
4. Disable new replica scheduling on one control-plane disk through the
   repository-owned policy.
5. Request or allow evacuation through the chosen Longhorn node/disk policy.
   Never delete replica directories or patch individual volume replica counts.
6. Observe replica modes, rebuild progress, per-node network throughput, NVMe
   I/O wait, temperature, and application latency.
7. Require every volume to return to three healthy replicas on distinct nodes
   before starting the next control-plane disk.
8. Repeat for the second and third control-plane disks.
9. Confirm control-plane nodes still run the Longhorn node components required
   by attached system workloads, while their disks no longer accept application
   replicas.

**Stop conditions:** any rebuild reset, mount/I/O error, CNPG lag outside its
normal envelope, Valkey link failure, active thermal throttling, sustained
network saturation, or a second degraded volume.

**Exit gate:** every Longhorn volume is healthy with three replicas; replica
disks are in the intended worker pool; no per-volume replica overrides exist.

**Rollback:** re-enable the last control-plane disk through the same owned
policy and allow Longhorn to recover. Do not evacuate another disk and do not
manually remove the new healthy replicas.

### Phase 8: Apply the control-plane scheduling boundary

- **Owner:** infrastructure/Ansible and platform GitOps
- **Effort:** one maintenance window
- **Mutation:** control-plane Node taints and final placement reconciliation

1. Prove that all non-node-local platform workloads have the standard
   control-plane selector and exact critical-addons toleration.
2. Prove that node-local agents tolerate the taint without a control-plane-only
   selector, and that all user PodTemplates have no critical toleration.
3. Apply `CriticalAddonsOnly=true:NoExecute` to one K3s server at a time through
   the repository-owned, idempotent Ansible transition.
4. `NoExecute` evicts existing pods that lack a matching toleration. Stop after
   each server until platform readiness and user replacement scheduling pass.
5. Verify that new and recreated user pods can schedule while one worker is
   considered unavailable in the capacity model.
6. Verify that Rancher, Fleet, Prometheus, Grafana, Alertmanager, and operators
   continue to recreate on control-plane nodes.

**Exit gate:** zero user pods run on control-plane nodes, zero platform pods run
outside their declared pool except node-local agents, all nodes have the target
labels/taints, and there is zero pending demand.

**Rollback:** remove the managed taint through the same Ansible desired state if
worker scheduling or a platform exception was missed, then correct the owning
Fleet bundle before retrying.

### Phase 9: Resilience validation and soak

- **Owner:** cluster operator
- **Effort:** seven-day soak plus one approved maintenance test
- **Mutation:** only separately approved maintenance operations

1. Add worker/control-plane pool panels and alerts before declaring the project
   complete.
2. Observe at least seven days of CPU, memory, network, disk, temperature,
   scheduler, database, cache, and storage behavior.
3. During an approved maintenance window, test one-worker unavailability. Use
   the normal operator runbook; do not improvise a failure by powering off a
   stateful node.
4. Verify that user workloads reschedule within their documented availability
   behavior and worker N+1 request utilization stays inside its action gate.
5. Verify control-plane quorum and platform services during one control-plane
   maintenance event separately from the worker test.
6. Refresh the dated capacity baseline and update the root hardware facts only
   after the eight-node state is real.

**Exit gate:** seven-day operation is stable, the approved N+1 tests pass, the
capacity dashboard reflects both pools, documentation matches live topology,
and all Fleet child bundles and workloads are healthy.

## Capacity and Reliability Gates

| Signal | Watch | Stop or act |
| --- | ---: | ---: |
| Worker normal scheduled CPU requests | 70% | 80% |
| Worker N+1 scheduled CPU requests | 75% | 85% |
| Worker normal scheduled memory requests | 65% | 75% |
| Worker N+1 scheduled memory requests | 70% | 80% |
| Any individual node scheduled CPU requests | 85% | 90% |
| Any individual node scheduled memory requests | 80% | 90% |
| Pending CPU or memory demand | greater than zero for 5 minutes | greater than zero for 15 minutes or blocks rollout |
| Longhorn unhealthy volumes | 1 | Stop at any active degraded or faulted volume during migration |
| Longhorn replicas per volume | not equal to 3 | Stop; reconcile through the shared policy |
| Raspberry Pi throttle state | any occurred state | any active state |
| Node network utilization during rebuild | 700 Mbps sustained | 800 Mbps sustained or application impact |
| PostgreSQL replication lag | outside seven-day normal envelope | sustained growth or replica disconnect |
| Valkey evictions/rejections | any increase | sustained increase or Sentinel quorum loss |
| Fleet/workload readiness | one stale parent with healthy child/workload | unhealthy child bundle or unready workload |

Forecasts remain advisory until Prometheus retains the full intended planning
window. Decisions must use current scheduled requests, pending demand, seven-day
p95/p99 use, and the relevant node-pool failure calculation.

## Observability Changes

Add recording rules that derive control-plane membership from
`node-role.kubernetes.io/control-plane` and treat the remaining nodes as the
worker pool:

- allocatable CPU and memory by pool;
- scheduled CPU and memory requests by pool;
- pending CPU and memory demand by intended pool;
- live CPU and working-set memory by pool;
- per-pool request and use percentages;
- largest single-node capacity in each pool;
- N+1 capacity and request percentages;
- pod count and unavailable workload count by pool;
- user pods on control-plane nodes and platform pods outside control-plane
  nodes.

Update the capacity dashboard with separate control-plane and worker rows. Keep
the existing cluster aggregate as context, but never use it alone for an
admission or procurement decision after pool isolation.

Add alerts for placement violations, worker N+1 request pressure, missing pool
labels, unexpected taint loss, and Longhorn replicas placed outside the target
storage pool.

## Validation Commands

These examples are read-only unless the referenced Ansible entrypoint is the
operator-approved implementation step.

Repository validation:

```sh
cd infrastructure/ansible
ansible-inventory --graph
ansible-playbook --syntax-check playbooks/site.yml
ansible-playbook playbooks/k3s_agent.yml -e k3s_agent_entrypoint=validation --limit worker-2
ansible-playbook playbooks/k3s_server.yml -e k3s_server_entrypoint=validation
```

Node and placement validation:

```sh
kubectl get nodes -o wide --show-labels
kubectl get pods -A -o wide
kubectl get events -A --sort-by=.metadata.creationTimestamp
```

Stateful-service validation:

```sh
kubectl -n postgresql get clusters.postgresql.cnpg.io,pods,poolers.postgresql.cnpg.io
kubectl -n postgresql get backups.postgresql.cnpg.io --sort-by=.metadata.creationTimestamp
kubectl -n valkey get pods -o wide
kubectl -n longhorn-system get volumes.longhorn.io,replicas.longhorn.io,engines.longhorn.io
```

Fleet validation:

```sh
kubectl -n fleet-local get gitrepos.fleet.cattle.io,bundles.fleet.cattle.io
kubectl get bundledeployments.fleet.cattle.io -A
```

Use direct Deployment, StatefulSet, pod, and EndpointSlice state to resolve any
stale parent Fleet or HelmOp status before deciding whether a phase passed.

## Implementation Change Sequence

Keep review and rollback boundaries narrow. The preferred commit or pull-request
sequence is:

1. Add K3s server taint schema/template/reconciliation support and validation.
2. Add the four worker inventory records without joining them all at once.
3. Add pool-aware capacity recording rules, dashboard panels, and alerts.
4. Pin Rancher, Fleet, monitoring, and platform operators to control-plane
   nodes.
5. Remove control-plane pins and critical tolerations from user application groups.
6. Verify PostgreSQL, Valkey, singleton, and other stateful applications have
   no critical toleration.
8. Add the shared Longhorn worker-storage policy and migrate one disk at a time.
9. Apply the control-plane taint after placement violations reach zero.
10. Update current-state hardware facts and close the roadmap after the soak.

Do not squash the operational rollout into one irreversible commit. A later
phase must be independently revertible without undoing already validated node
joins or healthy storage placement.

## Completion Checklist

- [ ] Eight nodes are `Ready`: three control-plane/etcd and five workers.
- [ ] Every server has the standard control-plane label; no custom pool label
  is required.
- [ ] Every control-plane node has `CriticalAddonsOnly=true:NoExecute`.
- [ ] Rancher, Fleet, Prometheus, Grafana, Alertmanager, and platform operators
  run on control-plane nodes.
- [ ] User workloads run only on workers.
- [ ] Node-local agents are ready on every applicable node.
- [ ] Worker normal and N+1 capacity gates pass with zero pending demand.
- [ ] CNPG has three healthy instances, healthy poolers, and a successful
  post-migration backup.
- [ ] Valkey and Sentinel are healthy with distinct-node placement.
- [ ] Every Longhorn volume is healthy with three replicas and no per-volume
  replica override.
- [ ] No Longhorn application replica remains on a control-plane disk if worker
  storage isolation is enabled.
- [ ] Pool-aware Grafana panels and alerts are active.
- [ ] Fleet child bundles, workloads, EndpointSlices, ingress, and fresh logs
  pass verification.
- [ ] The seven-day soak and approved N+1 maintenance tests pass.
- [ ] Root and subsystem READMEs describe the live eight-node topology rather
  than the former four-node state.

## Revisit Triggers

Revisit the design when any of these becomes true:

- worker N+1 scheduled CPU requests exceed 75% for seven days;
- worker N+1 scheduled memory requests exceed 70% for seven days;
- more than one worker must be unavailable during routine maintenance;
- Longhorn rebuilds regularly saturate 1 GbE or affect application latency;
- control-plane platform workloads exceed 60% CPU or 70% memory by requests;
- Prometheus retention or cardinality prevents reliable pool-level forecasting;
- application availability requirements exceed the guarantees of three-member
  PostgreSQL, Valkey, or Longhorn placement.

At that point, evaluate a sixth worker, faster east-west networking, dedicated
storage, or higher service replica counts as separate decisions rather than
silently weakening this roadmap's safety gates.
