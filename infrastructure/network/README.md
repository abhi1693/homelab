# Network Infrastructure

This directory holds network-side configuration and notes that sit outside the
Kubernetes API.

## What Lives Here

| Path | Purpose |
| --- | --- |
| `unifi/` | UniFi VLAN assumptions and operational notes for Layer 2 service VIP advertisement. |

## Why This Exists

The cluster declares LoadBalancer services and MetalLB advertises their VIPs on
the cluster VLAN. The LAN gateway only needs its normal connected VLAN and
inter-VLAN routing; no Kubernetes-specific dynamic routing is required.

Network files here document the assumptions that must match the Kubernetes
configuration:

- Traefik ingress VIP.
- App LoadBalancer pool.
- Cluster VLAN and gateway address.
- Inter-VLAN firewall requirements.
- Optional break-glass access-port behavior.

## How It Fits The Cluster

1. MetalLB allocates explicitly requested service VIPs from declared pools.
2. One eligible MetalLB speaker answers ARP for each VIP on `eth0`.
3. The UniFi gateway routes between its directly connected VLANs.
4. LAN clients reach `*.home` and app service VIPs through ordinary
   connected-VLAN routing.
5. ExternalDNS keeps internal DNS records aligned with Ingress hosts.

The network layer is therefore coupled to MetalLB, Traefik, ExternalDNS, and
the app LoadBalancer pool. When one changes, review the VLAN, DNS, and firewall
assumptions.
