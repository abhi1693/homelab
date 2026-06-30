# NetBox

NetBox is the source of truth for home-network planning, IPAM, device
inventory, and rack/cabling documentation.

The web UI is available at:

- `http://netbox.home`

Current choices:

- chart: `oci://ghcr.io/netbox-community/netbox-chart/netbox`
- chart version: `8.3.22`
- NetBox version: `v4.6.3`
- image: `registry.home/home-lab/netbox:4.6.3-20260628`
- namespace: `netbox`
- ingress class: `traefik`
- web replicas: `1`
- worker replicas: `1`
- PostgreSQL operator: CloudNativePG
- PostgreSQL cluster chart: `cnpg/cluster`
- PostgreSQL cluster instances: `3`
- PostgreSQL write pooler: `postgresql-pooler-netbox-rw`
- queue/cache: shared Database project Valkey Sentinel service
- media persistence: enabled on Longhorn
- required plugins:
  - `netbox-metatype-importer` from its NetBox 4.6 compatibility branch
  - `netbox-topology-views==4.5.1`
  - `netbox-plugin-dns==1.5.10`
  - `netbox-lifecycle==1.1.9`
  - `netbox-bgp==0.19.0`
- registry pull Secret: namespace-scoped `harbor-registry`, backed by
  `robot-namespace-netbox`

## Required operator

The `cnpg-operator` Fleet app installs the cluster-wide CloudNativePG operator
in `cnpg-system`. The Database project `postgresql` HelmOp creates the shared
`postgresql` cluster in the `postgresql` namespace. NetBox connects only to its
app-specific write PgBouncer pooler at
`postgresql-pooler-netbox-rw.postgresql.svc.cluster.local` using the
manually-managed `postgresql-app` secret in the `netbox` namespace.

## First login

The NetBox chart generates the initial admin password and API token into a
Kubernetes Secret. After Fleet reconciles both NetBox bundles, retrieve the
password with:

```sh
kubectl -n netbox get secret netbox-superuser \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

Then log in as `admin` at `http://netbox.home`.

## DNS

ExternalDNS should publish `netbox.home` from the Ingress. If the DNS record is
not created automatically, add `netbox.home` to the Traefik LoadBalancer IP
`192.168.3.3`.

## Storage

Media persistence is enabled on Longhorn for device type elevation images and
other NetBox-managed media. The chart mounts the existing `netbox-media-v2` PVC so
Fleet does not try to replace immutable bound PVC fields during Helm syncs.
Reports and scripts persistence stay disabled until there is a concrete
Git-backed workflow for them.

The active NetBox media PVC is also declared under `extraDeploy` with its live
`volumeName` because Fleet compares dynamically provisioned PVCs after
Kubernetes binds them. Without the bound volume name in Git, Fleet tries to
replace it with an empty value and Kubernetes rejects the immutable spec change.
If the PVC is intentionally recreated or migrated, update the pinned
`volumeName` in `values.yaml`.

## Plugins

`netbox-metatype-importer` is enabled so device and module types can be imported
from the NetBox Device Type Library instead of seeded by hand.

`netbox-topology-views`, `netbox-plugin-dns`, `netbox-lifecycle`, and
`netbox-bgp` are enabled for cabling topology, DNS source-of-truth records,
hardware lifecycle/procurement tracking, and BGP documentation.

Required plugins are baked into `registry.home/home-lab/netbox:4.6.3-20260628` instead
of installed at pod startup. Add plugin source archives to
`kubernetes/images/netbox/required-plugins.txt`; the `NetBox App Image` workflow
builds the image from the Harbor GHCR proxy copy of
`netbox-community/netbox:v4.6.3` and publishes the `netbox`, date-stamped
semver, and SHA tags.

`netbox-metatype-importer` is installed from the NetBox 4.6 compatibility
branch archive, pinned by commit in `required-plugins.txt` for repeatable
builds. PyPI plugins are pinned by version in the same file.

The GitHub token is intentionally not stored in Git. Create this optional Secret
when imports should call the GitHub GraphQL API:

```sh
kubectl -n netbox create secret generic netbox-metatype-importer-config \
  --from-literal=plugin.yaml='PLUGINS_CONFIG:
  netbox_metatype_importer:
    github_token: "<github-token>"'
```

## HA model

The web Deployment uses pod anti-affinity, topology spread constraints, and a
PodDisruptionBudget so one web replica can be disrupted without taking NetBox
offline. The worker is intentionally single-replica. PostgreSQL uses three
CloudNativePG instances with synchronous replication and a two-instance
PgBouncer write pool. Queue and cache traffic uses logical DB indexes 1 and 2
on the shared Valkey Sentinel service in the Database project.
