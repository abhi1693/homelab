---
title: UniFi Infrastructure to NetBox Drift Detection and Manual Reconciliation
---

# UniFi Infrastructure to NetBox Drift Detection and Manual Reconciliation

- Service: UniFi Network and NetBox
- Type: maintenance
- Owner: Home Lab operator
- Last verified: 2026-08-26 by OpenAI Codex
- Expected duration: 20-60 minutes for detection; reconciliation depends on the
  number of reviewed changes

## Meaning

Use this runbook to compare a point-in-time UniFi Network infrastructure API
snapshot with NetBox and, after review, reconcile accepted controller
observations through the NetBox MCP server.

There is no scheduled UniFi-to-NetBox reconciler. Drift is therefore expected
between manual runs. This procedure does not reinstall that service and does
not write to UniFi. All controller requests in this runbook are `GET` requests;
all accepted inventory changes go through the NetBox MCP server.

This workflow is infrastructure-only. UniFi clients are intentionally excluded
from NetBox inventory and must not be collected, compared, imported, updated,
or recreated by this procedure.

Drift means one of the following:

- a UniFi infrastructure device, WLAN, static DNS record, port observation, or
  transceiver differs from its NetBox representation;
- a controller object has no unambiguous NetBox match;
- NetBox contains a controller-owned value that is absent from a complete
  current UniFi snapshot;
- more than one NetBox object claims the same stable identity.

An unresolved or intentionally skipped item is still drift. Do not report
`zero drift` merely because every safe update was applied.

## Impact

Unreviewed drift can leave infrastructure device status, static DNS records,
WLAN metadata, port telemetry, or transceiver inventory stale. Incorrect
reconciliation can be worse: it can merge different physical devices,
overwrite intentional rack or cable data, or delete a specialized camera or
infrastructure record.

The ordinary procedure has no UniFi blast radius. NetBox writes affect only
the explicitly named objects. Deletions and duplicate merges have a larger
blast radius and require the additional gates in this runbook.

## Authority and safety rules

Treat ownership per field, not per whole object:

| Data | Authority | Reconciliation rule |
| --- | --- | --- |
| UniFi infrastructure serial, model, firmware observation | UniFi | Match infrastructure devices by exact non-empty serial before updating telemetry. |
| Infrastructure online state, uplink, RF and port counters | UniFi | Update only after a complete snapshot and an unambiguous infrastructure interface match. |
| UniFi controller object IDs | UniFi | Store in the applicable `unifi_*_id` custom field; an ID must map to at most one NetBox object. |
| Device name, asset tag, role, site, rack, position, cable, tenant and ownership | NetBox | Preserve unless a separate reviewed inventory change explicitly says otherwise. |
| Hardware distributor, reseller, and their contact details | NetBox | Preserve native contact groups, contacts, roles, priorities, and device assignments; never infer an individual's title or seniority. |
| Physical device serial | Manufacturer or asset record | Never invent, normalize across devices, or replace a non-empty conflicting serial. |
| UniFi static DNS | UniFi | Match by stable controller ID; fall back to exact zone/name/type/value only for adoption. Client reservation-local DNS is excluded. |
| NetBox manual DNS (`managed=true` or without a UniFi ID) | NetBox | Never alter or delete through this procedure. |

Hard stops:

- Do not call the UniFi `rest/user` or `stat/sta` client endpoints for this
  workflow. Do not persist their payloads even temporarily.
- Never create or update a NetBox device with role `client`, device type `UniFi
  Client`, tag `unifi-client`, or client identity fields such as
  `unifi_client_ids`, `unifi_identity_key`, or `unifi_client_details`.
- Never import client interfaces, MAC addresses, DHCP IP addresses, attachment
  cables, status observations, or reservation-local DNS. A DNS ownership ID
  beginning with `client:` is client data and is out of scope.
- If a proposed plan includes any client object or client-derived value, stop
  before all writes, discard that part of the plan, and report the policy
  violation. The same boundary applies to any future automated importer or
  replacement reconciler.
- Preserve specialized device roles such as `camera`, all rack placement,
  cables, inventory ownership, and manually maintained custom fields.
- Never copy WLAN passphrases, private keys, API keys, or raw controller
  payloads into NetBox, logs, tickets, or this repository.
- Keep supplier phone numbers and other personal contact details in NetBox; do
  not duplicate them in this repository or a controller snapshot.
- Do not use direct NetBox REST, Django, SQL, or `kubectl exec` for the
  reconciliation. Use the NetBox MCP server so permissions, bounds, delete
  confirmation, and receipts remain in force.
- Administrative MCP writes are disabled. If a required custom field, tag,
  role, device type, or credential is missing, stop and handle that schema or
  access change separately through its normal reviewed workflow.

## Prerequisites

Required access and tools:

- LAN or VPN reachability to `https://192.168.3.1`.
- A current UniFi API key with read access to the `default` Network site.
- `zsh`, `curl`, and `jq` on the operator workstation.
- An MCP client connected to `https://mcp.netbox.home/mcp` with:
  - `X-NetBox-URL: https://netbox.home/`;
  - a write-enabled NetBox v2 token supplied in the MCP HTTP
    authorization configuration, never in a tool argument;
  - view permission for all compared object types;
  - add/change/delete permission only for objects approved for reconciliation.
- A change reference for NetBox changelog messages, for example
  `CHG-2026-08-26-UNIFI-NETBOX`.

Before starting:

1. Confirm nobody else is changing the affected NetBox objects.
2. Decide whether this is detection-only or an authorized reconciliation.
3. Keep the MCP server's administrative-write gate disabled.
4. Use a secure change record for the final drift summary and write receipts.
   Do not attach the raw controller snapshots.

## Diagnosis: collect a secret-free UniFi snapshot

The commands below keep the API key out of shell history and process arguments.
They store only curated fields in a private temporary directory, preferably on
tmpfs, and remove it on every normal or interrupted exit.

```zsh
umask 077
drift_parent=/dev/shm
[[ -d "$drift_parent" && -w "$drift_parent" ]] || drift_parent=/tmp
drift_dir=$(mktemp -d "${drift_parent}/unifi-netbox-drift.XXXXXX")

cleanup_unifi_netbox_drift() {
  unset UNIFI_API_KEY
  if [[ -n "${drift_dir:-}" && -d "$drift_dir" ]]; then
    case "$drift_dir" in
      /dev/shm/unifi-netbox-drift.*|/tmp/unifi-netbox-drift.*)
        find "$drift_dir" -type f -delete
        find "$drift_dir" -depth -type d -empty -delete
        ;;
      *)
        print -u2 "Refusing cleanup of unexpected path: $drift_dir"
        ;;
    esac
  fi
}
trap cleanup_unifi_netbox_drift EXIT HUP INT TERM

read -rs 'UNIFI_API_KEY?UniFi API key: '
printf '\n'
export UNIFI_API_KEY

unifi_get() {
  local endpoint=$1
  {
    printf 'header = "X-API-Key: %s"\n' "$UNIFI_API_KEY"
    printf 'header = "Accept: application/json"\n'
  } | curl --silent --show-error --fail-with-body \
    --connect-timeout 5 --max-time 30 --retry 2 \
    --insecure --config - \
    --url "https://192.168.3.1${endpoint}"
}
```

`--insecure` is limited here to the fixed local UDM address because the current
controller certificate is not trusted by the workstation. Prefer `--cacert`
with the controller CA when one becomes available. Never reuse this exception
for an internet host.

Collect the three required infrastructure datasets. The filters deliberately
exclude clients, WLAN passphrases, and unneeded raw controller fields.

```zsh
unifi_get '/proxy/network/api/s/default/stat/device' |
  jq -e '
    def rows: if type == "array" then .
      elif (.data | type) == "array" then .data
      elif (.results | type) == "array" then .results
      else error("missing result array") end;
    rows | map({
      _id, name, model, type, serial, mac, version,
      port_table: [(.port_table // [])[] | {
        name, port_idx, up, speed, full_duplex, media,
        op_mode, is_uplink, lag_member, lag_idx, aggregated_by,
        aggregate_num_ports, aggregate_members, lacp_state,
        poe_mode, poe_power, rx_bytes, tx_bytes, rx_packets,
        tx_packets, rx_errors, tx_errors, rx_dropped, tx_dropped,
        stp_state, sfp_vendor, sfp_part, sfp_rev, sfp_serial,
        sfp_compliance, sfp_temperature, sfp_voltage, sfp_current,
        sfp_txpower, sfp_rxpower, sfp_rx_los, sfp_tx_fault
      }],
      radio_table_stats: [(.radio_table_stats // [])[] | {
        name, radio, state, channel, bw, tx_power, cu_total,
        cu_self_rx, cu_self_tx, num_sta, satisfaction,
        tx_packets, tx_retries, tx_retries_pct
      }]
    })' > "$drift_dir/devices.json"

unifi_get '/proxy/network/api/s/default/rest/wlanconf' |
  jq -e '
    def rows: if type == "array" then .
      elif (.data | type) == "array" then .data
      elif (.results | type) == "array" then .results
      else error("missing result array") end;
    rows | map({
      _id, name, enabled, security, wpa_mode, pmf_mode,
      wpa3_support, is_guest, wlan_band, wlan_bands,
      hide_ssid, bss_transition, fast_roaming_enabled, uapsd_enabled
    })' > "$drift_dir/wlans.json"

unifi_get '/proxy/network/v2/api/site/default/static-dns/' |
  jq -e '
    def rows: if type == "array" then .
      elif (.data | type) == "array" then .data
      elif (.results | type) == "array" then .results
      else error("missing result array") end;
    rows | map({
      _id: (._id // .id), key: (.key // .name),
      record_type: (.record_type // .type), value,
      enabled, ttl
    })' > "$drift_dir/static-dns.json"
```

Expected output is no terminal output and three non-empty, mode-`600` JSON
files. A `curl` HTTP error, a `jq` error, or an empty required result is a stop,
not evidence that objects should be removed from NetBox.

Run completeness and uniqueness gates:

```zsh
jq -e 'length >= 3 and all(.[]; (.serial // "") != "")' \
  "$drift_dir/devices.json" >/dev/null
jq -e 'all(group_by(.serial)[]; length == 1)' \
  "$drift_dir/devices.json" >/dev/null

printf 'devices=%s wlans=%s static_dns=%s\n' \
  "$(jq length "$drift_dir/devices.json")" \
  "$(jq length "$drift_dir/wlans.json")" \
  "$(jq length "$drift_dir/static-dns.json")"
```

The historical completeness floor is 3 infrastructure devices. Update this
runbook after an intentional infrastructure inventory reduction rather than
bypassing the check ad hoc.

## Diagnosis: query NetBox through MCP

MCP calls below are tool invocations, not shell commands. Keep their results in
the active MCP session; do not export a second raw inventory snapshot.

First confirm the object registry and permission-aware schemas:

```text
netbox_list_object_types(include_plugins=true)

netbox_get_object_schema(object_type="dcim.device", include_choices=true)
netbox_get_object_schema(object_type="dcim.interface", include_choices=true)
netbox_get_object_schema(object_type="wireless.wirelesslan", include_choices=true)
netbox_get_object_schema(object_type="netbox_dns.record", include_choices=true)
netbox_get_object_schema(object_type="dcim.inventoryitem", include_choices=true)
netbox_get_object_schema(object_type="tenancy.contact", include_choices=true)
netbox_get_object_schema(object_type="tenancy.contactassignment", include_choices=true)
```

Expected result: all seven types exist and the intended operation is available.
If a write operation is absent, the MCP token lacks permission; do not bypass
MCP. If `netbox_dns.record` is absent, plugin discovery or the DNS plugin is not
available and DNS reconciliation must be skipped and reported.

Collect bounded NetBox views:

```text
netbox_get_all_objects(
  object_type="dcim.device",
  fields=["id", "name", "status", "serial", "asset_tag", "site", "role",
          "device_type", "platform", "rack", "position", "primary_ip4",
          "tags", "custom_fields"],
  ordering="name",
  max_results=500
)

netbox_get_all_objects(
  object_type="dcim.interface",
  fields=["id", "name", "device", "type", "enabled", "mark_connected",
          "cable", "primary_mac_address", "tags", "custom_fields"],
  ordering=["device", "name"],
  max_results=500
)

netbox_get_all_objects(
  object_type="wireless.wirelesslan",
  fields=["id", "ssid", "status", "auth_type", "auth_cipher",
          "vlan", "group", "tenant", "custom_fields"],
  ordering="ssid",
  max_results=100
)

netbox_get_all_objects(
  object_type="netbox_dns.zone",
  fields=["id", "name", "status"],
  ordering="name",
  max_results=100
)

netbox_get_all_objects(
  object_type="netbox_dns.record",
  fields=["id", "zone", "name", "fqdn", "type", "value", "status",
          "ttl", "managed", "description", "comments", "custom_fields"],
  ordering=["zone", "name", "type", "value"],
  max_results=500
)

netbox_get_all_objects(
  object_type="dcim.inventoryitem",
  fields=["id", "device", "name", "label", "manufacturer", "part_id",
          "serial", "discovered", "description", "custom_fields"],
  ordering=["device", "name"],
  max_results=500
)

netbox_get_all_objects(
  object_type="tenancy.contact",
  fields=["id", "name", "groups", "title", "phone", "description"],
  ordering="name",
  max_results=100
)

netbox_get_all_objects(
  object_type="tenancy.contactassignment",
  fields=["id", "object_type", "object_id", "object", "contact", "role",
          "priority"],
  max_results=500
)
```

Every response must have `truncated=false`. If it is truncated, continue from
`next_offset` or narrow the query. Never reconcile against an incomplete MCP
page.

The current identity and telemetry custom fields are:

- device: `unifi_device_id`, `unifi_mac`, `unifi_site_id`, `unifi_host_id`,
  `unifi_product_line`, `unifi_firmware_status`, and `unifi_source_data`;
- interface: `unifi_device_id`, `unifi_mac`, `unifi_first_seen`,
  `unifi_last_seen`, `unifi_network`, `unifi_uplink`, and
  `unifi_connection`;
- WLAN: `unifi_wlan_id`, `unifi_security`, and `unifi_radio_policy`;
- DNS record: `unifi_dns_record_id`;
- inventory item: `unifi_inventory_data`.

Before writing any `custom_fields` object, read the current object and merge
the intended `unifi_*` values into the complete existing map. Sending a partial
`custom_fields` map may erase unrelated values. Apply the same preserve-and-
merge rule to `tags`.

Every Device whose manufacturer is `Ubiquiti` must have exactly one primary
`Distributor Sales` assignment to a contact in the `Savex Technologies` group
and exactly one secondary `Reseller` assignment to a contact in the
`Uniek Cloud Solutions` group. The reseller role describes the confirmed
company-to-hardware procurement relationship; it does not establish the
individual's job title. Keep an unconfirmed title empty.

## Diagnosis: build the identity map and drift report

### Infrastructure devices

For each UniFi `stat/device` row:

1. Require a non-empty `serial`.
2. Match exactly one NetBox `dcim.device.serial`, case-insensitively after
   trimming whitespace.
3. If zero matches exist, report `infrastructure_unmatched`; do not create a
   rack device automatically.
4. If more than one match exists, report `duplicate_serial` and stop all writes
   for those devices.
5. After a unique serial match, compare model and controller ID as corroborating
   evidence. Preserve the NetBox name, role, asset tag, site, rack, position,
   cables, tenant, platform, and device type.

### Home room locations

The `Home` site has these active top-level room locations and stable device
assignments:

| Location | Expected devices |
| --- | --- |
| `Bedroom` | `Bedroom Room - U6+` |
| `Master Bedroom` | `Master Bedroom - U6+`; `Master Bedroom - G4 Instant` |
| `Guest Room` | `Guest Room - U6+` |
| `Dining Room` | `Dining Room - U6 Enterprise` |
| `Kitchen` | `Kitchen - G5 Turret Ultra`; `Kitchen Balcony - G5 Flex` |
| `Office Room` | `Office Desk - USW Flex 2.5G 5` |
| `Living Room` | `Living Room - G5 Turret Ultra` |

Do not infer a room for a rack-mounted device. `Outside - G5 Turret Ultra`
remains at the `Home` site without a Location until an outside location is
explicitly approved.

### Excluded client data

Do not build a client identity map. Ignore controller client rows if they appear
in an unexpected response, and do not compare them with NetBox. A valid drift
plan contains no device with role `client`, no device type `UniFi Client`, no
`unifi-client` tag, no client-derived interface/MAC/IP/cable, and no DNS record
whose `unifi_dns_record_id` begins with `client:`.

This exclusion also applies to useful or infrastructure-adjacent hosts such as
Kubernetes nodes, storage appliances, laptops, phones, IoT devices, and Protect
storage when UniFi reports them as Network clients. Model such assets through
their authoritative inventory workflow, not from the UniFi client API.

### WLANs

Match by `unifi_wlan_id`; use exact SSID only to adopt an existing WLAN whose ID
field is empty. Compare enabled/status, authentication type/cipher, and curated
security/radio policy. Do not copy a PSK. Do not automatically create a missing
WLAN because VLAN, group, tenant, and scope require an inventory decision.

### DNS

Choose the longest NetBox zone suffix matching the FQDN. Match an existing
record by `unifi_dns_record_id`; exact zone/name/type/value is adoption evidence
only when no other record claims the controller ID. Never change or delete a
record with `managed=true` or no UniFi ownership marker. Skip any record whose
ownership ID begins with `client:`; reservation-local DNS is not imported.

### Ports and transceivers

Update port/radio telemetry only after matching the parent device by serial and
the interface by exact name. Preserve existing cable endpoints and never clear
`mark_connected` for a cabled interface. Creating or changing a cable is a
separately reviewed inventory change and requires corroborating evidence from
both endpoints, such as matching LACP membership and an identical non-empty DAC
serial.

Model an observed LACP bundle only when both devices are unambiguously matched,
the controller reports the same `lag_idx` on every member, each member has
`lag_member=true`, the aggregate member lists agree with the physical ports,
and the current `lacp_state` reports every member active. After operator review,
create one `type=lag` interface per device, assign each physical interface to
its local LAG, and keep one cable per physical member. Never attach a cable to
the logical LAG interface. Report partial or one-sided evidence as unresolved
drift instead of inferring a bundle from interface names alone.

Match transceivers by exact, non-empty `sfp_serial`. Report a serial observed at
multiple endpoints and choose the NetBox owner only after reviewing the actual
physical link. Preserve manually maintained inventory fields not supplied by
UniFi.

### Report format

Produce a review table before any write:

| Class | Stable key | UniFi value | NetBox object ID/value | Confidence | Proposed action | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| `firmware` | infrastructure serial | 7.2.123 | device 17/7.2.120 | high | update | unique serial |
| `dns` | static DNS ID | service.home/A | record 42/value differs | high | update | unmanaged UniFi-owned record |

The report must include:

- total infrastructure devices, WLANs, and static DNS records;
- accepted updates, creates, deletes, duplicate serial conflicts, incomplete
  infrastructure mappings, and unmodeled DNS zones;
- an explicit `client objects proposed=0` policy check;
- an explicit statement that the snapshot passed or failed completeness gates.

## Mitigation: reconcile accepted NetBox drift

### Pre-write gate

For every accepted change:

1. Call `netbox_get_object_by_id` immediately before writing.
2. Confirm the ID, stable key, current relationships, full custom field map,
   tags, and the proposed before/after values still match the drift report.
3. Add a changelog message containing the change reference and stable source
   key, for example `CHG-2026-08-26-UNIFI-NETBOX: reconcile infrastructure
   serial ABC123456`.
4. Apply dependency changes one object at a time. Use bulk operations only for
   independent, same-type updates after several single-object writes have been
   verified. Auto-chunked bulk writes are not atomic.
5. Save each MCP receipt and the minimal before/after field set in the secure
   change record. Do not save the API key or raw snapshots.

### Update an existing object

Use partial updates and include only reviewed fields, except that
`custom_fields` and `tags` must contain their complete merged values:

```text
netbox_update_object(
  object_type="dcim.device",
  object_id=123,
  data={
    "custom_fields": {
      "unifi_device_id": "0123456789abcdef01234567",
      "unifi_firmware_status": "UP_TO_DATE",
      "existing_unrelated_field": "preserved-value"
    }
  },
  changelog_message="CHG-2026-08-26-UNIFI-NETBOX: reviewed infrastructure reconciliation"
)
```

Replace `123`, the source ID, and the complete custom field map with the values
from the immediately preceding read. Expected result: one updated object or a
stable update receipt. On `409`, validation error, or `412`, stop and re-read;
do not retry with weaker matching.

### Reconcile dependent objects in this order

1. Existing infrastructure device identity and telemetry metadata.
2. Existing infrastructure interfaces and their port/radio telemetry.
3. Existing WLAN metadata.
4. UniFi-owned static DNS records.
5. Serialized infrastructure inventory items.
6. Separately approved infrastructure cable or stale-object changes.

For stale DNS, delete only when the record has `unifi_dns_record_id`, has
`managed=false`, and its ID is absent from a complete current controller
snapshot. Use `confirm=true` and retain the receipt.

## Verification

1. Repeat all three curated UniFi `GET` requests into the same protected
   temporary directory.
2. Re-run the bounded MCP reads for every changed type.
3. Rebuild the infrastructure identity indexes and drift table from scratch.
4. Confirm:
   - every accepted high-confidence drift is gone;
   - every skipped or ambiguous item remains explicitly listed with its reason;
   - no stable infrastructure serial, controller ID, WLAN ID, DNS ID, or
     transceiver serial maps to multiple NetBox objects;
   - the second plan proposes zero client devices, interfaces, MAC addresses,
     DHCP IPs, attachment cables, status updates, or reservation-local DNS;
   - specialized roles, cables, rack placement, and unrelated custom fields are
     unchanged;
   - every Ubiquiti Device has the required primary distributor and secondary
     reseller contact assignments, with no inferred personal title;
   - the seven Home room Locations and their device assignments match the
     baseline above, while rack hardware and the outside camera remain
     unchanged;
   - every write has a successful MCP receipt and matching NetBox changelog;
   - a second reconciliation plan proposes zero creates, updates, or deletes
     for already accepted objects.
5. Let the shell exit normally and confirm the cleanup trap removed the
   snapshot directory and unset `UNIFI_API_KEY`:

```zsh
saved_drift_dir=$drift_dir
cleanup_unifi_netbox_drift
[[ ! -e "$saved_drift_dir" ]]
[[ -z "${UNIFI_API_KEY:-}" ]]
trap - EXIT HUP INT TERM
```

Expected result: both tests exit with status zero. Only the redacted drift
summary, reviewed before/after fields, change reference, and MCP receipts should
remain in the approved change record.

## Rollback

UniFi needs no rollback because this runbook performs no controller writes.

For an incorrect NetBox update, use the pre-change values captured in the
change record and call `netbox_update_object` on the same object. Restore the
complete previous `custom_fields` and `tags` maps, then re-read the object and
its relationships.

For objects created during this run, delete them in reverse dependency order:
static DNS records, inventory items, infrastructure interfaces, then the
infrastructure device. Every delete requires `confirm=true` and an exact ID
from the create receipt.

A deletion cannot be restored with the same NetBox ID. If a duplicate or stale
object was deleted incorrectly, stop routine work. Recreate it from the secure
pre-change export, rebind relationships explicitly, and verify changelogs and
cables. This is why deletion is isolated behind a separate approval gate.

## Troubleshooting

| Symptom | Likely cause | Resolution |
| --- | --- | --- |
| UniFi returns `401` or `403` | Missing, expired, or under-privileged API key | Stop, unset the key, obtain a current read-only key, and repeat the snapshot. Never fall back to credentials embedded in Home Assistant or Git. |
| UniFi returns `404` | Site slug or controller API path changed | Confirm the Network application and `default` site in the controller. Update and re-verify this runbook before reconciling. |
| Infrastructure device count falls below the floor | Partial API response, wrong site, or controller outage | Make no writes. Repeat after the controller is healthy. |
| MCP reports an unknown object type | Plugin discovery or the required plugin is unavailable | Skip that object class and repair MCP/plugin availability through GitOps. |
| MCP operation is unavailable or returns `403` | Token lacks the applicable NetBox permission | Stop. Use a correctly scoped, expiring token; do not enable administrative writes or bypass MCP. |
| MCP returns `409` or a uniqueness error | Duplicate infrastructure serial, asset tag, or controller ID | Re-read all claimants, mark an identity conflict, and stop the affected write. |
| MCP returns `412` | Object changed after the read | Re-read, regenerate the proposal, and obtain review again. |
| A bulk receipt has successful and failed chunks | Auto-chunked writes are not atomic | Record successful receipts, stop, re-read all submitted IDs, and reconcile only the remaining verified drift. |
| WLAN response appears to contain passphrases | The curation filter was changed or bypassed | Stop, delete the temporary snapshot with the cleanup function, rotate exposed credentials if they left the workstation, and restore the curated filter. |
| A plan contains role `client`, tag `unifi-client`, or a `client:` DNS ID | Client data entered the infrastructure workflow | Stop before all writes, remove the client-derived rows from the plan, and verify that neither `rest/user` nor `stat/sta` was queried. |
| DNS FQDN matches no zone | NetBox does not model the authoritative suffix | Report `dns_unmodeled_zone`; do not create a zone through this runbook. |

## Escalation

Stop and request owner review when:

- any stable key maps to multiple objects;
- a proposed change touches a camera, rack device, cable, or manually maintained
  inventory without the required independent evidence;
- the controller snapshot is incomplete twice in succession;
- any client-derived object is proposed, or any infrastructure serial would be
  created, merged, or deleted;
- NetBox and UniFi disagree on a physical serial or asset tag;
- MCP cannot perform the reviewed operation with its normal safety gates.

Provide the redacted drift table, completeness counts, affected NetBox IDs,
stable keys, proposed changes, and MCP error/receipt. Do not provide API keys,
tokens, WLAN secrets, or raw snapshots.

## References

- [NetBox deployment](../../../kubernetes/projects/home-automation/apps/netbox/README.md)
- [NetBox MCP server](../../../kubernetes/projects/home-automation/apps/netbox-mcp-server/README.md)
- [UniFi LAN integration](../../../infrastructure/network/unifi/README.md)
- [Runbook format](../README.md)
