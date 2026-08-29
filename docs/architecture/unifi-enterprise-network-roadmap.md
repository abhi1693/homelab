# UniFi Enterprise Network Roadmap

## Status

Proposed. This document records the 2026-08-18 read-only UniFi audit, target
architecture, execution order, validation gates, and rollback boundaries. It
does not authorize live controller, switch, access point, camera, storage,
cluster, or firewall changes by itself.

- **Last updated:** 2026-08-24
- **Last live refresh:** 2026-08-18 22:56 IST
- **Observability research refresh:** 2026-08-24
- **Baseline controller:** UniFi Network 10.5.67 on a UDM Pro
- **Planning owner:** network operator
- **Change ownership:** UniFi for network and Protect policy, Git and Rancher
  Fleet for Kubernetes dependencies, and repository documentation for the
  cross-system contract
- **Implementation rule:** re-read live state before every phase because this
  baseline will drift as devices arrive and clients reconnect

No API key, password, private key, public WAN address, device MAC address, or
camera credential is recorded in this document.

## Executive Summary

The network is operational, but it does not yet have enterprise-style failure
containment. Four routed networks exist, 65 clients are known, seven UniFi
devices are adopted, and the live ExternalDNS integration is healthy. The
largest risks are a switch port disabled by BPDU Guard after a loop event,
non-deterministic spanning-tree root selection, several historical physical
link errors, broad inter-zone firewall allows, no management/camera/storage/
guest separation, detect-only IDS alerts that have not been triaged, an
inactive site-to-site VPN, and local-only controller backups.

The arriving USW-Pro-Max-24-PoE, UNAS Pro 4, UNVR-G2, and 10 GbE desktop switch
should be integrated around the existing USW Pro Aggregation as a star-shaped
core. The core becomes the deterministic RSTP root. The current 1 GbE access
switch remains for K3s and legacy endpoints; the Pro Max becomes the primary
PoE and multigigabit access switch; the UNAS, UNVR, desktop switch, and UDM use
direct core uplinks.

Logical migration should preserve the current K3s, trusted Wi-Fi, and IoT
subnets initially, then introduce dedicated management, camera, storage, and
guest networks. Firewall policy moves to default deny between zones with
explicit application exceptions. Wi-Fi client isolation is applied by device
class, not globally. RF tuning and bandwidth limits follow physical repair and
measurement rather than being used to hide cabling or congestion problems.

Implementation is intentionally phased. Credential containment and physical
stability come first; VLANs and firewall policy follow; camera and storage
migrations happen only after the new switching foundation has soaked.

## Goals

- Make the USW Pro Aggregation the deterministic Layer 2 core and RSTP root.
- Remove loops, marginal links, implicit trunks, and unused enabled ports.
- Separate infrastructure management, servers, trusted clients, IoT, cameras,
  storage, guests, and VPN clients by explicit trust boundary.
- Default-deny new cross-zone connections and allow only documented flows.
- Preserve required K3s, ExternalDNS, Home Assistant, Music Assistant, Cast,
  Protect, NFS/SMB, and local DNS behavior.
- Apply Wi-Fi and wired client isolation according to actual peer-to-peer
  requirements.
- Limit guest and IoT Internet bandwidth without constraining cameras, local
  storage, or trusted LAN transfers.
- Replace the interim UDM Pro Protect workload with the UNVR-G2 without attempting to
  move the Network application off the UDM Pro.
- Integrate the UNAS Pro 4, desktop 10 GbE switch, desktop, and WD EX4100 with
  explicit VLAN, LACP, backup, and recovery contracts.
- Turn IDS, flow, syslog, WAN, VPN, backup, and device-health data into
  actionable monitoring.
- Keep implementation reversible, observable, documented, and free of
  plaintext secrets.

## Non-Goals

- Treating a single UDM, aggregation switch, UNVR, or UNAS as highly available.
- Enabling every available UniFi feature without a measured need.
- Changing every subnet while also changing the physical topology.
- Opening broad inter-zone access for convenience.
- Enabling LAG, jumbo frames, fast roaming, IPS blocking, or Smart Queues
  before their prerequisites are tested.
- Exposing qBittorrent WebUI/API, Traefik, Protect administration, storage
  administration, or UniFi administration directly to the Internet.
- Assuming hidden SSIDs, VLANs, or Wi-Fi client isolation are authentication or
  authorization boundaries by themselves.
- Retiring the old Protect console before historical footage and the new UNVR
  have passed their acceptance windows.

## Baseline Provenance and Limitations

The baseline was collected read-only on 2026-08-18 and refreshed at 22:56 IST
after another U6+ was adopted. The controller remained at 192.168.3.1, and the
supplied temporary Network API key authenticated successfully.
The official Integration API was used where it exposed the required data. The
Network application was newer than the supplied 10.4.57 documentation, and the
official clients endpoint only returned connected clients, so read-only legacy
controller endpoints were also used for offline clients, detailed port state,
activity, and security history.

The live Kubernetes Secret contains a different site-scoped key that continued
to authenticate during the audit. ExternalDNS was healthy, its Fleet bundle
was ready, its pod containers were ready, and its logs reported that DNS
records were already current. The temporary owner-level key is therefore not
needed for continuity and must not become the long-term workload credential.

The Network key did not authenticate to the Protect Integration API during the
initial audit. During the later refresh, the Protect console still appeared as
an online Network client, but the audit host could not reach its management
address across the inactive site path. Protect retention, disks, microphone
policy, detections, alarm rules, users, roles, remote access, stream encryption,
and camera-level settings remain a mandatory separate audit from a reachable
home-side source using a Protect-specific key before the UNVR migration.

Counts and counters below are observations, not desired-state declarations.
Cumulative interface counters did not increase during the initial 12-second
resample or the post-adoption 10-second resample, so they identify links that
need investigation rather than proving an active fault at those moments.

### Post-adoption refresh delta

- One new U6+ was discovered, adopted, and upgraded from 6.6.71 to 6.7.54. It
  is now the Master Bedroom AP on Lab port 10 at 1 Gb/s.
- The former Master Bedroom U6+ was renamed/relocated to Guest Room and is now
  on Lab port 11 at 1 Gb/s.
- The U6 Enterprise was renamed from Office/Living Room to Dining Room and is
  now on Lab port 7 at 1 Gb/s.
- The Lab switch upgraded from 7.4.1 to 7.5.10. Its reboot/reset means current
  per-port lifetime counters cannot be compared directly with the earlier
  7.4.1 counters.
- No device was pending adoption, offline, unsupported, upgradeable, or marked
  end-of-life at the refresh.
- Logical policy counts were unchanged: four networks, two SSIDs, seven zones,
  95 firewall policies, 53 DNS policies, no ACL/LAG/MC-LAG/stack/traffic list,
  and one inactive site-to-site VPN.
- ExternalDNS remained 1/1 available with both containers ready; all three
  Fleet child BundleDeployments were ready, and a fresh log line reported that
  all records were already up to date.

## Current Inventory

### Adopted UniFi infrastructure

All seven adopted devices were online at the refresh. None was pending adoption,
offline, marked end-of-life, or offering an upgrade.

| Role | Device | Software | Audit note |
| --- | --- | --- | --- |
| Gateway and Network console | UDM Pro | UniFi OS 5.1.26; Network 10.5.67 | Network remains here after the UNVR migration. |
| Core | USW Pro Aggregation | 7.4.1 | 28 10 GbE SFP+ and four 25 GbE SFP28 ports; target RSTP root. |
| Access and PoE | USW-24-PoE, Lab | 7.5.10 | 73.11 W of 95 W PoE in use; several physical/STP findings. |
| Access point | U6 Enterprise, Dining Room | 6.8.2 | Lab port 7 at 1 GbE; capable of 2.5 GbE. |
| Access point | U6+, Bedroom Room | 6.7.54 | Lab port 1 at 1 GbE. |
| Access point | U6+, Guest Room | 6.7.54 | Relocated/renamed existing AP; Lab port 11 at 1 GbE. |
| Access point | U6+, Master Bedroom | 6.7.54 | Newly adopted AP; Lab port 10 at 1 GbE. |

Four additional Raspberry Pi 5 systems of the existing node model are planned
for connection on 2026-08-19. Treat them as staged K3s/server endpoints until
their identities, power method, firmware, operating-system baseline, and
intended cluster roles are verified. If all four join K3s, the cluster grows
from four to eight Raspberry Pi nodes; update capacity, failure-domain, quorum,
scheduling, storage, monitoring, and maintenance assumptions accordingly.

### Port coverage

All 69 gateway/switch ports and all four access-point uplinks were inspected.

| Device | Total | Up | Down | Additional observation |
| --- | ---: | ---: | ---: | --- |
| Lab USW-24-PoE | 26 | 16 | 10 | 12 PoE-active ports; port 14 remains down after BPDU Guard. |
| USW Pro Aggregation | 32 | 2 | 30 | UDM and Lab switch are the only active links. |
| UDM Pro | 11 | 3 | 8 | Gateway and console are healthy. |

Unused ports are generally still enabled. Profiles and labels are often
default or automatic, and there is no systematic port security, isolation,
rate limiting, or storm control.

Reserve four known-good 1 GbE access ports for the incoming Raspberry Pi 5
systems. Do not use Lab port 14, port 16, or any link under active loop/error
investigation. The current Lab switch has enough nominal free ports, but that
does not override the Phase 2 physical-topology gate. Prefer the existing Lab
switch for initial staging so adoption of the arriving Pro Max remains a
separate change. Move the nodes later only through a documented, one-node-at-a-
time port migration.

Before connection, record each node's serial number, Ethernet MAC, hostname,
intended role, switch port, power source, and rollback owner. Create DHCP
reservations and DNS records only after checking existing static-address, VIP,
VPN, and NetBox allocations. Use the existing K3s/server VLAN 2 access profile,
with no unnecessary tagged VLANs. A node is not admitted to K3s merely because
it received a server-VLAN address.

Power the nodes with supported USB-C supplies, or confirm the exact PoE HAT and
its negotiated PoE class before using switch power. If PoE is selected, budget
all four nodes at measured boot and sustained draw, preserve headroom, and do
not place them on an already constrained 95 W PoE budget without calculation.

### Clients and network placement

The controller knew 65 clients: 14 online and 51 offline. Online clients were
11 wired and three wireless. Fifty-one clients were named, 14 were unnamed,
and none was marked blocked or guest.

| Offline age | Clients |
| --- | ---: |
| Less than one day | 8 |
| One to seven days | 14 |
| Seven to 30 days | 13 |
| 30 to 90 days | 13 |
| At least 90 days | 3 |

| Last network | Total | Online | Offline | Observation |
| --- | ---: | ---: | ---: | --- |
| Default | 23 | 6 | 17 | Infrastructure, Protect, cameras, and other clients are mixed. |
| Old Wifi Devices | 16 | 0 | 16 | Stale identities should be reviewed before deletion. |
| iot | 11 | 2 | 9 | IoT is separated by VLAN but not yet least privilege. |
| wifi | 10 | 1 | 9 | Trusted Wi-Fi network. |
| k8s-rpi | 5 | 5 | 0 | Four K3s nodes and the NAS were visible as clients. |

Do not bulk-delete offline clients. First classify recurring, seasonal,
replaced, and unknown identities, then remove only confirmed stale records
after DHCP reservations, firewall groups, Protect associations, and dashboards
have been checked.

### Current networks

| Network | Subnet | VLAN | Zone/type | Primary gap |
| --- | --- | ---: | --- | --- |
| Default | 192.168.1.0/24 | 1 | Internal | Management, cameras, Protect, and miscellaneous clients are mixed. |
| k8s-rpi | 192.168.3.0/24 | 2 | DMZ | Cluster source scopes are too broad in several user rules. |
| wifi | 192.168.4.0/24 | 3 | Internal | Trusted Wi-Fi; no L2 client isolation. |
| iot | 192.168.5.0/24 | 4 | Custom IoT | Can reach too much of the gateway; peer policy is not explicit. |

All four networks had mDNS enabled. Network isolation, DHCP guard, and IGMP
snooping were not consistently enforced per network. Global DHCP snooping was
enabled, but trusted DHCP ports were not expressed as an end-to-end access
policy.

The controller also had two WANs, two SSIDs, seven firewall zones, 95 firewall
policies, 53 DNS policies, one site-to-site VPN, and no ACL, LAG, MC-LAG,
switch stack, traffic list, or VPN server configured. Of the firewall policies,
87 were system policies, five were user policies, and three were derived; 94
were enabled.

### Protect and cameras

Five cameras were present: four wired G5 cameras on the Default network and one
wireless G4 Instant on trusted Wi-Fi. Protect has since moved from the CloudKey
to the UDM Pro, which now runs both Network and Protect. The CloudKey remains a
historical-footage source until its recordings are no longer required. The
UNVR-G2 therefore replaces the UDM Pro's Protect recorder role, not its Network
console role.

### Storage

The WD EX4100 currently uses two independent 1 GbE links on Lab switch ports 17
and 19. No LAG was configured. Dual-homing must not be allowed to form a loop.
If LACP is later supported and configured on both the NAS and the managed
desktop switch, aggregate capacity can improve across multiple flows, but a
single flow remains limited to one member link.

## Findings and Risk Register

| Priority | Finding | Impact | Required disposition |
| --- | --- | --- | --- |
| P0 | A disabled OpenVPN profile contained credentials that were exposed during legacy API inspection. | A disabled profile can still become an access path if re-enabled or copied. | Delete the unused profile or rotate all associated credentials before it can be enabled. Do not record the exposed material. |
| P0 | The temporary API key has Owner/Super Admin scope. | Workload compromise would become full-controller compromise if it were deployed. | Create dedicated least-privilege Network/DNS and read-only audit keys; revoke the temporary key after verification. |
| P0 | Lab port 14 remains down after BPDU Guard, following a loop detected on port 16. | Re-enabling either path without tracing the loop can destabilize the whole LAN. | Trace both ends of ports 14 and 16 and remove the physical/logical loop before resetting either port. |
| P1 | Core and Lab switches both use RSTP priority 32768. | Root selection is non-deterministic and topology changes can take the wrong path. | Set core to 0, direct access switches to 4096, downstream tier to 8192. |
| P1 | Historical link errors, drops, and repeated link-down events exist on critical uplinks and endpoints. | Marginal copper, optics, negotiation, or endpoint behavior can cause intermittent loss and STP churn. | Inspect, clean, reseat, certify, replace, and then re-baseline counters one link at a time. |
| P1 | Inter-zone policies include broad K3s, IoT, VPN, and gateway access. | A compromised endpoint can move laterally or reach administration surfaces. | Replace broad allows with exact sources, destinations, protocols, ports, and logging. |
| P1 | IDS recorded 493 new high or very-high events in the refreshed 30-day window while operating detect-only. | Real threats may be uncontained; blindly switching to block could also disrupt legitimate traffic. | Triage signatures and endpoints, suppress proven false positives narrowly, then stage IPS blocking. |
| P1 | Camera, Protect, management, storage, and ordinary clients share Default/VLAN 1. | Compromise and broadcast faults have an unnecessarily large blast radius. | Introduce dedicated networks and empty VLAN 1 through staged migrations. |
| P1 | Backups are local-only: daily at 01:00 with seven retained files. | Console or disk loss can remove both service and recovery data. | Add encrypted off-console backups and perform a restore test. |
| P1 | Delhi Home site-to-site VPN is enabled but inactive. | Intended remote connectivity is unavailable and produces persistent health ambiguity. | Restore with validated routes/policy or disable intentionally and document why. |
| P2 | The relocated Guest and newly adopted Master Bedroom U6+ APs are now at 1 Gb/s, but recent install/reconnect and transient low-speed events need a soak. | A marginal new or moved cable may regress after the point-in-time check. | Watch speed, link-down, error, PoE, and reconnect deltas before RF tuning. |
| P2 | Dining Room U6 Enterprise is limited to 1 Gb/s. | High-density radio capacity can exceed the wired uplink. | Move it to a 2.5 GbE PoE++ port on the Pro Max. |
| P2 | Lab-to-core uplink is 1 Gb/s. | K3s, NAS, AP, and camera traffic share a bottleneck. | Keep legacy switch traffic understood; use a 10 GbE uplink for the Pro Max and direct 10 GbE core links for new storage. |
| P2 | IoT speed profile is configured as 125 Kb/s up and down, not 125 Mb/s. | Devices can be unintentionally starved. | Replace it with a measured profile, proposed 10 Mb/s down and 5 Mb/s up. |
| P2 | Dining, Bedroom, and Guest 2.4 GHz radios all use channel 6 at high/automatic power; Master uses channel 1. | Co-channel contention is high, especially with the fourth AP. | Plan 1/6/11 reuse at 20 MHz and tune power after a survey. |
| P2 | User firewall policies do not log sensitive allows or denies. | Troubleshooting and policy verification lack evidence. | Enable bounded logging while tuning, then retain it on sensitive policies and denies. |
| P2 | mDNS is reflected across all VLANs. | Discovery leaks across trust boundaries and creates avoidable multicast load. | Limit reflected services and participating networks to actual Cast/AirPlay needs. |
| P2 | Legacy FTP, PPTP, H323, and TFTP helpers are enabled. | Unused application helpers enlarge the inspection surface. | Disable helpers unless a named application test proves one is required. |
| P2 | WAN history shows repeated loss, failure, and failover. | Internet availability may be lower than current status suggests. | Correlate TriplePlay/Airtel events, modem state, latency/loss, and failover behavior. |
| P3 | Unused ports are enabled and labels/profiles are generic. | Accidental attachment and configuration drift are harder to contain. | Use named access/trunk/quarantine profiles; disable unused data and PoE. |
| P3 | No wired ACLs or port-level isolation are configured. | VLAN policy alone may not meet guest/camera peer-isolation requirements. | Add only after the VLAN/firewall contract is stable and tested. |

### Physical and STP evidence

The refreshed 30-day event history contained ten STP topology flaps, two
loop-detected events, two BPDU Guard events, one port-dropped event, one SFP
transmit fault, and nine low-uplink-speed events. The newest low-speed events
were transient during AP moves/adoption; all four APs were at 1 Gb/s at the
point-in-time refresh.

Notable cumulative interface counters were:

| Link | Evidence | Interpretation and action |
| --- | --- | --- |
| Lab port 2, k8s-rpi1 | Earlier: 478 errors, 113 drops, 54 link-downs. After the 7.5.10 upgrade: four errors, no drops/link-downs. | Certify or replace the patch lead and alert on new post-upgrade deltas. |
| Lab ports 14 and 16 | Port 16 reported a loop; port 14 then triggered BPDU Guard and remains down. | Keep both paths controlled until the complete bridge/cable loop is traced. |
| Lab port 17, WD NAS | Earlier: 57 errors, one drop, 47 link-downs and STP flaps. After upgrade: no errors/drops and one link-down. | Inspect the dual-link design and retain the historical event evidence despite reset counters. |
| Lab port 10, new Master Bedroom U6+ | Current 1 Gb/s; one error and 15 lifetime link-downs after adoption/moves. | Soak and alert on new deltas before calling the cable stable. |
| Lab port 11, relocated Guest Room U6+ | Current 1 Gb/s; three lifetime link-downs and no errors/drops. | Soak after relocation. |
| Lab port 7, Dining Room U6 Enterprise | Current 1 Gb/s; five lifetime link-downs; AP uplink reported 212 receive drops. | Re-baseline and move to Pro Max 2.5 GbE when available. |
| Core port 1, UDM 10 GbE | 640 receive errors and 17 link-downs, up from 621 and 11 in the initial snapshot. | Inspect SFP/DAC seating and compatibility; alert on fresh deltas. |
| Core port 6, Lab 1 GbE uplink | 2,272 transmit drops and six link-downs, with drops unchanged and link-downs up from four. | Capacity and link-quality investigation; no counter grew during the refresh sample. |

### Firewall and security evidence

The global security posture was Allow All, with system zone policies adding
some boundaries. The five user policies were:

| Policy | Current state | Roadmap disposition |
| --- | --- | --- |
| Allow WireGuard to k8s-rpi | Disabled; empty server selection | Remove if obsolete or rebuild for a named VPN source; it is currently redundant with broad VPN-to-DMZ access. |
| Allow K8s to Access Protect | Entire K3s network to one Protect address on TCP 443/7441 | Narrow source to Home Assistant or an explicit service group when stable identities permit. |
| Allow Music Assistant Google Cast | One source to one player on TCP 8008/8009/8443 | Preserve; this is the model for least-privilege exceptions. |
| Allow K8s to Manage IoT | Entire K3s network to entire IoT network on all ports | Replace with per-application and per-device-group rules. |
| Allow DMZ to Gateway IP | Entire K3s network to 192.168.3.1 TCP 443 | Restrict to the ExternalDNS workload source if a stable source identity is available. |

Additional concerns:

- IoT-to-Gateway ended with Allow All, exposing unnecessary management paths.
- VPN-to-Internal, VPN-to-Gateway, and VPN-to-DMZ were broadly allowed.
- Internal-to-DMZ was broadly allowed; Internal-to-IoT was blocked.
- UPnP and NAT-PMP were off and should remain off.
- Direct SSH, direct-connect, and debug access were off and should remain off.
- Remote/cloud access was connected; every administrator requires MFA, or
  administration should be restricted through a policy VPN.
- Endpoint scanning and honeypot features were off. They should be evaluated
  only after the primary segmentation and alerting controls are reliable.
- DNS filtering reported none on Default, while traffic statistics showed a
  policy named Bloack Ads and global ad blocking reported false. Reconcile the
  desired DNS policy and the spelling/name drift before enforcing it.
- The legacy port-forward endpoint returned no rules, but repository
  documentation requires TCP/UDP 53181 to 192.168.3.16 for qBittorrent peer
  traffic. Reconcile the modern NAT/policy UI and live packet behavior before
  changing or declaring the forward absent.

### Activity, flow, security, VPN, and WAN evidence

The refreshed 30-day system history contained 7,982 events:

| Category | Events |
| --- | ---: |
| Client | 6,099 |
| VPN | 1,172 |
| Security | 493 |
| WAN | 144 |
| Device | 42 |
| Port | 25 |
| Software | 7 |

VPN history included 586 Teleport connect/disconnect pairs. Confirm whether
that volume matches intended use and verify that individual administrator
access is attributable and MFA-protected.

Security history contained 476 high and 17 very-high events, all marked new.
IDS remained detect-only across all four networks with 32 enabled categories
and no alert suppression/whitelist entries.
The refreshed 24-hour flow endpoint again produced inconsistent totals and a
5,000-row unfiltered cap. Separate filters were therefore used to avoid hiding
blocked and risky traffic:

- 735 blocked rows represented 940 sessions. Every captured blocked session
  was low-risk UDP DNS from the trusted Wi-Fi network, blocked by the ad
  blocking policy named Bloack Ads. These are not firewall segmentation denies.
- 28 medium-risk rows represented 39 sessions. All matched the CINS Army
  Reputation List, all were allowed, and all targeted or involved k8s-rpi2.
  The set included inbound connections to dynamic TCP/UDP ports and traffic on
  the documented qBittorrent peer port.
- No high-risk row appeared in the refreshed 24-hour filtered query, although
  the earlier monthly aggregate showed 31 high-risk allowed sessions.
- Allowed outgoing traffic exceeded the endpoint's 5,000-row return cap within
  only a few hours. The unfiltered sample still showed k8s-rpi2 dominating the
  available rows, consistent with peer-to-peer workload volume.

The flow API's row totals, session aggregation, and page counts are not
forensically complete. Preserve fixed query windows and use action, direction,
risk, source, and destination filters rather than trusting a single all-flows
export.

The k8s-rpi2 endpoint was involved in 310 of the 493 refreshed 30-day threat
events. Much of the visible activity resembled peer-to-peer tracker traffic,
but that is not enough evidence to dismiss the events. Preserve timestamps,
signature IDs, direction, destination workload, and packet metadata during
triage.

WAN history contained 47 restored, 13 failed, 43 failed-multiple-times, 19
failover, five temporary-failover, seven packet-loss, five high-latency, and
five temporary-failure events. Both WANs were healthy at the point-in-time
refresh. Investigation must distinguish ISP, modem/ONT, gateway, cable, DNS,
and health-check failures.

The Delhi Home site-to-site VPN was enabled but inactive. VPN health reported
zero active and one inactive tunnel.

Flow logging was enabled, NetFlow was off, and syslog was configured. These
signals should feed the existing observability stack with retention, alert
thresholds, and privacy controls rather than remain controller-only evidence.

## Target Physical Architecture

Use a star topology from the aggregation core. Do not daisy-chain the new
storage or desktop switch through the existing Lab switch.

    UDM Pro
      |
      | 10 GbE
      |
    USW Pro Aggregation, RSTP priority 0
      |
      +-- 10 GbE -- USW-Pro-Max-24-PoE, priority 4096
      |               +-- 2.5 GbE PoE -- U6 Enterprise
      |               +-- 1 GbE PoE --- U6+ access points
      |               +-- PoE ---------- cameras and new edge devices
      |
      +-- 1 GbE -- existing USW-24-PoE, priority 4096
      |              +-- Existing K3s nodes and legacy endpoints
      |              +-- Four staged Raspberry Pi 5 nodes at 1 GbE each
      |
      +-- 10 GbE -- managed desktop switch, priority 4096
      |              +-- 10 GbE desktop
      |              +-- WD EX4100 at 1 GbE or validated LACP
      |
      +-- 10 GbE -- UNAS Pro 4
      |
      +-- 10 GbE -- UNVR-G2

The Pro Max has 16 1 GbE PoE access ports, eight 2.5 GbE PoE++ ports, two
10 GbE SFP+ uplinks, and a 400 W PoE budget. Reserve 2.5 GbE ports for the U6
Enterprise and future multigigabit APs. Reserve core SFP28 capacity for future
25 GbE requirements rather than consuming it for ordinary 10 GbE endpoints
without need.

Start every new downstream switch with one uplink. Add LACP only after both
ends, member speeds, VLAN membership, hashing, failure behavior, and monitoring
are validated. No MC-LAG exists, so an LAG does not create switch-level high
availability. Use MTU 1500 initially; jumbo frames are an end-to-end change and
must not be enabled on only part of a storage path.

## Target STP and Port Standards

| Tier | RSTP priority | Examples |
| --- | ---: | --- |
| Core | 0 | USW Pro Aggregation |
| Direct access | 4096 | Pro Max, Lab switch, desktop switch |
| Downstream/temporary | 8192 | Any intentionally downstream managed switch |

- Keep RSTP enabled.
- Enable BPDU Guard only on confirmed edge endpoint ports, never on uplinks,
  trunks, switch interconnects, or an AP port until its bridge behavior has
  been verified.
- Enable loop protection and measured storm-control thresholds on edge ports
  after the topology is stable.
- Give every connected port a device/purpose label.
- Access profiles carry one untagged client VLAN and no unnecessary tagged
  VLANs.
- Trunk profiles have an explicit native VLAN and only the tagged VLANs the
  downstream device needs; avoid All unless the design actually requires all.
- Disable data and PoE on unused ports. Keep a named quarantine profile for
  staging unknown devices.
- Permit management only from the management/admin path, regardless of whether
  a port itself is trusted.
- Capture baseline CRC/error/drop/link-down counters after cable repair and
  alert on new deltas rather than lifetime totals.

## Target Logical Architecture

Keep existing production subnets during initial segmentation. New subnets are
proposed and require a conflict check against DHCP reservations, static hosts,
VPN routes, NetBox, DNS, Kubernetes manifests, and the Delhi remote site before
creation.

| Function | VLAN | Proposed subnet | UniFi zone | Migration note |
| --- | ---: | --- | --- | --- |
| Network management | 10 | 192.168.10.0/24 | Custom Management | UDM, switches, APs only; migrate last among infrastructure devices, one at a time. |
| K3s/server | 2 | 192.168.3.0/24 | DMZ/Server | Preserve existing addresses and service VIPs. |
| Trusted Wi-Fi/client | 3 | 192.168.4.0/24 | Internal | Preserve initially. |
| IoT | 4 | 192.168.5.0/24 | Custom IoT | Preserve initially; reduce policy. |
| Cameras | 30 | 192.168.30.0/24 | Custom Camera | Wired cameras and the G4 Instant after wireless validation. |
| Storage | 40 | 192.168.40.0/24 | Custom Storage | UNAS, WD NAS, and storage-facing clients only. |
| Guest | 50 | 192.168.50.0/24 | Hotspot/Guest | Internet only with L2 and network isolation. |
| Default/quarantine | 1 | 192.168.1.0/24 during transition | Quarantine/transition | Empty and retire as a client network after all dependencies move. |
| Policy VPN | Built in | Controller-assigned | VPN | Admin VPN separated in policy from ordinary remote clients. |

Do not use 192.168.21.0/24 because it is used by the Delhi remote site. Also
account for the disabled VPN client's 192.168.120.2/32 identity when checking
route overlap.

### Target zone policy matrix

Every unlisted new connection is denied. Stateful return traffic is allowed.
Policy rows are a design contract; exact Protect/storage ports must be reduced
after a live flow capture.

| Source | Destination | Allow | Deny or constraint |
| --- | --- | --- | --- |
| Admin devices or Admin VPN | Management | HTTPS administration; SSH only if deliberately enabled | No access from ordinary trusted, IoT, guest, camera, or storage clients. |
| Management | Internet | Controller updates, NTP, DNS, certificate/vendor services as required | Cannot initiate to ordinary client networks without a documented management need. |
| K3s/server | Gateway | DHCP, DNS, NTP; ExternalDNS to Network API HTTPS from its stable source | No whole-subnet gateway administration. |
| K3s/server | Protect/Camera | Home Assistant to Protect TCP 443/7441 and speaker-capable cameras TCP 7004; other exact services after audit | No whole-subnet Camera or Protect access. |
| K3s/server | IoT | Home Assistant/Music Assistant to named device groups and exact ports | Remove all-ports, whole-subnet rule. |
| Trusted | K3s/server | Required application VIPs, Traefik, and user services | Do not make every server port reachable by default. |
| Trusted | IoT | Controller apps to named devices as required | No blanket peer access. |
| IoT | Gateway | DHCP, DNS, NTP | No gateway administration or other local services. |
| IoT | Internet | Vendor endpoints if required, preferably by DNS/category and logs | Block unsolicited local and cross-zone access. |
| IoT | IoT | Only device groups needing local hubs/casting | Isolate devices that do not need peers. |
| Camera | UNVR | Only Protect adoption, control, media, and time/DNS flows verified for the installed versions | No general management, trusted, K3s, or Internet access. |
| Camera | Gateway | DHCP, DNS, NTP | No gateway administration. |
| Storage | K3s/server | Stateful return for exact NFSv4/SMB clients | Storage cannot initiate broadly into servers. |
| K3s/server | Storage | Exact source hosts to NFSv4/SMB services and administration only from admin sources | No whole-subnet any/any. |
| Trusted | Storage | Named clients and required shares/protocols | Storage administration remains admin-only. |
| Guest | Internet | DNS, DHCP, NTP, HTTP/HTTPS and other intended Internet services | No RFC1918/local networks; no client-to-client access. |
| VPN user | Internal services | Named services according to role | No default access to Management or Gateway. |
| Any untrusted zone | Gateway | DHCP/DNS/NTP only where required | Deny management plane and log attempts. |

### Discovery and DHCP controls

- Replace global all-network mDNS reflection with a Custom service/network list
  for only required Cast, AirPlay, printer, and discovery services.
- Preserve the existing narrow Music Assistant-to-bedroom-player TCP
  8008/8009/8443 rule and the player's return fetch to Music Assistant TCP
  8097.
- Trust DHCP only on the gateway/upstream path. Enable per-network DHCP guard
  only after the legitimate server address is verified.
- Enable IGMP snooping where multicast behavior is understood and test Protect,
  Cast, AirPlay, and IPv6 before expanding it.
- Keep UPnP and NAT-PMP disabled.
- Disable FTP, PPTP, H323, and TFTP helpers unless a documented application
  fails a controlled test without one.

## Client Isolation Model

Client isolation is layered. Wi-Fi L2 isolation affects clients on the same
SSID/AP domain; network isolation and switch ACLs control routed or wired peer
paths. A checkbox on the SSID is not a complete boundary.

| Client class | Wi-Fi client isolation | Network/ACL isolation | Exceptions |
| --- | --- | --- | --- |
| Guest | Enabled | Enabled | Gateway DHCP/DNS/NTP and Internet only. |
| IoT with no local hub/peer need | Enabled | Enabled | Exact controller/cloud requirements. |
| IoT requiring hub, Cast, AirPlay, or peer discovery | Test per device group | Enabled by default | Named controllers, peers, mDNS services, and ports only. |
| Trusted clients | Disabled | Normal stateful zone policy | Users retain intended LAN collaboration. |
| Cameras | Optional after Protect validation | Camera zone and explicit ACL | Camera-to-UNVR flows and required time/DNS. |
| Management infrastructure | Not applicable | Strongest isolation | Admin sources only. |

Test onboarding, DHCP, DNS, NTP, firmware update, casting, speaker control,
camera adoption, recording, playback, and mobile roaming after each isolation
change. Apply one device group at a time.

## Wi-Fi Roadmap

### Baseline

| SSID | Current design | Primary gaps |
| --- | --- | --- |
| Abhimanyu | Trusted Wi-Fi VLAN; WPA2/WPA3 Personal; PMF optional; 2.4/5/6 GHz; BSS transition enabled | No L2 isolation by design; no fast roam; 2.4 GHz minimum basic rate is 1 Mb/s; no client cap. |
| abhimanyu-iot | Hidden; 2.4 GHz; WPA2; PMF disabled; Enhanced IoT; Wifi IoT Speed profile | Hidden is not a security control; no L2 isolation; profile is accidentally 125 Kb/s. |

Three of four 2.4 GHz radios were on channel 6 at 20 MHz and high/automatic
power around 22-23 dBm; the new Master Bedroom AP was on channel 1. Refreshed
point-in-time utilization was:

| AP | 2.4 GHz | 5 GHz |
| --- | ---: | ---: |
| Dining Room U6 Enterprise | 48% | 1% |
| Bedroom Room U6+ | 58% | 1% |
| Guest Room U6+ | 68% | 4% |
| Master Bedroom U6+ | 47% | 13% |

There were 609 neighboring observations across 398 unique BSSIDs: 505
observations at 2.4 GHz, 104 at 5 GHz, and 20 open observations. None was
marked rogue. These are environmental observations, not a substitute for a
site survey or spectrum capture.

Current 5 GHz channels were 100, 153, 44, and 48 at 80 MHz. Guest channel 44
and Master channel 48 occupy the same 80 MHz block and therefore contend
despite having different primary channels. The Dining Room 6 GHz radio was set
to automatic at 160 MHz and had no active channel/client in the snapshot.

The new Master AP served one 5 GHz client at 95% satisfaction during the
refresh; the relocated Guest AP had no associated clients. Dining served two
2.4 GHz IoT clients. One of those clients showed a 33.3% transmit retry rate,
and the Dining 2.4 GHz radio showed a 25% retry rate, reinforcing the need for
channel/power tuning after the post-move soak.

### Target RF and security profile

- Keep all four repaired/current 1 Gb/s AP links under a post-move counter
  soak, and move the U6 Enterprise to 2.5 GbE before judging radio capacity.
- Assign non-overlapping 2.4 GHz channels 1, 6, and 11 at 20 MHz based on
  physical reuse, not device order.
- Reduce 2.4 GHz power after a walk/coverage survey so clients prefer 5/6 GHz
  where signal permits.
- Use 40 MHz on congested 5 GHz cells and 80 MHz only where measured airtime
  and channel reuse support it.
- Use 6 GHz only after WPA3/PMF/client compatibility and real coverage are
  validated; 160 MHz is not automatically better in a noisy or small cell.
- Raise the trusted SSID minimum basic rate only after coverage validation so
  weak but necessary clients are not disconnected.
- Consider fast roaming on the trusted SSID only after wired stability,
  roaming tests, and legacy-client compatibility checks. Do not enable it as a
  generic performance switch.
- Keep IoT security compatible with actual devices, but inventory devices that
  prevent stronger WPA/PMF settings and replace them over time.
- Treat the hidden IoT SSID as cosmetic; security comes from credentials,
  identity, isolation, and firewall policy.
- Use unique strong credentials, planned rotation, and a separate guest SSID.
  Enterprise/RADIUS authentication can be evaluated later if operational
  ownership and recovery are available.

### Bandwidth policy

Start with simple per-client profiles:

| Class | Proposed down | Proposed up | Reason |
| --- | ---: | ---: | --- |
| Trusted | Unlimited | Unlimited | Preserve LAN, NAS, backup, and interactive performance. |
| IoT | 10 Mb/s | 5 Mb/s | Sufficient for most devices; tune exceptions from evidence. |
| Guest | 25 Mb/s | 10 Mb/s | Bound shared WAN usage without making normal use painful. |
| Cameras/UNVR/Storage | No Wi-Fi rate profile | No Wi-Fi rate profile | Control through segmentation and capacity, not Internet-style shaping. |

Correct the current 125 Kb/s IoT profile before using it as a template. Apply
profiles to a small test group and verify firmware updates, voice assistants,
streaming devices, and calls.

Enable Smart Queues only after measuring WAN speed, latency under load,
bufferbloat, CPU cost, and dual-WAN behavior. Configure slightly below stable
measured throughput and retest failover. Smart Queues can reduce maximum
throughput; they are not a substitute for local VLAN or Wi-Fi capacity.

## Protect and UNVR-G2 Roadmap

The UNVR-G2 provides four drive bays, 10 GbE SFP+, 2.5 GbE copper, and capacity
for a materially larger camera estate. Capacity estimates are not a retention
guarantee; calculate retention from camera count, codec, frame rate, resolution,
detection mode, drive size, and redundancy.

Before migration:

1. Create a Protect-specific read-only API key and complete the missing audit:
   console/disk health, retention, recording mode, microphone policy, privacy
   zones, smart detections, alarm rules, users/roles, remote access, camera
   firmware, stream encryption, snapshots, RTSPS, speaker paths, and backups.
2. Export system and Protect configuration backups and copy them off-console.
3. Record every camera name, address/reservation, switch port, VLAN, model,
   firmware, adoption state, recording mode, retention expectation, and Home
   Assistant entity.
4. Size and install supported drives, select the desired redundancy, and run
   drive health/burn-in checks.
5. Build the camera VLAN and exact firewall policy while cameras remain on the
   old recorder.
6. Validate the UNVR management path from admin sources and its 10 GbE core
   link at MTU 1500.

Protect recording history cannot be transferred as ordinary configuration
data, and moving disks between consoles may reformat them. Keep the UDM Pro
available as the active pre-UNVR recorder and retain the CloudKey for its
required historical-footage window. Do not factory reset or repurpose either
console while its recordings are still required.

Migrate one camera at a time. Verify adoption, live view, continuous/event
recording, detection, playback, mobile access, time synchronization, and alert
delivery before the next camera. Then verify Home Assistant to Protect TCP 443
and RTSPS TCP 7441, plus direct camera speaker TCP 7004 for speaker-capable
cameras.

UniFi documents Protect service ports including 7441, 7442, 7443, 7444, 7445,
7447, 7550, 7552, and 7888 for various local functions. Do not open the entire
set bidirectionally by default. Capture flows for the installed console and
camera versions, determine initiator/direction, and narrow the camera-to-UNVR
rules accordingly.

Enable Protect stream encryption only after console, camera, browser,
Home Assistant, RTSPS, and mobile-client support are verified. Retire the old
CloudKey only after the new UNVR has passed the full retention soak, backups
restore successfully, and no required history remains solely on the old host.

## UNAS Pro 4, Desktop Switch, and WD NAS Roadmap

Connect the UNAS Pro 4 directly to the aggregation core over one 10 GbE link at
MTU 1500 initially. Place management in the management path and data services
in the storage zone according to supported interface/VLAN behavior. Restrict
NFS/SMB access to named K3s nodes and trusted clients. Prefer NFSv4 where it
meets application requirements because it has a narrower firewall surface than
legacy RPC-based NFS.

The UNAS supports four data drives, two NVMe devices, SMB/NFS, snapshots,
multiple RAID layouts, and backup targets. RAID and snapshots are not backups.
The storage plan requires:

- workload and capacity forecast;
- supported, matched drives and health validation;
- selected redundancy and documented usable capacity;
- snapshots with retention;
- backup from UNAS to a separate failure domain such as the WD NAS and/or
  offsite/cloud target;
- a reverse or offsite copy that does not depend on the UNAS being alive;
- periodic file and full-share restore tests;
- UPS integration and clean-shutdown testing;
- disk, pool, snapshot, backup, temperature, and capacity alerts.

Connect the managed desktop switch directly to the core at 10 GbE. The exact
model must be recorded before defining its port profiles, VLAN support, LACP,
STP priority, management path, or PoE behavior. The desktop receives a 10 GbE
access profile for its intended trust zone. Keep the WD EX4100 on one validated
1 GbE link until its dual-NIC mode and the switch's LACP support are confirmed.
If LACP is enabled, configure and test it on both ends in one maintenance
window, including single-member failure and reboot behavior.

Do not bridge two NAS interfaces, place them in the same Layer 2 domain with
independent active addresses without an intentional supported mode, or use two
switch paths to simulate redundancy. Those patterns can create loops,
asymmetric traffic, or unstable service discovery.

## Credential, Backup, and Administration Controls

- Create one least-privilege Network API key for the DNS integration. Grant
  only the DNS/Network write capabilities it actually needs if the controller
  role model permits.
- Create a separate read-only Network audit key and a Protect-specific
  read-only audit key.
- Update only the encrypted SOPS field in Git, let Fleet reconcile the
  generated Secret, and validate authentication and DNS reconciliation before
  revoking the predecessor.
- Never deploy the temporary Owner/Super Admin key to Kubernetes and never
  include plaintext keys in Git, tickets, logs, shell history, or this roadmap.
- Remove or rotate the credential-bearing disabled OpenVPN profile before any
  chance of re-enablement.
- Require MFA for all cloud/remote administrators, individual accounts instead
  of shared credentials, least-privilege roles, and periodic access review.
- Preserve SSH/direct-connect/debug disabled unless a time-bound break-glass
  runbook explicitly enables and later disables them.
- Copy automated controller and Protect backups to an encrypted off-device
  destination. Keep multiple generations and perform scheduled restore tests.
- Store recovery material outside the hardware it restores and document
  console replacement, Internet outage, and credential-loss procedures.

## Observability and Security Operations

### IDS/IPS

1. Export the 493 threat events with signature, category, direction, endpoint,
   policy, and packet/session metadata.
2. Map k8s-rpi2 traffic to pods, host processes, NAT/LoadBalancer VIPs, and
   expected media/P2P workloads at each timestamp.
3. Investigate the CINS-listed inbound sources and the 31 monthly high-risk
   allowed sessions rather than classifying them from reputation alone.
4. Patch or contain confirmed vulnerabilities.
5. Add narrowly scoped suppressions for proven benign signatures only.
6. Stage blocking by category or test endpoint, watch CPU/throughput and false
   positives, then expand. Keep a quick policy rollback.

### Network and device health

- Alert on new CRC/errors, drops, link-speed regression, repeated link-downs,
  BPDU Guard, STP topology changes, loops, PoE budget/overload, AP uplink speed,
  switch temperature, storage capacity, disk health, and device offline state.
- Track client count and offline age, but do not alert on ordinary sleeping IoT
  devices without an availability contract.
- Monitor WAN packet loss, latency, health-check target, failover/failback,
  public address change, and modem/ONT reachability separately.
- Monitor site-to-site VPN state, route reachability, reconnect rate, and
  authentication events.
- Feed bounded syslog and flow metadata to the existing telemetry stack with
  retention, access controls, and sensitive-field handling.
- Evaluate NetFlow after sizing volume and storage. Do not enable high-volume
  export without a retention and query plan.
- Add dashboards for core/uplink capacity, radio airtime/channel utilization,
  DHCP/DNS failures, firewall denies, top inter-zone flows, IDS disposition,
  Protect recording health, and storage backup age.

### Future Grafana network observability architecture

This section is a researched implementation proposal, not a record of deployed
state. The first implementation should be a new Fleet-managed
`kubernetes/projects/system/apps/unifi-observability/` app. It should reuse the
existing Rancher Monitoring Prometheus and Grafana plus the existing Loki
gateway; it should not introduce a second monitoring stack.

The targeted read-only 2026-08-24 research refresh found UniFi Network 10.5.67
on UDM Pro with traffic-flow collection allowed, but NetFlow disabled. It also
recorded these correlation points:

- UNAS Pro 4 at `192.168.1.128`, Pro Max port 21, negotiated at 1 Gb/s;
- current Protect storage path at `192.168.1.174`, Pro Max port 5, negotiated
  at 1 Gb/s;
- wired G5 cameras on the Default network on Pro Max ports 2, 3, 6, and 9; and
- the Wi-Fi G4 Instant at `192.168.4.120`, associated with the Master Bedroom
  AP on the `wifi` network.

These addresses, associations, ports, link speeds, controller settings, and
available MetalLB addresses must be re-read immediately before implementation
because cabling and migrations can change them.

#### Visibility model and limits

No single exporter can answer every internal-traffic question. Build the
dashboard from complementary sources and label panels with the source and its
blind spots.

| Source | Answers | Important limitation | Priority |
|---|---|---|---|
| UnPoller Prometheus metrics and DPI | Device, AP, client, switch-port, WAN, application/category, and UNAS health/rates | Controller aggregates are not a complete flow ledger | Required foundation |
| UniFi IPFIX/NetFlow to GoFlow2 | Routed conversations, protocols, bytes, and inter-VLAN patterns | UniFi exports completed sessions that pass through the gateway; same-VLAN switched traffic is invisible | Bounded pilot |
| SNMPv3 exporter | Independent interface counters and capacity checks | Adds credentials and another collector; some device families have limited support | Optional |
| Switch port mirror to a Zeek sensor | Exact connection metadata for traffic crossing the mirrored port, including same-VLAN traffic | Requires a dedicated capture NIC/host and a controller/physical change | Optional diagnostic phase |

For example, UNAS-to-client traffic within one VLAN can be switched directly
by the Pro Max and will not cross the UDM. The UNAS aggregate rate and port 21
counters will still show load, but IPFIX will not identify the client. Exact
same-VLAN attribution requires a temporary or permanent port mirror.

#### Foundation: UnPoller metrics, logs, and UNAS support

Start with UnPoller `v4.0.1` or a later version validated at implementation
time. Version 4 introduced opt-in UNAS Pro support and version 4.0.1 corrected
switch receive-packet reporting. Confirm an ARM64 image is available before
pinning it.

The Fleet app should contain:

- a single-replica UnPoller `Deployment`, ClusterIP `Service`, and
  `ServiceMonitor` for TCP `9130`;
- a dedicated SOPS-encrypted `Secret` for UniFi and UNAS credentials;
- least-privilege `NetworkPolicy` rules;
- Grafana dashboard ConfigMaps and, only after baselining, `PrometheusRule`
  resources; and
- resource requests/limits based on a measured pilot rather than copied
  defaults.

Use a dedicated Network API key with only the required read access. Do not
reuse the ExternalDNS integration credential merely because it already exists.
UNAS polling does not support an API key: create a dedicated local UNAS account
with the least privilege that can read device, storage, drive, share, and
network-I/O data. Never use an owner account or place credentials in the
ConfigMap.

The current UNAS input obtains that data from the Drive device-info, storage,
drive, and network-I/O API paths. Treat those paths as an implementation detail
that can change with UnPoller or UniFi Drive releases; validate the pinned
collector against the live UNAS before rollout:

- `/proxy/drive/api/v2/systems/device-info`;
- `/proxy/drive/api/v2/storage`;
- `/proxy/users/drive/api/v2/drives`; and
- `/proxy/drive/api/v2/systems/network-io`.

The planned egress and ingress contract is:

- UnPoller to UDM TCP `443`;
- UnPoller to UNAS TCP `443`;
- Prometheus to UnPoller TCP `9130`;
- UnPoller to the in-cluster Loki gateway TCP `8080`; and
- DNS for service and controller name resolution.

The implementation-time configuration should begin from this shape, with all
credentials injected from the encrypted Secret:

```toml
[prometheus]
disable = false
http_listen = "0.0.0.0:9130"
interval = "60s"
dead_ports = true

[influxdb]
disable = true

[loki]
disable = false
url = "http://loki-gateway.cattle-monitoring-system.svc.cluster.local/loki/api/v1/push"
interval = "2m"

[unifi]
dynamic = false

[unifi.defaults]
url = "https://192.168.3.1"
sites = ["default"]
save_sites = true
save_dpi = true
save_traffic = true
save_syslog = true
save_events = false
save_alarms = true
save_anomalies = true
save_ids = false
save_rogue = false
save_speedtest = true
verify_ssl = false

[unas]
enable = true

[[unas.device]]
url = "https://192.168.1.128"
verify_ssl = false
timeout = "60s"
```

`save_dpi` produces per-client application/category aggregates. Budget roughly
150 additional time series per active client until measurements prove
otherwise. `save_traffic` is country-level aggregate data, not a substitute for
IPFIX. `save_syslog` can contain IP addresses, MAC addresses, hostnames, user
activity, and other personal data; keep access internal and retention bounded.

UNAS panels should cover CPU, memory, temperature, aggregate receive/transmit
rate, pool capacity and usage, RAID expected/current state and rebuild
progress, drive health/temperature/sectors/read-write activity, and share
quota/usage. Correlate UNAS receive/transmit rate with the current switch-port
counters. This provides storage and network saturation evidence, but not the
identity of each same-VLAN client.

#### Routed-flow pilot: UniFi IPFIX to GoFlow2 and Loki

Only after the foundation has established a stable baseline, run a 24- to
48-hour IPFIX pilot:

1. Deploy GoFlow2 as an ARM64-compatible single-replica collector with UDP
   `2055`, a health/metrics endpoint, JSON written to stdout, and Alloy shipping
   those pod logs to Loki.
2. Expose UDP `2055` with a dedicated MetalLB address. Address `192.168.3.18`
   appeared unused during research, but re-check the full pool before reserving
   it in Git.
3. Restrict collector ingress to the UDM source and keep source/destination IPs
   as JSON fields, not Loki labels, to prevent cardinality growth.
4. In UniFi Network, open **Settings > CyberSecure > Traffic Logging >
   NetFlow**, select IPFIX, enter the collector address and UDP `2055`, and use
   the default sampling/export settings for the first pilot.
5. Generate a known inter-VLAN transfer and confirm that templates decode and
   the expected source, destination, protocol, byte count, and timestamps reach
   Loki.
6. Generate a known same-VLAN transfer and record its expected absence from
   IPFIX so the dashboard does not imply coverage that does not exist.

Use a shorter dedicated flow-log retention period during the pilot. Measure
GoFlow2 drops, Alloy/Loki ingestion rate, Loki disk growth, query latency, and
resource use before deciding whether to retain flow logs for seven days or
expand the export. Disable NetFlow if volume, privacy, or query cost exceeds
the agreed budget.

#### Optional exact same-VLAN attribution

If aggregate UNAS and switch-port metrics cannot explain a recurring problem,
mirror the relevant Pro Max source port to an otherwise unused destination
port and attach a dedicated Linux sensor with a separate capture NIC. Mirror
the then-current UNAS port to study all storage conversations or the
then-current Protect/UNVR port to study recording traffic. Do not mirror into a
production K3s node's primary NIC.

Run Zeek on the sensor and forward bounded JSON connection metadata such as
`conn.log` to Loki. Do not retain full packet captures by default. Port
mirroring is a live controller and physical-network mutation and therefore
requires explicit authorization, a time window, a storage estimate, and a
rollback step that removes the mirror.

SNMPv3 is a separate optional cross-check. If required, enable it under
**Settings > CyberSecure > Traffic Logging > SNMP**, use SNMPv3 with SHA and
AES-128, allow UDP `161` only from the exporter, and store its credential in
SOPS. Do not add it merely to duplicate port counters already supplied reliably
by UnPoller.

#### Dashboard information architecture

Provide drill-down links between views instead of one oversized dashboard:

1. **Network overview:** current/peak throughput, busiest link and AP, active
   clients, WAN health, and open alerts.
2. **Core and uplinks:** negotiated speed, utilization and remaining headroom,
   p95 rate, saturation duration, drops, errors, and link transitions.
3. **Wi-Fi:** airtime/channel utilization, retries, signal, roaming, and
   throughput by AP, SSID, and band.
4. **UNAS and storage:** network receive/transmit, switch-port traffic, disk
   I/O, pool/RAID state, share usage, and backup/restore status.
5. **Cameras and Protect:** camera aggregate traffic, bitrate changes,
   availability, and the Protect/UNVR recording-path link.
6. **Internal routed flows:** top source/destination pairs, protocols,
   inter-VLAN patterns, denied traffic, and explicit notice of the same-VLAN
   blind spot.
7. **Reliability:** device offline, STP, port flap, DHCP/DNS, WAN, VPN, and
   controller anomaly events.
8. **Capacity planning:** hourly/daily/weekly heat maps, p95 and maximum demand,
   and time spent above warning/critical utilization thresholds.

Calculate link utilization as `8 * bytes_per_second / negotiated_bits_per_second`
rather than comparing traffic to a hard-coded 1 or 10 Gb/s value. Alert on
sustained utilization and error/drop deltas, not isolated peaks or sleeping
client disconnects. Set thresholds only after several days of baseline data.

#### Security, privacy, and operating limits

- Keep Grafana and all raw telemetry LAN/VPN-only.
- Encrypt credentials with SOPS, use separate revocation boundaries, and never
  expose credentials in dashboards, logs, rendered manifests, or this roadmap.
- Decide whether hostnames, client names, MACs, and addresses may be retained.
  Hashing reduces personal-data exposure but makes per-device investigations
  less useful.
- Keep identifiers in log fields rather than high-cardinality Loki labels.
- Apply least-privilege NetworkPolicies to collectors and monitoring paths.
- Do not retain raw packet captures by default.
- Re-measure Prometheus series count and Loki ingestion/storage after enabling
  each source; do not enable DPI, syslog, and IPFIX simultaneously on the first
  deployment day.

## Phased Roadmap

### Phase 0: Freeze, evidence, and recovery gate

- **Owner:** network operator
- **Effort:** half a day
- **Mutation:** none

1. Confirm every adopted device is online and record current firmware, port,
   VLAN, policy, DHCP, DNS, Wi-Fi, Protect, VPN, WAN, flow, and alert state.
2. Export encrypted controller and Protect backups off-device.
3. Capture configuration screenshots/exports for every object changed by the
   next phase and identify its direct rollback.
4. Record exact physical cable endpoints and label both ends.
5. Reconcile the repository's qBittorrent forward with the modern live NAT UI.
6. Freeze unrelated firmware, subnet, storage, K3s networking, ISP, and camera
   changes until the active phase reaches its soak gate.

**Validation:** backup files exist off-console, can be decrypted by the intended
operator, and a non-destructive restore rehearsal or documented restore test is
complete.

**Exit gate:** the live snapshot is current, all dependencies are named, and
every planned mutation has a rollback.

**Rollback:** not applicable; this phase is read-only.

### Phase 1: Contain credentials and administration risk

- **Owner:** security and network operator
- **Effort:** half to one day
- **Mutation:** UniFi credentials and encrypted Git secret through normal
  Fleet ownership

1. Delete the unused credential-bearing VPN profile or rotate its credentials.
2. Create dedicated least-privilege DNS integration and read-only audit keys.
3. Update only the encrypted SOPS API-key field in the repository.
4. Let Fleet reconcile; verify the child bundle, generated Secret ownership,
   workload readiness, controller authentication, and a fresh DNS sync.
5. Revoke the temporary Owner/Super Admin key and any superseded key only after
   the new key works end to end.
6. Verify individual admin roles, MFA, recovery accounts, and remote access.

**Validation:** no plaintext appears in Git/diff/logs, ExternalDNS stays ready,
DNS records reconcile, read-only audit access works, and old keys fail after
revocation.

**Exit gate:** workloads and audits use separate least-privilege credentials
and no exposed VPN credential remains usable.

**Rollback:** re-encrypt the previously working site-scoped workload key if the
new role cannot perform required DNS operations; do not restore the exposed
temporary owner key.

### Phase 2: Repair loops, cabling, optics, and STP

- **Owner:** network operator
- **Effort:** one to two maintenance windows
- **Mutation:** physical cabling and switch policy

1. Keep Lab port 14 disabled and treat port 16 as part of the same incident
   while tracing every connected bridge/switch path.
2. Inspect the WD dual-NIC design and remove any unsupported bridge/dual-active
   topology.
3. Soak the new Master Bedroom and relocated Guest Room AP links at 1 GbE;
   repair or re-terminate immediately if speed, error, drop, PoE, or reconnect
   counters regress.
4. Inspect and re-seat or replace the Lab p2/p6/p17, Core p1/p6, and related
   cables, optics, or DACs one at a time.
5. Set RSTP priorities: core 0, directly attached access switches 4096, future
   downstream tier 8192.
6. Restrict BPDU Guard to confirmed edge ports; enable loop protection and
   conservative storm control only after the physical topology is understood.
7. Clear/re-baseline counters only after recording their original values, then
   observe new deltas.

**Validation:** no new STP block/flap/BPDU event, no speed regression, no new
CRC/error/drop delta, stable management reachability, and normal K3s/Protect/
WAN traffic for at least 24 hours.

**Exit gate:** every active link has one documented path, intended speed, named
profile, and stable error counters.

**Rollback:** restore the prior RSTP priority/profile from the captured export;
disconnect the newly identified loop rather than re-enabling an unsafe port.

### Phase 3: Adopt the Pro Max and establish the star core

- **Owner:** network operator
- **Effort:** one maintenance window plus 48-hour soak
- **Mutation:** new switch adoption and physical uplinks

1. Inventory serial/model/firmware, update NetBox or the source of truth, and
   validate the hardware before production attachment.
2. Adopt the Pro Max on a quarantine/management path and bring firmware to the
   approved version without combining the change with VLAN migration.
3. Connect one 10 GbE uplink directly to the aggregation core.
4. Apply RSTP priority 4096, explicit management, and a minimal trunk profile.
5. Move the U6 Enterprise to a 2.5 GbE PoE++ port, then move other APs and new
   PoE endpoints one at a time.
6. Track actual PoE draw and keep budget headroom for boot/inrush and future
   cameras.
7. Keep the existing Lab switch connected for K3s and legacy endpoints.
8. Reserve and label four clean Lab-switch access ports for the incoming
   Raspberry Pi 5 nodes; do not use ports implicated in the loop incident.
9. Stage one Pi at a time: verify link, power, DHCP reservation, DNS, NTP,
   server-VLAN placement, isolation, monitoring, and clean counters before the
   next. Join or schedule it in K3s only through the cluster's normal GitOps/
   Ansible onboarding and after cluster-role and failure-domain review.

**Validation:** stable 10/2.5/1 GbE negotiation, intended VLANs only, no STP
changes, no counter deltas, APs adopt and serve clients, PoE remains below the
planned budget, and roaming/DHCP/DNS work. Each new Pi must negotiate at 1 GbE,
receive only its reserved identity, pass intended K3s/server reachability and
negative isolation tests, expose monitoring, and show no new errors, drops,
flaps, duplicate addresses, or unexpected east-west flows during a 24-hour
staging soak.

**Exit gate:** the Pro Max has soaked for 48 hours with clean links and exact
port profiles.

**Rollback:** return each moved endpoint to its labeled original Lab port; keep
the new switch isolated until its uplink/profile issue is corrected.

### Phase 4: Introduce management and explicit port profiles

- **Owner:** network and security operator
- **Effort:** one to two days
- **Mutation:** VLAN, DHCP/DNS, firewall, and infrastructure addressing

1. Conflict-check and create the Management VLAN/zone.
2. Create named access, AP trunk, switch trunk, storage, camera, guest,
   quarantine, and disabled profiles with explicit VLAN lists.
3. Permit administration only from named admin clients and Admin VPN sources.
4. Migrate one non-core infrastructure device at a time, validating adoption
   and rollback before the next.
5. Migrate the core only when every downstream device has a known recovery
   path and console access is available.
6. Disable unused ports and PoE after confirming they are not expected offline
   endpoints.

**Validation:** controller sees every device, administrators can reach
management services only from approved paths, ordinary clients cannot, and no
AP/switch loses adoption across reboot.

**Exit gate:** UDM, switches, and AP management are separated from user/device
traffic and every port has an exact profile.

**Rollback:** restore the previous native/management VLAN on one device at a
time using its documented local recovery path.

### Phase 5: Create Camera, Storage, and Guest networks

- **Owner:** network operator
- **Effort:** two to four days
- **Mutation:** new networks, DHCP, DNS, SSIDs, and staged client moves

1. Conflict-check and create Camera VLAN 30, Storage VLAN 40, and Guest VLAN
   50 with no broad inter-zone access.
2. Create DHCP scopes, reservations, DNS behavior, NTP, and gateway-service
   policy before moving a client.
3. Pilot one disposable guest client and verify Internet-only behavior and
   wired/wireless peer isolation.
4. Pilot one camera while it remains on the old Protect console; capture exact
   flows and confirm recording/playback/alerts.
5. Pilot a non-critical storage path and measure DNS, MTU, throughput,
   permissions, reconnect, backup, and failover behavior.
6. Migrate remaining low-risk clients in small batches. Keep VLAN 1 available
   only as a controlled transition/quarantine network.

**Validation:** each pilot gets DHCP/DNS/NTP, reaches only intended services,
survives reboot/renewal, and produces expected deny logs without service loss.

**Exit gate:** new zones are functional with exact observed dependencies and
VLAN 1 no longer hosts new clients.

**Rollback:** return only the current pilot to its prior access profile and DHCP
reservation; leave already validated migrations intact.

### Phase 6: Replace broad firewall policy and enforce isolation

- **Owner:** security and network operator
- **Effort:** three to five days plus soak
- **Mutation:** zone policies, ACLs, DHCP guard, mDNS, and helpers

1. Build address/device groups for admin clients, Home Assistant, Music
   Assistant, ExternalDNS, Protect, cameras, storage clients, and speakers.
2. Add exact allow rules before adding the corresponding deny.
3. Narrow K3s-to-Protect, K3s-to-IoT, K3s-to-Gateway, VPN, Internal-to-DMZ, and
   IoT-to-Gateway paths.
4. Preserve the current narrow Cast and Home Assistant dependencies.
5. Apply guest isolation, then IoT device-group isolation, then camera ACLs.
6. Limit mDNS services/networks and enable DHCP guard with only the legitimate
   server trusted.
7. Disable unused application helpers.
8. Enable logging on final denies and sensitive allows; tune retention and
   noise without removing security evidence.

**Validation:** use a source/destination/port test matrix from every zone,
including negative tests. Verify K3s API/services, ExternalDNS, Home Assistant,
Cast playback, Protect API/RTSPS/speakers, storage mounts, guest Internet, VPN,
DHCP, DNS, NTP, and firmware updates.

**Exit gate:** every cross-zone allow has an owner, application, source,
destination, protocol/port, logging decision, and tested negative boundary.

**Rollback:** disable only the newest deny or restore its immediately preceding
policy export; do not return the whole network to global any/any.

### Phase 7: Tune Wi-Fi security, RF, and speed profiles

- **Owner:** wireless network operator
- **Effort:** two survey/tuning windows plus seven-day observation
- **Mutation:** radio, SSID, security, roaming, and rate-limit policy

1. Survey coverage, interference, airtime, retry rate, RSSI, SNR, client
   capability, and actual roaming after AP uplinks are stable.
2. Assign 2.4 GHz channels 1/6/11 at 20 MHz and reduce overlapping power.
3. Select 5 GHz 40/80 MHz widths per cell; validate DFS behavior and 6 GHz
   WPA3 coverage.
4. Correct the IoT profile to an intentional measured limit; create the guest
   profile and pilot both.
5. Strengthen PMF/WPA and minimum basic rates only for compatible client groups.
6. Pilot fast roaming on trusted devices; leave it off if any critical client
   becomes unstable.

**Validation:** wired uplinks remain clean; retries, airtime, latency, roaming,
voice/video, IoT onboarding, multicast discovery, and throughput improve or do
not regress for seven days.

**Exit gate:** every SSID has an owner, client class, security mode, VLAN,
isolation rule, speed policy, and measured RF plan.

**Rollback:** restore the last known-good radio/SSID profile per AP or SSID;
rate and security changes must be independently reversible.

### Phase 8: Migrate Protect to the UNVR-G2

- **Owner:** Protect and network operator
- **Effort:** one preparation day, one migration window, retention soak
- **Mutation:** Protect console, storage, camera adoption, and camera VLAN

1. Complete the Protect-specific audit and backups.
2. Install and burn in drives; connect the UNVR directly to the core at 10 GbE.
3. Configure roles, MFA/remote access, retention, recording, alarms, privacy,
   backup, and stream policy before moving cameras.
4. Migrate and validate one camera at a time, including the wireless G4
   Instant.
5. Update Home Assistant to the new Protect endpoint/key through its owned
   encrypted configuration and verify API, RTSPS, HLS, snapshots, and speaker
   functions.
6. Keep the UDM Pro available for rollback and retain the CloudKey as an
   isolated historical-footage source until its recording window expires.

**Validation:** all cameras continuously record, events/detections/alerts work,
playback spans the soak window, storage is healthy, backups restore, remote and
local viewing work, and only required flows cross the Camera boundary.

**Exit gate:** the UNVR has passed the full desired retention window with no
recording gaps and all consumers use it.

**Rollback:** re-adopt only the currently migrating camera to the old Protect
console if needed. Preserve both backups and do not reformat old disks/history.

### Phase 9: Deploy UNAS, desktop switch, and storage segmentation

- **Owner:** storage and network operator
- **Effort:** two to five days plus backup soak
- **Mutation:** new switch, storage, shares, client mounts, and backup jobs

1. Record the exact desktop-switch model and validate managed VLAN, RSTP, LACP,
   monitoring, and firmware capabilities.
2. Adopt it on one 10 GbE core uplink with RSTP priority 4096.
3. Connect the desktop at 10 GbE and verify its access/management separation.
4. Install UNAS drives, choose redundancy, burn in, and connect one 10 GbE core
   uplink at MTU 1500.
5. Create shares and migrate one non-critical dataset/client at a time.
6. Permit exact K3s NFSv4/SMB sources and verify workload reconnect/reboot
   behavior before critical data moves.
7. Configure snapshots, WD/offsite backups, monitoring, UPS shutdown, and a
   restore test.
8. Evaluate WD LACP only after the single-link design is stable and supported
   by both ends.

**Validation:** expected single/multi-flow throughput, no packet loss or MTU
blackholes, correct permissions, durable mounts, clean switch counters,
successful snapshots/backups/restores, and safe power-loss behavior.

**Exit gate:** storage has a tested independent backup and every client/share
path is least privilege and documented.

**Rollback:** keep source data authoritative and mounts unchanged until each
copy is verified; return the current client to the prior share/link without
deleting source data.

### Phase 10: Operationalize IDS, WAN, VPN, and telemetry

- **Owner:** security and observability operators
- **Effort:** three to five days plus 30-day tuning
- **Mutation:** alerting, exports, IDS/IPS policy, VPN/WAN configuration

1. Triage all current high/very-high IDS signatures and the k8s-rpi2 traffic.
2. Stage IPS blocking only for validated categories and test throughput.
3. Deploy the Fleet-managed UnPoller foundation with Prometheus metrics, UNAS
   polling, bounded UniFi logs, dashboards, SOPS credentials, and restrictive
   network policy. Do not enable NetFlow yet.
4. Observe several days of baseline data, reconcile device/client counts with
   a fresh controller audit, and measure Prometheus and Loki growth.
5. Run the 24- to 48-hour GoFlow2/IPFIX pilot with bounded retention. Keep it
   only if decoding, collector reliability, privacy, and storage gates pass.
6. Add alerts after measured baselines; add SNMPv3 or a mirror/Zeek sensor only
   if a documented visibility gap justifies the additional access and cost.
7. Correlate WAN failures with each ISP/modem and test failover/failback in a
   maintenance window.
8. Restore the Delhi tunnel with exact routes/firewall tests or disable it
   intentionally.
9. Reconcile DNS filtering/ad-block policy and remove name/config drift.
10. Test encrypted controller/Protect/storage backup restoration.

**Validation:** the UnPoller target is up without restarts; device and client
counts match a fresh audit; UNAS rate, drive, pool, RAID, and share metrics are
present; UNAS rate correlates with its switch port; cardinality and storage
growth remain inside the accepted budget; UniFi logs contain no secrets; IPFIX
templates decode the test flow; the collector reports no unexplained drops;
the same-VLAN blind spot is demonstrated and documented; alerts fire on
synthetic failures and clear after recovery; IPS does not break approved
traffic; WAN and VPN tests match dashboards; and backup restores are
repeatable.

**Exit gate:** every security, telemetry, WAN, and VPN alert has an owner,
severity, runbook, threshold, and evidence source; every dashboard panel states
its data source and meaningful blind spots.

**Rollback:** return only the newly enabled IPS category/export/VPN policy to
detect-only or its prior state; retain the triage evidence.

### Phase 11: Soak, retire transitional state, and close drift

- **Owner:** network operator
- **Effort:** 30-day observation plus one cleanup window
- **Mutation:** retirement and documentation cleanup

1. Observe STP, link counters, radio health, DHCP/DNS, firewall denies, IDS,
   WAN, VPN, Protect, storage, backups, and application availability for 30
   days.
2. Classify all 51 offline clients and remove only confirmed stale identities.
3. Empty VLAN 1, remove obsolete broad policies/profiles, and disable unused
   ports after dependency confirmation.
4. Retire the CloudKey only after the historical Protect window and backup
   acceptance criteria are met.
5. Update NetBox, port maps, DHCP reservations, firewall matrix, diagrams,
   runbooks, inventory, and repository READMEs to the final live state.
6. Schedule quarterly access/policy/client reviews, backup restores, firmware
   maintenance, cable/counter checks, and annual RF/failover exercises.

**Validation:** 30 days without unexplained STP events, link-speed regression,
critical firewall regression, missed recording, failed backup, unresolved
high-risk IDS event, or undocumented live drift.

**Exit gate:** the transitional VLAN/profiles/credentials are gone and the
documentation matches a fresh read-only controller audit.

**Rollback:** retirement happens one object at a time. Restore a documented
dependency only if a negative test proves it is still required.

## Acceptance Criteria

The roadmap is complete only when:

- the aggregation switch is the deterministic RSTP root and no unexplained
  loop/BPDU/STP event occurs for 30 days;
- every active uplink negotiates at its intended speed with no unexplained new
  error/drop delta;
- all switch ports are labeled and use exact access/trunk/disabled profiles;
- infrastructure, K3s, trusted, IoT, camera, storage, guest, and VPN trust
  boundaries are explicit;
- all inter-zone policy is default deny with tested, owned exceptions;
- guest isolation blocks both local networks and peer clients;
- IoT and camera peer behavior is limited to tested needs;
- Wi-Fi channel/power/width choices are survey-backed and the accidental
  125 Kb/s profile is gone;
- Network and Protect use separate least-privilege audit/workload keys and the
  temporary owner key plus exposed VPN credential are revoked;
- every high/very-high IDS event has a disposition and blocking is enabled only
  where validated;
- WAN failover and the Delhi VPN have intentional, tested states;
- the UNVR records every camera through the retention window and the old
  CloudKey is retired safely;
- the UNAS has independent, monitored, restore-tested backups;
- Grafana shows UniFi device, client, AP, switch-port, WAN, DPI, and UNAS
  metrics from a healthy Fleet-managed collector;
- dashboard saturation uses observed negotiated link speed, and telemetry
  volume, cardinality, retention, access, and blind spots are documented;
- any retained IPFIX pipeline has passed a bounded pilot with decoded known
  flows, no unexplained collector drops, and an accepted Loki storage budget;
- controller, Protect, and storage backups exist off-device and restore tests
  are current;
- no plaintext secret or raw forensic export is committed; and
- a fresh audit matches NetBox, port maps, firewall matrix, diagrams, and
  repository documentation.

## Decisions Still Required

- Exact model and managed capabilities of the arriving desktop switch.
- Final Management, Camera, Storage, and Guest subnet approval after a complete
  route/static-address conflict scan.
- Protect drive models, redundancy, desired retention, recording modes, and
  whether microphones are permitted by location.
- UNAS drive layout, usable-capacity target, snapshot retention, backup target,
  and recovery objectives.
- Exact IoT and guest speed limits after WAN and device testing.
- Whether ordinary VPN users need any Internal services and which users belong
  in the Admin VPN role.
- Stable source identity for ExternalDNS and Home Assistant firewall rules.
- Exact hostnames, Ethernet MAC addresses, switch ports, power method, and K3s
  roles for the four Raspberry Pi 5 systems arriving on 2026-08-19.
- Whether cluster control-plane/etcd membership changes are intended; adding
  worker capacity does not by itself justify changing quorum membership.
- Which IoT devices genuinely require same-L2 peers or reflected discovery.
- Whether the Delhi site-to-site VPN should be restored or intentionally
  decommissioned.
- Whether client identifiers remain readable in telemetry or are hashed.
- The acceptable Prometheus cardinality increase, flow-log retention period,
  Loki ingestion/storage budget, and threshold that ends the IPFIX pilot.
- Whether recurring same-VLAN questions justify a dedicated mirror/Zeek sensor
  and which physical port can safely receive the mirror.
- The least-privilege UNAS local role that can expose monitoring data without
  granting storage administration.
- Whether 6 GHz, fast roaming, wired ACLs, retained NetFlow, and IPS blocking
  meet the stability and operational-support bar after pilots.

## References

- [UniFi Network API getting started, 10.4.57](https://developer.ui.com/network/v10.4.57/gettingstarted)
- [USW-Pro-Max-24-PoE technical specifications](https://techspecs.ui.com/unifi/switching/usw-pro-max-24-poe)
- [USW Pro Aggregation technical specifications](https://techspecs.ui.com/unifi/switching/usw-pro-aggregation)
- [U6 Enterprise technical specifications](https://techspecs.ui.com/unifi/wifi/u6-enterprise)
- [UNAS Pro 4 technical specifications](https://techspecs.ui.com/unifi/integrations/unas-pro-4)
- [UNVR-G2 technical specifications](https://techspecs.ui.com/unifi/physical-security/unvr-g2)
- [UniFi required ports reference](https://help.ui.com/hc/en-us/articles/218506997-Required-Ports-Reference)
- [UniFi Traffic Flows and Traffic Logging](https://help.ui.com/hc/en-us/articles/32201256219799-Traffic-Flows-and-Traffic-Logging-in-UniFi-Network)
- [UniFi SNMP monitoring](https://help.ui.com/hc/en-us/articles/33502980942615-SNMP-Monitoring-in-UniFi-Network)
- [UniFi switch settings and port mirroring](https://help.ui.com/hc/en-us/articles/33402927617047-UniFi-Switch-Settings)
- [Official UniFi API introduction](https://help.ui.com/hc/en-us/articles/30076656117655-Getting-Started-with-the-Official-UniFi-API)
- [UnPoller v4.0.0 release](https://github.com/unpoller/unpoller/releases/tag/v4.0.0)
- [UnPoller v4.0.1 release](https://github.com/unpoller/unpoller/releases/tag/v4.0.1)
- [UnPoller configuration example](https://github.com/unpoller/unpoller/blob/v4.0.1/examples/up.conf.example)
- [UnPoller UNAS input](https://github.com/unpoller/unpoller/blob/v4.0.1/pkg/inputunas/README.md)
- [GoFlow2 collector](https://github.com/netsampler/goflow2/blob/main/README.md)
- [Zeek live-traffic quick start](https://docs.zeek.org/en/v8.2.1/quickstart.html)
- [UniFi Protect backups and migration](https://help.ui.com/hc/en-us/articles/360008976393-Backups-and-Migration-in-UniFi)
- [How UniFi Protect protects data](https://help.ui.com/hc/en-us/articles/31234972188951-How-UniFi-Protect-Protects-Your-Data)
- [WD My Cloud EX4100 data sheet](https://documents.westerndigital.com/content/dam/doc-library/en_us/assets/public/wd/product/nas/my_cloud/my_cloud_ex4100/data-sheet-my-cloud-expert-series-ex4100.pdf)
- [UniFi LAN integration notes](../../infrastructure/network/unifi/README.md)
