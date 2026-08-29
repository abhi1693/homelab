# NetBox

NetBox is the source of truth for home-network planning, IPAM, infrastructure
inventory, and rack/cabling documentation. UniFi Network client devices and
their derived interfaces, MACs, DHCP addresses, attachment cables, status, and
reservation-local DNS are intentionally excluded from imports.

The web UI is enabled on the internal LAN at `https://netbox.home`. Traefik
permanently redirects HTTP requests to HTTPS using a cert-manager certificate
from the trusted `home-local-ca` issuer. HTTPS is required for browser security
headers such as `Cross-Origin-Opener-Policy` to apply to this non-local origin.

Current choices:

- chart: `oci://ghcr.io/netbox-community/netbox-chart/netbox`
- chart version: `8.3.63`
- NetBox version: `v4.6.9`
- image: `registry.home/ghcr.io/abhi1693/home-lab-netbox:4.6.9-f3db127`
- namespace: `netbox`
- ingress: enabled through Traefik
- web replicas: `1`
- worker replicas: `1`
- housekeeping: enabled
- PostgreSQL operator: CloudNativePG
- PostgreSQL cluster chart: `cnpg/cluster`
- PostgreSQL cluster instances: `3`
- PostgreSQL write service: `postgresql-rw`, using the shared CNPG cluster
- queue/cache: shared Database project Valkey Sentinel service
- media persistence: retained NAS directory through NFS CSI
- required plugins:
  - `netbox-metatype-importer` from its NetBox 4.6 compatibility branch
  - `netboxlabs-netbox-custom-objects==0.6.1`
  - `netbox-topology-views==4.5.1`
  - `netbox-plugin-dns==1.5.11`
  - `netbox-lifecycle==1.1.9`
- registry pull Secret: namespace-scoped `harbor-registry`, backed by
  `robot-namespace-netbox`

## Required operator

The `cnpg-operator` Fleet app installs the cluster-wide CloudNativePG operator
in `cnpg-system`. The Database project `postgresql` HelmOp creates the shared
`postgresql` cluster in the `postgresql` namespace. NetBox connects to the
cluster write service at `postgresql-rw.postgresql.svc.cluster.local` using the
manually-managed `postgresql-app` secret in the `netbox` namespace.

## First login

The NetBox chart generates the initial admin password and API token into a
Kubernetes Secret. After Fleet reconciles both NetBox bundles, retrieve the
password with:

```sh
kubectl -n netbox get secret netbox-superuser \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

Then log in as `admin` at `https://netbox.home`.

## DNS

ExternalDNS publishes `netbox.home` from the Ingress. If the DNS record is not
created automatically after Fleet reconciles NetBox, add `netbox.home` to the
Traefik LoadBalancer IP `192.168.3.3`.

## Storage

Media persistence uses the `netbox-media-v2-nfs` PVC for device type elevation
images and other NetBox-managed media. NFS CSI provisions the retained NAS
directory below `netbox/netbox-media-v2-nfs`.
Reports and scripts persistence stay disabled until there is a concrete
Git-backed workflow for them.

The dynamic NFS claim is declared with its live controller-assigned
`volumeName`, and the HelmOp comparison policy ignores that immutable field
during drift checks. The detached former Longhorn media claim was retired after
its NFS copy was verified.

Housekeeping is enabled and retains neither successful nor failed Jobs because
retained housekeeping Pods can still be reported as consumers of the shared
media PVC after they finish. That stale consumer state can make Longhorn reject
a later CSI republish when no consumer Pod is Pending. Job output remains
available through centralized logs.

## Plugins

`netbox-metatype-importer` is enabled so device and module types can be imported
from the NetBox Device Type Library instead of seeded by hand.

`netbox-custom-objects`, `netbox-topology-views`, `netbox-plugin-dns`, and
`netbox-lifecycle` are enabled for workload catalog objects, cabling topology,
DNS source-of-truth records, and hardware lifecycle/procurement tracking.

Hardware Lifecycle records apply manufacturer EOS/EOL evidence to Device Types
or Module Types. Per-unit serial, asset tag, status, warranty, and support data
remain separate: use native Device identity/status fields and real lifecycle
Vendor, Support Contract, and Contract Assignment objects. Minimum production
commitments and undated vintage/legacy classifications belong in lifecycle
notices, not fabricated end-of-sale dates. Follow
[`docs/runbooks/netbox-hardware-lifecycle.md`](../../../../../docs/runbooks/netbox-hardware-lifecycle.md)
for evidence requirements and drift checks.

Required plugins are baked into
`registry.home/ghcr.io/abhi1693/home-lab-netbox:4.6.9-f3db127`
instead of installed at pod startup. Add plugin source archives to
`kubernetes/images/netbox/required-plugins.txt`; the `NetBox App Image` workflow
builds the image from the Harbor GHCR proxy copy of
`netbox-community/netbox:v4.6.9` and publishes a commit-SHA tag.

The image build enables the same plugin list temporarily and runs Django
`collectstatic` after installation. This is required for plugin-owned browser
assets; the build fails unless the topology plugin's `app.js`, `app.css`, and
`vendor.css` exist in NetBox's collected static root. See
[`kubernetes/images/netbox/README.md`](../../../../images/netbox/README.md).

`netbox-metatype-importer` is installed from the NetBox 4.6 compatibility
branch archive, pinned by commit in `required-plugins.txt` for repeatable
builds. The remaining PyPI plugins are pinned by version in the same file.

The GitHub token is intentionally not stored in Git. Create this optional Secret
when imports should call the GitHub GraphQL API:

```sh
kubectl -n netbox create secret generic netbox-metatype-importer-config \
  --from-literal=plugin.yaml='PLUGINS_CONFIG:
  netbox_metatype_importer:
    github_token: "<github-token>"'
```

## HA model

NetBox uses one web replica, one worker replica, and no PDB because a singleton
web service cannot preserve availability during voluntary disruption. Its
Services, ingress, PVC, PostgreSQL database and role, and Valkey data are
declaratively managed. PostgreSQL remains a shared three-instance CloudNativePG
cluster.
