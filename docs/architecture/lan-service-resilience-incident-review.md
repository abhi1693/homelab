# LAN service resilience during an ISP outage

- Status: accepted architecture decision and learning review
- Incident reported: 2026-07-23; the exact outage interval was not captured
- Migration completed: 2026-07-23
- Decision: advertise Kubernetes service VIPs with MetalLB Layer 2 mode

## Executive summary

An ISP outage was followed by an unexpected loss of access to LAN-hosted
Kubernetes services. The workloads and service addresses were local, but the
path to those addresses was not fully local to Kubernetes: Cilium advertised
the service VIPs to a single UniFi Dream Machine Pro using BGP, and clients on
other VLANs depended on the UDM retaining those learned routes.

The former design was not unreasonable. It had three independent Cilium
speakers, conservative prefix filtering, 30-second keepalives, a 90-second hold
timer, and a 120-second graceful-restart window. Those measures protected
against several speaker and node failures. They did not remove the UDM routing
process as the only consumer of every service route. If the UDM withdrew,
flushed, or stopped using those routes while reacting to WAN loss, every
otherwise healthy service VIP became unreachable at the same boundary.

The incident did not include a retained UDM route-table snapshot or
incident-time FRR logs. It is therefore not possible to prove the exact
internal UDM sequence after the fact. The strongest supported conclusion is:

- the user-observed trigger was loss of ISP connectivity;
- LAN service access failed at the same time;
- the cluster topology made the UDM's learned service routes a shared
  dependency;
- no evidence showed a simultaneous Kubernetes workload or data failure; and
- removing that shared dependency is the smallest architecture change that
  directly addresses the observed failure mode.

MetalLB now answers ARP for each service VIP from a K3s node on `eth0`. The UDM
only performs ordinary connected-VLAN routing. WAN state is no longer part of
service VIP ownership. A controlled physical WAN-disconnect test is still
required before claiming the new design has passed its final resilience
acceptance test.

## Impact

Expected impact:

- internet destinations were unavailable during the ISP outage.

Unexpected impact:

- the operator reported losing access to LAN-hosted services as well;
- ingress through `192.168.3.3` and application-specific VIPs were within the
  affected path; and
- internal services appeared down even though their addresses and workloads
  lived on the cluster VLAN.

There is no evidence of data loss. The available evidence also does not show
that K3s, Cilium's pod dataplane, Traefik, or the application pods all failed
during the ISP outage. This was an access-path incident, not a demonstrated
cluster-wide compute failure.

## Why a local VLAN did not make the old path local

The old path differed by client location:

```text
client on another VLAN
  -> UDM inter-VLAN gateway
  -> learned /32 service route
  -> selected K3s node
  -> Service endpoint
```

A service VIP such as `192.168.3.3` was inside the cluster VLAN's address
range, but it was not assigned to the UDM or to a permanent node interface.
For an inter-VLAN client, the UDM still had to decide which K3s node owned that
host route. The fact that the destination address was RFC1918 and on a local
VLAN did not remove that routing decision.

A client directly attached to the cluster VLAN would ARP for the VIP instead
of sending it through its default gateway. The former design did not have an
independent Layer 2 announcer for those VIPs. That path therefore depended on
router proxy behavior or was not a supported direct-client path. In both
cases, "the VIP is in my local subnet" was not the same as "a cluster node
directly owns the VIP on this subnet."

Internal DNS could amplify the symptom if a client also lost access to the
UDM's resolver, but DNS alone does not explain the architecture's dependency
on learned VIP routes. An incident-time test by literal IP was not preserved,
so the review does not claim DNS was or was not an additional factor.

## What the former design was expected to survive

The BGP design had real resilience properties:

- three control-plane nodes (`192.168.3.243`, `192.168.3.191`, and
  `192.168.3.108`) could advertise the service addresses;
- the UDM accepted only `192.168.3.3/32` and addresses within
  `192.168.3.16/29`, limiting accidental route propagation;
- the cluster and router used separate private ASNs, `65001` and `65000`;
- the peer timers were a 30-second keepalive and 90-second hold time; and
- graceful restart was enabled with a 120-second restart window.

That redundancy covered the advertising side. Losing one K3s node did not
necessarily remove a VIP because another speaker could advertise it. Graceful
restart could preserve forwarding during a cooperative, transient speaker
restart when both peers retained the required state.

It did not provide two independent route consumers. All three sessions ended
on the same UDM and the same routing process. Graceful restart is also not a
guarantee that routes survive a router daemon reset, RIB flush, forwarding
reprogramming, WAN-driven configuration transition, or a restart in which the
helper state itself is lost. Multiple speakers protected against node failure;
they did not protect against their single shared upstream boundary.

This distinction is the central lesson: high availability must be evaluated
across failure domains, not by counting replicas inside one side of a
dependency.

## Evidence from the former topology

The state immediately before migration is preserved in the parent of commit
`cd959fdc`:

| Evidence | Observed value | Why it matters |
| --- | --- | --- |
| Cilium values | `bgpControlPlane.enabled: true` | Cilium, not a Layer 2 speaker, owned service advertisement. |
| Traefik service class | `io.cilium/bgp-control-plane` | Traefik explicitly selected the Cilium advertisement path. |
| Ingress VIP | `192.168.3.3` | The primary `*.home` ingress depended on that path. |
| App VIP pool | `192.168.3.16-192.168.3.23` | Non-HTTP LoadBalancer services used the same route consumer. |
| Cluster ASN | `65001` | The three selected control-plane nodes were route speakers. |
| UDM ASN | `65000` | The UDM was the upstream route consumer. |
| UDM peers | `.243`, `.191`, `.108` | Every speaker session terminated on the same router. |
| Prefix filter | `.3/32` and `.16/29 le 32` | Only intended service addresses were accepted. |
| Timers | keepalive `30`, hold `90`, restart `120` seconds | The design explicitly attempted to tolerate transient restarts. |

The generated Cilium resources selected all control-plane nodes, created one
peer to `192.168.3.1`, advertised Traefik's LoadBalancer IP, and advertised
LoadBalancer IPs outside `kube-system`. The UDM configuration activated all
three neighbors and applied the same inbound prefix list to each.

The fourth current K3s node, `k8s-rpi4` at `192.168.3.135`, is a worker and did
not match the former control-plane selector. Its absence from the old UDM peer
list was therefore consistent with the declared topology, not evidence of the
incident's cause.

## Root cause and contributing factors

### Root cause

LAN service VIP reachability had a hidden shared dependency on the UDM's
dynamic route state. The ISP outage was the observed trigger. The architecture
allowed a WAN-related change at that router boundary to remove access to local
service addresses even while Kubernetes remained available.

The exact UDM defect or restart sequence is not proven because the following
incident-time evidence was not retained:

- UDM routing-daemon logs;
- the UDM route table before and during the outage;
- peer state at the moment access failed;
- packet captures showing whether the failure was DNS, ARP, route lookup, or a
  combination; and
- literal-IP tests from both the cluster VLAN and another LAN VLAN.

The conclusion is intentionally architectural rather than vendor-diagnostic:
the UDM route state was a dependency it did not need to be, and the observed
failure crossed that dependency.

### Contributing factors

1. **Failure-domain accounting stopped at the cluster.** Three speakers looked
   redundant, but their only upstream route consumer remained singular.
2. **The address plan obscured the routed dependency.** Because the VIPs used
   `192.168.3.x`, it was easy to assume they behaved like ordinary hosts on the
   cluster VLAN. They did not have permanent interface ownership there.
3. **Graceful restart was treated too broadly.** Its timer protected a
   cooperative protocol restart, not every way the router could react to WAN
   loss.
4. **The failure mode was not fault-injected.** The design was validated for
   healthy peer establishment and service reachability, but not by physically
   removing the ISP link while testing LAN clients.
5. **Observability ended at the Kubernetes boundary.** Cluster health checks
   could remain green while the UDM no longer delivered traffic to service
   VIPs.

## Decision and current architecture

MetalLB `v0.16.1` owns the service VIPs in Layer 2 mode:

```text
client on another VLAN
  -> UDM ordinary connected route for the cluster VLAN
  -> ARP request on the cluster VLAN
  -> MetalLB speaker on an eligible K3s node
  -> Service endpoint
```

The declared address model is:

| Pool | Addresses | Allocation |
| --- | --- | --- |
| `ingress-services` | `192.168.3.3/32` | Explicit Traefik VIP |
| `app-services` | `192.168.3.16-192.168.3.23` | Explicit app VIPs |

Both pools have automatic allocation disabled. The `lan` Layer 2 advertisement
announces both pools only on `eth0`. Traefik and qBittorrent use
`externalTrafficPolicy: Local`, allowing the elected speaker to forward to a
local endpoint. Speaker memberlist uses TCP and UDP `7946` between K3s nodes.

Cilium remains the CNI, kube-proxy replacement, NetworkPolicy engine, and
Hubble dataplane. It no longer allocates or advertises LAN service VIPs.

This design deliberately accepts a different tradeoff:

- it is simpler and removes the router's dynamic route process from service
  ownership;
- one speaker answers ARP for a VIP at a time, so failover depends on neighbor
  cache refresh and gratuitous ARP rather than route convergence;
- inter-VLAN clients still require the UDM to be powered on and capable of
  ordinary LAN routing; and
- it does not promise availability through a full UDM reboot.

The design specifically targets ISP loss without loss of the LAN gateway.

## Migration chronology and controls

All times below are 2026-07-23 in Asia/Kolkata.

| Time | Commit or observation | Result |
| --- | --- | --- |
| 20:06 | `cd959fdc` | Added MetalLB, address pools, Layer 2 advertisement, classless service configuration, and a guarded handoff. |
| 20:10 | `c9855c9e` | Removed qBittorrent's unrelated media catalog dependency so a stale repository failure could not block service exposure. |
| 20:19 | `f09a7034` | Fixed the immutable Traefik Service handoff after the packaged Helm controller restored the previous class and produced a failed upgrade. |
| 20:21 | `9f7eb062` | Made Cilium reconciliation compare live state as well as the rendered values file after an interrupted run exposed their mismatch. |
| 20:24 | `c0a360e3` | Normalized Cilium's absent live configuration key as the disabled default. |

The guarded order mattered. MetalLB's controller, speakers, pools, and
classless-service behavior were checked before the Cilium path was disabled.
When the first Traefik handoff hit Kubernetes' immutable
`loadBalancerClass`, the guard stopped the migration rather than withdrawing
the working provider prematurely.

One Fleet obstacle was unrelated to networking: qBittorrent was coupled to a
stale `media-helm-repositories` resource whose `seerr-team` source failed a
`ghcr.io` DNS lookup. The chart itself used a direct OCI reference. Removing
that irrelevant dependency allowed the service bundle to reconcile without
weakening the actual chart source.

The migration also exposed an automation failure mode. An interrupted Ansible
run had already rendered the desired disabled value locally, while the live
Cilium configuration was still enabled. A file-change-only condition would
have skipped the required upgrade. The follow-up reconciliation used live
state, completed the rollout, and then normalized the disabled default.

These were migration defects, not explanations for the original ISP outage.
They are included because the handoff evidence would be incomplete without
them.

## Post-migration evidence

Live checks performed after the migration on 2026-07-23 established:

| Check | Result |
| --- | --- |
| Fleet bundles | `metallb`, `metallb-config`, `metallb-helmop`, `qbittorrent`, and `qbittorrent-helmop` each reported `1/1`. |
| MetalLB controller | Deployment `1/1`, image `quay.io/metallb/controller:v0.16.1`. |
| MetalLB speakers | DaemonSet `4/4`, one ready speaker on every K3s node. |
| Pools | `ingress-services` and `app-services` present with automatic allocation disabled. |
| Layer 2 advertisement | `lan` selected both pools on `eth0`. |
| Traefik | Classless, pool `ingress-services`, `Local`, VIP `192.168.3.3`. |
| qBittorrent | Classless, allocated from `app-services`, `Local`, VIP `192.168.3.16`, TCP and UDP `53181`. |
| Layer 2 ownership | Traefik elected `k8s-rpi1`; qBittorrent elected `k8s-rpi2`. |
| Endpoint locality | Traefik had endpoints on `k8s-rpi1` and `k8s-rpi4`; qBittorrent had an endpoint on `k8s-rpi2`. |
| Former Cilium resources | Cluster, peer, advertisement, and Cilium LoadBalancer pool queries returned no objects. |
| Cilium Helm value | `bgpControlPlane.enabled: false`. |
| Cilium ConfigMap | The corresponding key was absent, which is the disabled default. |
| Internal DNS | `rancher.home` resolved to `192.168.3.3`. |
| HTTPS path | `https://rancher.home` returned HTTP `200` from `192.168.3.3`. |
| App VIP path | TCP connection to `192.168.3.16:53181` succeeded. |
| Migration validation | Final migration run completed `50` checks with `0` changes and `0` failures. |
| Cleanup validation | The reference-removal run completed `45` checks with `0` changes and `0` failures. |
| Recent logs | No MetalLB controller or speaker warnings/errors appeared in the final five-minute check. |

During initial allocation at `14:50:41Z`, the MetalLB controller logged
optimistic-concurrency retries because Service and pool objects were modified
simultaneously. It subsequently assigned both VIPs and converged. Those
transient errors were not present in the final five-minute log check.

The Services retain a non-fatal Cilium IPAM status condition stating that no
Cilium pool matches. The authoritative `status.loadBalancer.ingress` values,
MetalLB allocation annotations, Layer 2 status resources, endpoint locality,
and real client connections all show that MetalLB owns the working path. The
condition is historical status noise, not a current allocation failure.

## What is proven and what remains to prove

Proven:

- the former topology depended on one UDM route consumer;
- the new topology gives every K3s node an eligible Layer 2 speaker;
- both VIPs are allocated, announced, endpoint-local, and reachable on the LAN;
- internal DNS and HTTPS work through the Traefik VIP;
- the qBittorrent TCP peer port works through its app VIP; and
- Cilium no longer owns the LAN VIP resources.

Not yet proven:

- continued DNS, HTTPS, and app-VIP access during a physical ISP disconnect;
- failover time after disconnecting the currently elected speaker's Ethernet
  link;
- behavior from every trusted client VLAN; and
- whether any obsolete UDM FRR configuration or port `179` firewall exception
  remains outside this repository.

The migration removes the identified WAN-coupled route dependency, but the
first item is the acceptance test for the original incident. It must not be
replaced by inference from a healthy connected state.

## Required follow-up

1. Remove any obsolete UDM BGP configuration and the firewall exception used
   only for TCP `179`, if either still exists.
2. From a client on a normal trusted VLAN, record successful DNS resolution,
   `https://rancher.home`, `192.168.3.3:443`, and
   `192.168.3.16:53181`.
3. Physically disconnect only the WAN link. Repeat the same tests for at least
   five minutes while confirming the UDM and all K3s nodes remain powered.
4. Reconnect the WAN and confirm there was no interruption or manual recovery
   of LAN services.
5. In a separate maintenance window, test speaker failover by disconnecting
   the elected node rather than the WAN.
6. Alert on unavailable MetalLB speakers, missing Layer 2 status, or a
   LoadBalancer Service without its declared VIP.

For break-glass diagnosis, a spare UDM Pro port can use the cluster VLAN's
access profile. A laptop attached there can distinguish direct cluster-VLAN
reachability from inter-VLAN gateway or DNS problems. It is a diagnostic path,
not high availability for a full UDM outage.

## Learning

BGP was a technically valid way to distribute service routes, and the
configuration included sensible redundancy and timers. It failed the actual
resilience goal because the design goal was broader than the protocol property:
LAN services were expected to survive an ISP outage, while every route still
converged on the device whose behavior changed during that outage.

The better question is not "is this protocol resilient?" It is "which
component is allowed to remove reachability for all local services, and does
that component share fate with the failure we are trying to survive?"

For this cluster, Layer 2 ownership is the more appropriate boundary. It keeps
service ownership on the cluster VLAN, uses the UDM only for ordinary LAN
routing, and makes WAN loss irrelevant to the mechanism that answers for a
service VIP.
