# NetBox Infrastructure Workspace

This directory is reserved for infrastructure source-of-truth workflows related
to NetBox. Import and reconciliation helpers must exclude UniFi Network client
devices and all client-derived interfaces, MACs, DHCP addresses, attachment
cables, status observations, and reservation-local DNS.

NetBox documents the stable physical and logical K3s inventory: the
`home-k3s` cluster, eight Raspberry Pi Devices installed in the cluster chassis,
node interfaces and addresses, switch cabling, cluster CIDRs, stable VIPs, and
the MetalLB application pool, and a curated workload service catalog. Git
remains authoritative for Ansible inventory, cluster desired state, and the
technical workload catalog; NetBox owns the human-facing catalog and stable
relationships; live Kubernetes is authoritative for observed runtime state.

The live NetBox application is declared under:

```text
kubernetes/projects/home-automation/apps/netbox/
```

That app bundle owns the Kubernetes deployment, Helm values, storage, ingress,
plugins, and database wiring. This infrastructure directory exists for artifacts
that are not themselves Kubernetes app desired state, including:

- `workload-catalog.schema.json`, the validation contract for app-local
  `catalog.yaml` files;
- `workload-catalog-netbox-schema.yaml`, the reviewed Custom Objects shape that
  the NetBox projection must match;
- `workload-catalog-exclusions.yaml`, the reviewed disposition of every project
  app directory that is not an independent application;
- `platform-catalogs/`, the durable controllers owned by Ansible bootstrap
  roles rather than Fleet project app directories;
- generated inventory or IPAM reports;
- source-of-truth migration notes;
- scripts that reconcile infrastructure data into NetBox.

Keep Kubernetes manifests with the NetBox app bundle. Keep reusable
source-of-truth tooling here.

## Workload catalog

Each durable app owns a `catalog.yaml` beside its Fleet manifests. The catalog
includes all 85 project app directories: 51 are independent applications and
34 are explicitly classified as component, support, or retired directories in
`workload-catalog-exclusions.yaml`. Six additional catalogs under
`platform-catalogs/` cover the Ansible-owned Cilium, cert-manager, Fleet, K3s
system services, Longhorn, and Rancher platforms. The resulting 57 applications
currently declare 136 durable controller workloads. Detailed catalogs can additionally record retained
stores, stable endpoints, and named dependencies without duplicating Pods,
ReplicaSets, Pod IPs, completed Jobs, Secrets, health history, or runtime
metrics.

Runtime expansion remains intentionally bounded. A declared CloudNativePG
`Pooler` represents its generated Deployment; Longhorn engine-image and
RecurringJob controllers, Rancher-generated cleanup jobs, and per-user Wardn
MCP runtime Deployments are not separate applications. A drift scan compares
declared identities and must not import those generated controllers merely
because they are currently visible.

Validate all entries with:

```sh
python -m pip install --requirement .github/requirements/workload-catalog.txt
python scripts/validate-workload-catalog.py
```

The validator enforces schema, app paths, referenced source files, globally
unique keys, deterministic workload and store identities, complete project-app
directory coverage, and an app-local `.fleetignore` entry so
catalog metadata is never rendered as a Kubernetes resource. A newly added app
directory fails validation until it has a catalog or a reviewed classification.
The
`Workload catalog validation` workflow runs the same check on relevant changes.
Renovate tracks the pinned validation dependencies and every PyPI plugin pin in
`kubernetes/images/netbox/required-plugins.txt`.

The NetBox Custom Objects plugin projects the Git catalog into five types:
`Application`, `Kubernetes Workload`, `Persistent Store`, `Endpoint`, and
`Dependency`. A reconciler must compare Git and runtime before using NetBox MCP
to update that projection. NetBox must never become an alternate deployment
controller.

The current projection contains 57 Applications and 136 controller workloads.
The five original detailed application graphs also contain five logical
persistent stores, nine stable endpoints, and eighteen dependency edges; those
relationship types are extended only when a durable Git-backed fact exists.
The live-safe field names `service_owner`, `container_images`, and
`endpoint_url` intentionally avoid collisions with fields inherited from the
NetBox model and REST serializer.

Use the
[K3s-to-NetBox drift runbook](../../docs/runbooks/k3s-netbox-drift-reconciliation.md)
to compare Git, runtime, hardware, controller telemetry, and NetBox without
turning transient Kubernetes resources into inventory. Use the
[UniFi-to-NetBox drift runbook](../../docs/runbooks/networking/unifi-netbox-drift-reconciliation.md)
for the stricter infrastructure-only controller workflow.
