# NetBox

NetBox is the source of truth for home-network planning, IPAM, device
inventory, and rack/cabling documentation.

The web UI is available at:

- `http://netbox.home`

Current choices:

- chart: `oci://ghcr.io/netbox-community/netbox-chart/netbox`
- chart version: `8.3.22`
- NetBox version: `v4.6.3`
- image: `registry.home/ghcr.io/abhi1693/home-lab-netbox:4.6.3-cf39083`
- namespace: `netbox`
- ingress class: `traefik`
- web replicas: `0` (paused)
- worker replicas: `0` (paused)
- housekeeping: disabled while NetBox is paused
- PostgreSQL operator: CloudNativePG
- PostgreSQL cluster chart: `cnpg/cluster`
- PostgreSQL cluster instances: `3`
- PostgreSQL write pooler: `postgresql-pooler-netbox-rw`, `0` instances while
  NetBox is paused
- queue/cache: shared Database project Valkey Sentinel service
- media persistence: retained NAS directory through NFS CSI
- required plugins:
  - `netbox-metatype-importer` from its NetBox 4.6 compatibility branch
  - `netbox-topology-views==4.5.1`
  - `netbox-plugin-dns==1.5.10`
  - `netbox-lifecycle==1.1.9`
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

Media persistence uses the `netbox-media-v2-nfs` PVC for device type elevation
images and other NetBox-managed media. NFS CSI provisions the retained NAS
directory below `netbox/netbox-media-v2-nfs`.
Reports and scripts persistence stay disabled until there is a concrete
Git-backed workflow for them.

The dynamic NFS claim is declared with its live controller-assigned
`volumeName`, and the HelmOp comparison policy ignores that immutable field
during drift checks. The detached former Longhorn media claim was retired after
its NFS copy was verified while NetBox remained paused.

Housekeeping is disabled while NetBox is paused. When enabled, the CronJob
retains neither successful nor failed Jobs. Retained housekeeping pods are
still reported as consumers of the shared media PVC after they finish, which
can make Longhorn reject a later CSI republish when no consumer pod is Pending.
Job output remains available through centralized logs.

## Plugins

`netbox-metatype-importer` is enabled so device and module types can be imported
from the NetBox Device Type Library instead of seeded by hand.

`netbox-topology-views`, `netbox-plugin-dns`, and `netbox-lifecycle` are
enabled for cabling topology, DNS source-of-truth records, and hardware
lifecycle/procurement tracking.

Required plugins are baked into
`registry.home/ghcr.io/abhi1693/home-lab-netbox:4.6.3-cf39083` instead of
installed at pod startup. Add plugin source archives to
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

NetBox is currently paused with zero web, worker, and PgBouncer replicas, and
housekeeping disabled. Its PVC, PostgreSQL database, role, and Valkey data are
retained for a later restart. When active, the web Deployment uses pod
anti-affinity and topology spread constraints, the worker is single-replica,
and the write pool normally uses two PgBouncer instances. PostgreSQL itself
remains a shared three-instance CloudNativePG cluster.
