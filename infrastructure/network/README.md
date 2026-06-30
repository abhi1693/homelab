# Network Infrastructure

This directory holds network-side configuration and notes that sit outside the
Kubernetes API.

## What Lives Here

| Path | Purpose |
| --- | --- |
| `unifi/` | UniFi gateway BGP configuration and operational notes for service VIP advertisement. |

## Why This Exists

The cluster can declare LoadBalancer services and Cilium can advertise those
VIPs, but the LAN gateway still has to accept and route those advertisements.
That router-side state is not reconciled by Fleet or Ansible in this repo.

Network files here document the assumptions that must match the Kubernetes
configuration:

- BGP local and peer ASNs.
- Control-plane node peer addresses.
- Accepted LoadBalancer VIP prefixes.
- Traefik ingress VIP.
- App LoadBalancer pool.
- Firewall requirements for BGP TCP port `179`.

## How It Fits The Cluster

1. Cilium allocates service VIPs through LoadBalancer IPAM.
2. Cilium BGP advertises those VIPs from the K3s nodes.
3. The UniFi gateway accepts only the expected prefixes.
4. LAN clients route `*.home` and app service VIP traffic through the gateway.
5. ExternalDNS keeps internal DNS records aligned with Ingress hosts.

The network layer is therefore coupled to Cilium, Traefik, ExternalDNS, and the
app LoadBalancer pool. When one of those changes, the router-side assumptions
should be reviewed.
