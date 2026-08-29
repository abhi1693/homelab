---
title: K3s Cluster to NetBox Drift Detection and Manual Reconciliation
---

# K3s Cluster to NetBox Drift Detection and Manual Reconciliation

- Service: K3s, NetBox, Ansible, Cilium, MetalLB, and UniFi Network
- Cluster: `home-k3s`
- Change path: Git/Fleet for cluster state; NetBox MCP for documentation state
- Normal mode: read-only discovery followed by reviewed NetBox writes

## Meaning

NetBox documents the stable physical and logical shape of the home K3s cluster.
It does not replace the Ansible inventory, Git-managed cluster configuration, or
live Kubernetes status. Drift exists when those sources disagree about a field
for which one of them is authoritative, or when NetBox no longer represents a
confirmed physical fact.

Do not import Pods, ReplicaSets, ephemeral Pod IPs, individual ClusterIPs,
completed Jobs, Secrets, runtime metrics, or Network clients into NetBox. The
infrastructure boundary covers the cluster, its physical nodes and cabling,
stable node addresses, control-plane services, cluster address spaces, and
load-balancer pools. The workload boundary is a separate curated service
catalog: durable applications, controller workloads, persistent stores, stable
endpoints, and named dependencies from project app-local `catalog.yaml` files
and Ansible-owned `infrastructure/netbox/platform-catalogs/*.yaml` files.

## Impact

Undetected drift can make maintenance and recovery decisions use the wrong node
role, address, serial, chassis slot, switch port, Kubernetes version, CNI, or
cluster CIDR. A NetBox discrepancy is not proof that the live cluster should be
changed. Determine the authoritative source before proposing a correction.

## Source-of-truth boundaries

| Data | Authority | NetBox representation |
| --- | --- | --- |
| Ansible host aliases, node IPs, server/worker membership, K3s version, API VIP, and Cilium configuration | Git under `infrastructure/ansible/` | Device custom fields, primary IPs, roles, and cluster custom fields |
| MetalLB pools and fixed ingress IP | Git under `kubernetes/projects/system/apps/metallb-config/` | Marked-utilized prefixes and VIP addresses |
| Admitted node names, readiness, runtime K3s version, OS, architecture, and observed InternalIP | Live Kubernetes API | Compared with Devices; readiness is not stored as inventory state |
| Hardware serial and Ethernet MAC | The physical node, corroborated by current host or controller telemetry | Device serial and the primary MAC on `eth0` |
| USB peripheral identity and host-port attachment | The physical node's current USB topology and sysfs identity | Peripheral Device, compatible console endpoints, and a typed Cable |
| Chassis, bay placement, lifecycle, and intended cabling | NetBox, checked against the physical rack and UniFi attachment evidence | Parent Device, Device Bays, child Devices, Interfaces, and Cables |
| Current switch attachment, speed, port state, and PoE delivery | Read-only UniFi telemetry | Evidence for cable and PoE drift; transient link state and draw are not copied into node status |
| Rack power topology, connector type, and outlet attachment | Equipment nameplates plus operator-confirmed physical attachment | Power Ports, Power Outlets, component templates, and typed power Cables; never infer an outlet mapping |
| Application purpose, owner, lifecycle, criticality, data classification, source path, and declared relationships | Git app-local and platform `catalog.yaml` files | Custom `Application`, `Kubernetes Workload`, `Persistent Store`, `Endpoint`, and `Dependency` objects |
| Workload existence, desired replicas, running images, endpoint readiness, and PVC capacity | Live Kubernetes API | Compared with the catalog; only bounded observations and `last_observed_at` are written to NetBox |

If Git and runtime disagree, stop the NetBox write phase. Resolve or formally
accept the cluster drift first. If NetBox and a complete, corroborated
observation disagree, update NetBox through MCP after review.

## Expected baseline

The `home-k3s` NetBox cluster has one K3s cluster, three control-plane Devices,
five worker Devices, and these stable network objects:

| Object | Expected value |
| --- | --- |
| K3s version | `v1.35.8+k3s1` |
| Platform | `Debian 13 (Trixie)`, ARM64 hardware |
| API VIP | `192.168.3.2/24` |
| Pod prefix | `10.42.0.0/16`, marked utilized |
| Service prefix | `10.43.0.0/16`, marked utilized |
| CNI | `Cilium` |
| Traefik VIP | `192.168.3.3/24` |
| MetalLB application pool | `192.168.3.16/29`, representing `.16-.23`, marked utilized |
| Chassis | `Home - Raspberry Pi Cluster`, 12 Device Bays |
| Occupancy | Bays 01-08 occupied; Bays 09-12 empty |
| Node PoE | Every `k8s-rpi1`-`k8s-rpi8` `eth0` is `PD`, IEEE `802.3at (Type 2)`; reciprocal Lab Switch ports 1-8 are `PSE` Type 2; node USB-C `PSU` ports remain uncabled because the Pis are PoE-only |
| Raspberry Pi 5 lifecycle | Hardware Lifecycle record 1 retains the conflicting official minimum manufacturing statements of January 2036 and January 2038 as a notice; EOS/EOL dates remain empty because no end-of-sale date was announced |
| Rack UPS | `ups-home-rack`, APC `BR1500G-IN`, serial `0B2428G26638` |
| UPS monitoring link | `k8s-rpi1` `USB-2` to `ups-home-rack` `USB data port`; USB ID `051d:0002`, Linux topology `1-2` |
| UPS power components | Type M `AC Input`; four logical battery-backed and two surge-only IS 1293 6A outlets, all mapped to the input |
| Rack PDU | `pdu-home-rack`, MX `MX-620`, eight 250V ITA Multistandard outlets mapped to its Type D `Input` |
| UPS-to-PDU power link | `ups-home-rack` logical `Battery-Backed Outlet 1` to `pdu-home-rack` `Input`, connected by a 1.5m black Power cable |
| PDU outlet map | O1 Management switch; O2 Core switch; O3 UNAS Pro 4; O4 CLOUDPLATE T7-N; O5 UDM Pro; O6 Lab switch; O7 formerly WD My Cloud EX4100 NAS, now disconnected pending decommission; O8 Tripleplay ISP-provided ONT |
| Pending power evidence | The physical UPS rear position for logical battery outlet 1, the MX-620 nameplate current, the upstream breaker/feed, and the O8 ONT manufacturer, model, serial, and power connector remain unconfirmed |

The MetalLB application pool is a prefix because the controller-derived UniFi
DHCP range already spans `192.168.3.6-254`. NetBox prevents overlapping IP
ranges. Do not alter the controller-owned DHCP range to make the MetalLB range
fit.

| Device | Ansible host | Role | Primary IP | Serial | Ethernet MAC | Switch port |
| --- | --- | --- | --- | --- | --- | --- |
| `k8s-rpi1` | `server-1` | K3s Control Plane | `192.168.3.243/24` | `3063d94522a172bf` | `88:A2:9E:4A:E7:13` | Lab Switch Port 1 |
| `k8s-rpi2` | `server-2` | K3s Control Plane | `192.168.3.191/24` | `37b31947ab552021` | `88:A2:9E:4A:E3:A6` | Lab Switch Port 2 |
| `k8s-rpi3` | `server-3` | K3s Control Plane | `192.168.3.108/24` | `4ff16d9f41c19bc9` | `88:A2:9E:4A:E2:C3` | Lab Switch Port 3 |
| `k8s-rpi4` | `worker-1` | K3s Worker | `192.168.3.135/24` | `56228b6895712df4` | `88:A2:9E:CF:F0:D3` | Lab Switch Port 4 |
| `k8s-rpi5` | `worker-2` | K3s Worker | `192.168.3.197/24` | `7930b0b1d5f001d2` | `98:FE:54:22:11:51` | Lab Switch Port 5 |
| `k8s-rpi6` | `worker-3` | K3s Worker | `192.168.3.71/24` | `62bd6dbb6739d435` | `98:FE:54:22:12:5C` | Lab Switch Port 6 |
| `k8s-rpi7` | `worker-4` | K3s Worker | `192.168.3.179/24` | `c8c596a76e73efdf` | `98:FE:54:22:13:58` | Lab Switch Port 7 |
| `k8s-rpi8` | `worker-5` | K3s Worker | `192.168.3.8/24` | `cfc778dbffa5998e` | `98:FE:54:22:12:1D` | Lab Switch Port 8 |

An intentional topology or inventory change must update this baseline in the
same repository change that updates the affected desired state or procedure.

## Guardrails

- Keep all Kubernetes and host changes in Git and let Fleet or Ansible apply
  them. This runbook does not authorize a manual cluster mutation.
- Use NetBox MCP for every NetBox read and write. Do not use direct REST,
  Django, SQL, or `kubectl exec` as a bypass.
- Administrative MCP writes are enabled in the deployment. They still require
  the authenticated NetBox user's permission. Treat custom fields, roles,
  platforms, tags, and object templates as schema: change them only in a
  separately reviewed reconciliation plan.
- Treat the Custom Objects definitions as schema. Reconcile application
  instances routinely, but change object types or fields only when the Git
  catalog schema, `infrastructure/netbox/workload-catalog-netbox-schema.yaml`,
  and this runbook change in the same review.
- `REQUIRE_DELETE_CONFIRMATION=true` remains mandatory. Routine drift handling
  must not delete Devices, IP addresses, prefixes, interfaces, cables, or
  schema objects.
- Never interpret an unreachable node, incomplete controller response, empty
  result page, or absent live attachment as evidence for deletion.
- Cap NetBox pagination at 500 results. Match exact, non-empty serials first.
  Reject ambiguous matches instead of guessing.
- Do not copy credentials, tokens, raw controller payloads, or Kubernetes
  Secrets into the repository, NetBox descriptions, or a drift report.

## Prerequisites

- A working read-only Kubernetes context.
- The home Ansible inventory and repository checkout at the revision being
  compared.
- Read-only UniFi access when validating switch attachment.
- NetBox MCP access using `X-NetBox-URL: https://netbox.home/` and a NetBox v2
  token with only the permissions needed for the reviewed operation.
- A change reference such as `CHG-YYYY-MM-DD-K3S-NETBOX` for any accepted write.

## Diagnosis: collect Git and live cluster state

Start from a clean understanding of the repository revision. Unrelated local
changes are not part of the drift baseline.

```sh
git status --short --branch
git rev-parse HEAD

ansible-inventory \
  -i infrastructure/ansible/inventories/home/hosts.yml \
  --graph

kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,CONTROL_PLANE:.metadata.labels.node-role\.kubernetes\.io/control-plane,INTERNAL_IP:.status.addresses[?(@.type=="InternalIP")].address,VERSION:.status.nodeInfo.kubeletVersion,OS:.status.nodeInfo.osImage,ARCH:.status.nodeInfo.architecture'

kubectl -n kube-system get daemonset cilium \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="cilium-agent")].image}{"\n"}'

kubectl get service kubernetes \
  -o jsonpath='{.spec.clusterIP}{"\n"}'

kubectl -n metallb-system get ipaddresspool ingress-services app-services \
  -o yaml
```

Confirm the pinned values directly in:

- `infrastructure/ansible/inventories/home/hosts.yml`;
- `infrastructure/ansible/inventories/home/group_vars/all.yml`;
- `infrastructure/ansible/inventories/home/group_vars/k3s_servers.yml`;
- `kubernetes/projects/system/apps/metallb-config/address-pools.yaml`.

Validate the Git-owned workload catalog before querying runtime or NetBox:

```sh
python scripts/validate-workload-catalog.py
```

For every `catalog.yaml`, read only the declared controller objects, endpoints,
and persistent stores. Query the declared `apiGroup`, `kind`, `namespace`, and
`name` directly; do not discover and import all namespaced resources. Record
the observed generation, desired/ready replicas where applicable, container
images from the controller's long-running `containers` list, endpoint readiness,
and requested/bound capacity. Do not mix init-container images into that field;
they are transient setup details and are not normalized with the existing
projection. The catalog remains valid when a Pod name or Pod IP changes.

Collect hardware identity from every reachable node without modifying it:

```sh
ansible k3s_nodes \
  -i infrastructure/ansible/inventories/home/hosts.yml \
  -m ansible.builtin.command \
  -a 'cat /proc/device-tree/serial-number'

ansible k3s_nodes \
  -i infrastructure/ansible/inventories/home/hosts.yml \
  -m ansible.builtin.command \
  -a 'ip -json link show eth0'

ansible server-1 \
  -i infrastructure/ansible/inventories/home/hosts.yml \
  -m ansible.builtin.shell \
  -a 'for d in /sys/bus/usb/devices/*; do test -r "$d/idVendor" || continue; test "$(cat "$d/idVendor"):$(cat "$d/idProduct")" = 051d:0002 || continue; printf "topology=%s serial=%s product=%s\n" "${d##*/}" "$(sed "s/[[:space:]]*$//" "$d/serial")" "$(cat "$d/product")"; done'
```

Normalize serials by removing NUL and surrounding whitespace, and normalize
MACs to uppercase colon notation before comparing. Record unreachable nodes as
`observation_incomplete`; do not substitute old telemetry.

When checking cabling, collect a fresh read-only UniFi snapshot and correlate
node name, primary Ethernet MAC, switch identity, port number, link state, and
speed. Follow the stricter evidence and client-exclusion rules in the
[UniFi-to-NetBox drift runbook](networking/unifi-netbox-drift-reconciliation.md).

## Diagnosis: query NetBox through MCP

Resolve IDs from names on every run; IDs in old reports are not configuration.
Use bounded `netbox_get_objects` or `netbox_get_all_objects` calls for:

1. `virtualization.cluster` named `home-k3s`, including its custom fields;
2. `dcim.device` filtered by that cluster;
3. `dcim.devicebay` on `Home - Raspberry Pi Cluster`;
4. `dcim.interface` for each cluster Device, including primary MAC, cable,
   `poe_mode`, and `poe_type`; verify the Raspberry Pi 5 `eth0` interface
   template carries the same PoE values;
5. `ipam.ipaddress` for node IPs and the two stable VIPs;
6. `ipam.prefix` tagged `k3s`;
7. `ipam.service` attached to the three control-plane Devices.
8. `dcim.device` named `ups-home-rack`, matched by its exact non-empty serial;
9. the APC `BR1500G-IN` `dcim.devicetype` and its `USB data port`
   `dcim.consoleserverporttemplate`;
10. the `dcim.cable` path from `k8s-rpi1` `USB-2` to the UPS data port;
11. the UPS and PDU `dcim.powerport`, `dcim.poweroutlet`,
    `dcim.powerporttemplate`, and `dcim.poweroutlettemplate` objects;
12. the Power cable from the UPS battery-backed outlet to the MX-620 input;
13. the uncabled Raspberry Pi USB-C `PSU` ports, corroborated against the PoE
    PSE/PD interface path rather than treated as missing power cables;
14. the five Custom Objects types and their instances for every app-local and
   platform `catalog.yaml`.

Resolve dynamic Custom Object object types from `netbox_list_object_types` by
their stable endpoint slugs (`application`, `kubernetes-workload`,
`persistent-store`, `endpoint`, and `dependency`). Do not hardcode generated
model names such as `table1model`, because they are local implementation IDs.

Expected structural counts are:

| Type | Count |
| --- | ---: |
| Cluster Devices | 8 |
| Control-plane Devices | 3 |
| Worker Devices | 5 |
| Chassis Device Bays | 12 |
| Occupied Device Bays | 8 |
| Node `eth0` interfaces with primary MACs and cables | 8 |
| K3s control-plane services | 3 |
| K3s-related prefixes | 3 |
| Stable K3s/ingress VIPs | 2 |

Fetch all pages before comparing. A partial page, tool error, or count above the
configured cap makes the scan incomplete.

## Diagnosis: match identities and classify drift

For each expected node:

1. Match one exact, non-empty hardware serial to one NetBox Device.
2. Confirm `ansible_inventory_name`, device name, primary IP, and Ethernet MAC.
3. Confirm the server/worker role against Git and the control-plane label.
4. Confirm the child Device is installed in the expected chassis Device Bay.
5. Confirm `eth0` is cabled to the observed Lab Switch port.

Use the device name only as a secondary key. A duplicate serial or MAC is a
hard conflict. Do not update either candidate until the physical identity is
resolved.

Classify every difference:

| Class | Meaning | Action |
| --- | --- | --- |
| `git_runtime_drift` | Git desired state and live cluster disagree | Stop NetBox writes; repair through Git/Ansible/Fleet or accept the new desired state first |
| `netbox_inventory_drift` | Stable node identity, role, platform, address, or bay differs after corroboration | Propose an MCP update with before/after values |
| `netbox_network_drift` | VIP, prefix, primary IP, MAC, service, or cable differs | Require both the authoritative config and current endpoint evidence before updating |
| `netbox_power_drift` | A power component, connector, UPS/PDU relationship, PoE-only source, or confirmed outlet attachment differs | Require equipment identity plus operator-confirmed physical endpoints; never assign an outlet from device proximity or naming |
| `schema_drift` | Required role, platform, tag, custom field, or template is absent or incompatible | Separate administrative review; do not create schema as a side effect of a routine scan |
| `observation_incomplete` | A source is unavailable, partial, stale, or ambiguous | Report it and make no destructive or identity-changing update |
| `unexpected_object` | NetBox has an extra object or Kubernetes has an unplanned node | Investigate lifecycle intent; never delete automatically |
| `catalog_source_drift` | A catalog key, Git source path, or declared relationship is missing or inconsistent | Fix and validate Git first; do not conceal it with a NetBox-only update |
| `catalog_runtime_drift` | A declared controller, replica target, image family, endpoint, or persistent store differs from live Kubernetes | Repair through Git/Fleet or explicitly accept the runtime change before updating NetBox observations |
| `netbox_catalog_drift` | Validated Git catalog and accepted runtime facts disagree with a Custom Object instance | Propose the narrowest MCP create or update; never alter cluster desired state from NetBox |

The drift report must include the class, stable key, source values, NetBox
object ID, confidence, proposed action, and evidence. `zero drift` is valid only
when every expected source was complete and every comparison passed.

## Mitigation: reconcile accepted NetBox drift

1. Review the complete report and resolve every `git_runtime_drift`, duplicate
   identity, and incomplete source before changing stable identity or cabling.
2. Re-read each target NetBox object immediately before writing. Confirm its ID
   and current value still match the report.
3. Use the narrowest NetBox MCP update with the change reference in
   `changelog_message`. Do not replace whole objects when a partial update is
   sufficient.
4. Preserve NetBox-owned site, chassis, bay, lifecycle, ownership, and
   descriptive fields unless they are explicitly part of the reviewed change.
5. For a cable change, prove both endpoints, confirm the target interfaces are
   free, and retain the previous cable ID and endpoints in the change record.
6. For a power cable, distinguish battery-backed from surge-only UPS outlets,
   keep PDU outlets mapped to their input, and require the physical PDU outlet
   number before connecting a downstream device. Never create PDU-to-Pi power
   cables when the Pi is powered through its PoE interface.
7. Update the cluster's `last_observed_at` custom field only after a complete
   scan has reconciled successfully. It means all required sources were checked,
   not merely that the runbook started.

Ordinary drift reconciliation updates existing objects. Creating a node is an
inventory onboarding operation: add it to Git, verify hardware identity and
placement, then create its Device, interfaces, MAC, IP, bay assignment, cable,
and cluster membership as one reviewed change.

For workload catalog reconciliation, process applications in dependency order:

1. Validate every catalog and prove each declared Git source path exists.
2. Read the declared live controllers, stores, and endpoints. Stop that
   application on missing or ambiguous runtime state.
3. Upsert the `Application` by its unique catalog name.
4. Upsert its `Kubernetes Workload` and `Persistent Store` instances by their
   deterministic keys.
5. Upsert stable `Endpoint` and `Dependency` instances by their catalog keys.
6. Re-read the complete application graph through MCP and compare it to Git.
7. Set `last_observed_at` only after the application has no unresolved source,
   runtime, or NetBox catalog drift.

Never create a catalog object from runtime discovery alone. A workload must
first have a reviewed `catalog.yaml`; this prevents transient controllers and
operator-generated resources from silently becoming inventory.

Treat a declared operator custom resource as the durable workload identity when
it owns generated controllers. The PostgreSQL catalog therefore records the
CloudNativePG `Cluster` and eight `Pooler` resources, not their generated Pods
or Deployments. Do not separately import Longhorn engine-image DaemonSets,
Longhorn RecurringJob CronJobs, Rancher-generated cleanup CronJobs, or per-user
Wardn MCP runtime Deployments. Investigate a new unmatched controller, but add
it only after assigning a stable Git-owned application and source path.

## Verification

Repeat the full collection from Git, Kubernetes, hosts, UniFi, and NetBox. Then
prove all of the following:

- exactly eight live nodes match exactly eight NetBox cluster Devices;
- the role split is three control-plane and five workers;
- every Device has one unique serial, expected inventory alias, primary IP,
  `eth0` primary MAC, chassis bay, and switch cable;
- the UPS exposes one Type M input, four battery-backed outlets, and two
  surge-only outlets, with all six outlets mapped to the UPS input;
- `pdu-home-rack` exposes one Type D input and exactly eight ITA Multistandard
  outlets mapped to it;
- the PDU input traces through a connected Power cable to a battery-backed UPS
  outlet;
- PDU O1-O6 trace through connected Power cables to the documented device power
  inputs, O7 remains uncabled for the disconnected WD My Cloud EX4100 pending
  decommission, and O8 is marked connected to the Tripleplay ISP-provided ONT
  until its exact device identity and power connector are documented;
- every Raspberry Pi USB-C `PSU` port remains uncabled and each node's active
  power path is represented by reciprocal PoE PSE/PD metadata;
- all live nodes report the Git-pinned K3s version, Debian 13, and ARM64;
- Cilium, API VIP, Pod CIDR, Service CIDR, Traefik VIP, and MetalLB pool match
  Git and the NetBox cluster/IPAM objects;
- Bays 09-12 remain empty and there are no module placeholders for the chassis;
- the three control-plane Devices expose documented TCP ports 6443 and 9345;
- every MCP write has a successful receipt and corresponding NetBox changelog;
- no unresolved or unclassified difference remains.

For the workload catalog, also prove:

- every directory matching `kubernetes/projects/*/apps/*` has exactly one
  disposition: an app-local catalog or an entry in
  `infrastructure/netbox/workload-catalog-exclusions.yaml`;
- exactly 57 `Application` objects match the 57 Git catalogs: 51 project apps
  plus the six Ansible-owned platform catalogs; all 34 other project app
  directories have a reviewed component, support, or retired classification;
- the projection contains 136 workload, 5 persistent-store, 9 endpoint, and 18
  dependency objects;
- every workload, store, endpoint, and dependency key is unique and matches its
  catalog entry;
- each declared live controller exists and its desired replica count matches;
- retained storage class and capacity match Git and bound PVC or CNPG state;
- no Pods, ReplicaSets, Pod IPs, Secrets, completed Jobs, or runtime metrics
  were created as Custom Objects; and
- all 57 application graphs have no unresolved application or workload drift,
  and the detailed NetBox, UPS Monitoring, Home Assistant, PostgreSQL, and
  Jellyfin graphs also have no unresolved store, endpoint, or dependency drift.

For MCP deployment changes, also verify the Git/Fleet state and runtime guard:

```sh
kubectl -n netbox get deployment netbox-mcp-server \
  -o jsonpath='{.metadata.generation} {.status.observedGeneration} {.status.readyReplicas}/{.status.replicas}{"\n"}'

kubectl -n netbox get deployment netbox-mcp-server \
  -o jsonpath='{range .spec.template.spec.containers[0].env[?(@.name=="ALLOW_ADMINISTRATIVE_WRITES")]}{.name}={.value}{"\n"}{end}'
```

## Rollback

For an incorrect NetBox update, read the object's changelog and restore only the
reviewed prior fields through MCP with a new change reference. Re-run the full
verification afterward. A deleted object cannot be restored with the same ID,
which is why routine drift reconciliation does not delete objects.

For an incorrect Git change, revert it in Git and let the normal Ansible or
Fleet owner reconcile it. Do not patch the live cluster to make it match
NetBox.

For an incorrect workload projection, restore the prior Custom Object fields
through MCP from the NetBox changelog. Do not delete a catalog type or bulk
delete instances during routine rollback. If a catalog is intentionally
retired, change its Git lifecycle first, reconcile that state, and handle any
later deletion as a separate confirmed administrative change.

## Escalation

Stop and request operator review when:

- Git and live cluster membership or network ranges disagree;
- more than one object claims a serial, MAC, IP, bay, or cable endpoint;
- a node is unreachable or its hardware identity cannot be read;
- UniFi topology is stale or contradicts the physical rack;
- schema creation, deletion, or a change to the source-of-truth boundary is
  needed;
- a catalog references a missing source, unmodeled dependency, mutable secret,
  or operator-generated resource that cannot be represented durably;
- the proposed update would remove a Device, IPAM object, interface, or cable.

## References

- [NetBox infrastructure workspace](../../infrastructure/netbox/README.md)
- [NetBox MCP server](../../kubernetes/projects/home-automation/apps/netbox-mcp-server/README.md)
- [K3s node maintenance](k3s-node-maintenance.md)
- [UniFi infrastructure to NetBox drift reconciliation](networking/unifi-netbox-drift-reconciliation.md)
