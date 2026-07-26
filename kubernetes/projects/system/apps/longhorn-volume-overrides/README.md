# Longhorn Volume Overrides

One-time Longhorn volume policy corrections that are safer to apply through
Fleet than by taking ownership of Longhorn's dynamic `Volume` resources.

This bundle records two finite, volume-ID-scoped corrections:

- disable data locality on build-cache volumes whose workloads do not need a
  same-node Longhorn replica;
- reduce the six CloudNativePG data/WAL volumes and three Valkey data volumes
  from three Longhorn replicas to one.

PostgreSQL and Valkey each maintain three application-level data copies on
separate nodes, so retaining three additional block replicas per PVC multiplies
storage and write traffic without adding an independent logical backup. The
database override reduces scheduled Longhorn capacity from 81Gi to 27Gi. The
global Longhorn default remains three replicas for other workloads.

Every target is pinned in RBAC and checked against its expected namespace and
PVC name before patching. The database Job runs as a post-upgrade Helm hook and
deletes itself after success so immutable Job fields cannot block later Fleet
reconciliations. If a database PVC is replaced, add its new Longhorn volume ID
and create a newly dated Job rather than broadening this role.

The finite kubectl Job requests `10m` CPU and `32Mi` memory and is capped at
`250m` CPU and `128Mi` memory.
