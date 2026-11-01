# Longhorn storage pools

Fleet owns the storage classes, admission policies and a single reconciler
Deployment. Ansible retains ownership of the Longhorn HelmCharts. The current
Kubernetes admission API is `admissionregistration.k8s.io/v1`; the reconciler
uses Longhorn `v1beta2` and Python's standard library.

Fleet also owns the `longhorn` HelmChartConfig in `kube-system`. Its
`failurePolicy: abort` prevents an unsuccessful chart reconciliation from
falling back to an uninstall/reinstall. The configuration starts without value
overrides; the reconciler owns only `spec.values.persistence` after the
storage-class retirement gate opens. Fleet comparison exclusions preserve that
field and the worker class's default annotation.

The reconciler requests 10m CPU and 32Mi memory, with a 128Mi memory limit.
Short API-processing CPU bursts are uncapped to avoid CFS throttling alerts;
the loop sleeps between reconciliations.

| Pool | Nodes | Longhorn tag | StorageClass |
| --- | --- | --- | --- |
| Control plane | Nodes with the control-plane role (`k8s-rpi1`–`k8s-rpi3`) | `storage-control-plane` | `longhorn-control-plane` |
| Worker | Other cluster nodes (`k8s-rpi4`–`k8s-rpi8`) | `storage-worker` | `longhorn-workers` |

`policy.yaml` assigns `cattle-monitoring-system` and `cups` claims to the
control-plane pool. Other namespaces, including Home Assistant, use workers.
Review this namespace map together with application placement when adding a
control-plane workload.

Each class requests three replicas with hard node anti-affinity inherited from
the cluster. The reconciler preserves unrelated tags and adds the corresponding
Kubernetes node label `home-lab.io/storage-pool` for RWX share managers. It
enforces volume node selectors and reports replicas or share managers placed
outside their assigned pool.

## Provisioning and existing claims

A creation-only MutatingAdmissionPolicy routes default/Longhorn PVC requests to
the class for their namespace. Explicit NFS classes, explicitly empty class
names and pre-bound `volumeName` requests are excluded. Bound PVCs keep their immutable storageClassName and volume
bindings. Chart and StatefulSet claim templates can therefore keep their
existing claims; newly created claims receive the pool class at admission.

The two pool classes select both Longhorn replica nodes and RWX share-manager
nodes. A second creation-only policy puts share managers without a pool selector
on workers, covering the existing worker RWX volumes. Explicit class-provided
share-manager pool selectors are preserved. A namespace reassignment involving
RWX volumes requires reviewing that policy and the share-manager class together.

Application scheduling must also agree with the pool. Current control-plane
applications are pinned by their manifests, and worker applications lack the
control-plane taint toleration.

## Default class retirement gate

`retireStorageClass: longhorn` arms an automatic switch to `longhorn-workers`.
It runs only after pool placement has converged and every node is healthy.
The gate requires **zero PVCs and zero PVs referencing `longhorn`**, including
Pending, Released, Failed and terminating objects. Replica placement does not
change a bound PVC's immutable `storageClassName`; this policy does not replace
or rebind claims. The existing default and class remain intact while references
exist. Owning manifests and chart claim templates must agree with each claim's
class; bound claims retain their immutable fields.

Once the reference gate opens, the reconciler:

1. Verifies both pool classes and rejects any unrelated default class.
2. Adds `persistence.createStorageClass: false` and `defaultClass: false` to the
   Fleet-owned HelmChartConfig. This overrides bootstrap HelmChart values.
3. Waits until Helm removes `longhorn-storageclass`, the ConfigMap from which
   Longhorn otherwise recreates the old class. No default changes occur first.
4. Marks `longhorn-workers` default, then rechecks PVC/PV references and deletes
   only the old StorageClass with UID and resource-version preconditions.

Each step resumes after a restart. A short interval with both classes marked
default avoids a gap; the existing namespace admission policy still routes CP
claims to `longhorn-control-plane`. No PVC, PV or Longhorn volume is deleted.
RBAC restricts class patching to `longhorn-workers`, class deletion to
`longhorn`, and HelmChartConfig patching to `kube-system/longhorn`.

Inspect the gate without changing resources:

```sh
kubectl logs -n longhorn-system deployment/longhorn-storage-pools --tail=10
kubectl get pvc -A -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,CLASS:.spec.storageClassName
kubectl get pv -o custom-columns=NAME:.metadata.name,CLASS:.spec.storageClassName
kubectl get storageclass
```

`storage-class-retirement-blocked` reports remaining claim and volume counts.
Remove `retireStorageClass` from `policy.yaml` through Git to disarm future
retirement steps. This does not undo completed steps. If the switch must be
rolled back after retirement, restore the old class through reviewed GitOps
changes, remove the HelmChartConfig persistence override and restore the
default annotation deliberately; reverting the code alone is not a rollback.

Three control-plane replicas occupy all three eligible nodes. A failed or
maintained control-plane node leaves two copies until it returns; a fourth
control-plane node is needed for replacement capacity within this pool. Hard
pool isolation deliberately prevents fallback onto workers. Keep maintenance
evacuation requirements in mind before draining these nodes.

The [maintenance policy](../longhorn-maintenance-policy/README.md) admits one
incoming rebuild per node. This limits new admission; it neither cancels an
existing copy nor caps a single copy's bandwidth.

## Validation and operations

```sh
python3 -m unittest discover -s kubernetes/projects/system/apps/longhorn-storage-pools -p 'test_*.py'
kubectl kustomize kubernetes/projects/system/apps/longhorn-storage-pools > /tmp/longhorn-storage-pools.yaml
kubectl apply --dry-run=server -f /tmp/longhorn-storage-pools.yaml
kubectl -n longhorn-system logs deployment/longhorn-storage-pools --tail=30
```

Validate PVC creation with server-side dry runs in a control-plane namespace,
a worker namespace and an explicit NFS class. Verify CEL type checking on the
two admission policies and confirm the resulting storageClassName. Do not use
real probe PVCs or create test data volumes.

`placement-status` reports misplaced replicas and share managers. The controller
maintains node tags, pool labels and volume selectors.

References: [storage tags](https://longhorn.io/docs/1.12.1/nodes-and-volumes/nodes/storage-tags/),
[storage-class parameters](https://longhorn.io/docs/1.12.1/references/storage-class-parameters/),
[volume controller](https://github.com/longhorn/longhorn-manager/blob/v1.12.1/controller/volume_controller.go).


## CSI reservation and recovery override

The Fleet-owned Longhorn HelmChartConfig also sets node CSI requests to
10m for the plugin and 5m each for registrar and liveness. Across eight nodes,
this reserves 160m rather than 560m CPU. Existing memory and CPU burst limits,
instance-manager guarantees, replicas and storage placement remain unchanged.
Bootstrap inventory declares the same CSI resources.

The override preserves failurePolicy=abort and serializes heavy snapshot tasks
at one per node. Chart valuesContent is separate from the existing storage-class
retirement gate; it does not authorize claim rebindings, replica deletion or
a default-class migration.
