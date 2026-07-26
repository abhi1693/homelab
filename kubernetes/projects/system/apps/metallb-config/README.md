# MetalLB Layer 2 configuration

This bundle owns the LAN address pools and the ARP-based Layer 2 advertisement
used by MetalLB.

| Pool | Addresses | Allocation |
| --- | --- | --- |
| `ingress-services` | `192.168.3.3/32` | Explicitly requested by Traefik only. |
| `app-services` | `192.168.3.16-192.168.3.23` | Explicitly requested by app-specific LoadBalancer services. |

Both pools disable automatic allocation. A Service must request its address
with `metallb.io/loadBalancerIPs`; this prevents an unrelated LoadBalancer from
silently consuming a LAN address. The `lan` advertisement is restricted to the
nodes' physical `eth0` interface.

Current fixed app allocations:

| VIP | Service | Ports |
| --- | --- | --- |
| `192.168.3.16` | `media/qbittorrent-torrent` | `53181/TCP`, `53181/UDP` |

This bundle depends on `metallb-helmop`, so Fleet does not apply the custom
resources before the MetalLB CRDs are installed.
