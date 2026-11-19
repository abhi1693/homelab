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
- chart version: `8.3.102`
- NetBox version: `v4.7.4`
- image: `registry.home/ghcr.io/abhi1693/home-lab-netbox:4.7.4-e90b692`
- namespace: `netbox`
- ingress: enabled through Traefik
- web replicas: `1`
- worker replicas: `1`
- housekeeping: built-in daily system job; legacy CronJob disabled
- PostgreSQL operator: CloudNativePG
- PostgreSQL cluster chart: `cnpg/cluster`
- PostgreSQL cluster instances: `3`
- PostgreSQL write service: `postgresql-rw`, using the shared CNPG cluster
- queue/cache: shared Database project Valkey Sentinel service
- media persistence: retained NAS directory through NFS CSI
- required plugins:
  - `netboxlabs-netbox-custom-objects==0.7.0`
  - `netbox-topology-views==4.7.0`
  - `netbox-plugin-dns==1.7.3`
  - `netbox-lifecycle==1.1.10`
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
during drift checks.
Housekeeping is enabled. Finished Jobs are not retained; use centralized logs
for their output.

## Plugins

`netbox-metatype-importer` is disabled because its upstream maximum remains
4.6.99. Its data and encrypted credentials are retained. Re-enable it only after
a supported plugin release passes qualification against NetBox 4.7.

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
`registry.home/ghcr.io/abhi1693/home-lab-netbox:4.7.4-e90b692`
instead of installed at pod startup. Add plugin source archives to
`kubernetes/images/netbox/required-plugins.txt`; the `NetBox App Image` workflow
builds the image from the Harbor GHCR proxy copy of
`netbox-community/netbox:v4.7.4` and publishes a commit-SHA tag.

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

NetBox uses one web replica, one background worker, and no web PDB because a singleton
web service cannot preserve availability during voluntary disruption. Its
Services, ingress, PVC, PostgreSQL database and role, and Valkey data are
declaratively managed. PostgreSQL remains a shared three-instance CloudNativePG
cluster.


## Background worker and housekeeping

One RQ worker processes the native daily System Housekeeping job. It requests
50m CPU and 512Mi memory with a 1Gi memory limit. The legacy housekeeping
CronJob is disabled because NetBox 4.7 removed `manage.py housekeeping`.
Existing retention settings, PostgreSQL data, Valkey queues and credentials are
preserved. Confirm the native job completes and schedules its next daily run;
a Ready web Deployment alone does not prove background maintenance is working.

Maintenance flags and worker resources are projected from `values.yaml` into
`helmop.yaml` by `python3 scripts/render-training-netbox.py`. This makes them
part of Fleet's tracked Helm values/deployment identity as well as the referenced
ConfigMap. Run the renderer and `--check` after changing them; never hand-edit
the projection. Runtime credential Secret references remain unchanged.

The web container and its mkdir-only init each request 50m CPU, so the init
does not inflate the web pod's scheduler reservation.

If Fleet retains an old `WaitApplied` summary after the NetBox HelmOp and child
BundleDeployment are Ready with matching desired/applied IDs, verify the web
and worker pods, then refresh the HelmOp's `home-lab.io/status-reconcile-at`
metadata annotation through Git. Confirm parent readiness and preserved pod
identities after reconciliation, following the root operational workflow.
This is a workaround for stale parent reporting; the cause of a missed
transition remains unproven. Preserve workload and controller evidence when it
recurs, then diagnose Fleet before considering a controller upgrade.

## NetBox 4.7 maintenance cutover

The isolated ARM64 4.7.4 migration preserved identity/value hashes for all 378
checked business tables and passed authenticated UI/API checks. The production
cutover quiesces the singleton and housekeeping through Git, takes the fresh
[private NAS rollback point](../netbox-upgrade-backup/README.md), then restores
the web replica and housekeeping on the new immutable image.
The metatype importer will remain disabled until upstream supports NetBox 4.7;
its retained database data and credentials are not deleted.

The completed qualification Job and its disposable database are removed through
Git after evidence capture. The independent pre-upgrade NAS rollback point stays
retained; it is not the disposable qualification database.

## Production verification

Production runs 4.7.4 with zero restarts. All four enabled plugin navigation
pages and authenticated inventory APIs returned HTTP 200; device/IP counts
remained 36/26. Identity/value fingerprints remained identical for 377 business
tables. The administrator's account metadata and existing password were also
verified against the retained rollback dump: its PBKDF2 work factor increased
from 1,200,000 to 1,500,000 iterations. An existing browser session required a
fresh sign-in. Session keys and API-token peppers remained byte-identical.
The disabled importer's 8,358 records remain in its retained table.

Production has no invalid indexes or unvalidated constraints, and the required
trusted `ltree` extension is installed. The four-worker web process used about
1,256 MiB during the post-upgrade check, within its unchanged 2,304 MiB limit.
The separate RQ worker is now enabled for native NetBox 4.7 housekeeping.

The worker explicitly imports `core.jobs` before invoking NetBox's native `rqworker` command. The deployed 4.7.4 app configuration otherwise registers only the search-cache safety-net job at startup. This bootstrap restores native daily housekeeping registration and schedule recovery without changing retention, installing code at runtime, or using the removed management command.
