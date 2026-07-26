# MetalLB

MetalLB owns LAN-facing Kubernetes `LoadBalancer` addresses. The chart is
installed by a Fleet `HelmOp`; the separate `metallb-config` bundle owns
address pools and Layer 2 advertisements only after the MetalLB CRDs and
workloads are ready.

The installation intentionally leaves `loadBalancerClass` empty. This lets
MetalLB adopt classless services such as Traefik and the qBittorrent torrent
listener. Services request a pool and fixed address through
`metallb.io/address-pool` and `metallb.io/loadBalancerIPs` annotations.

The deployment uses ARP-based Layer 2 announcements. Speaker pods run on every
K3s node, while the controller performs address allocation. The node network
must allow MetalLB memberlist traffic on TCP and UDP `7946` between K3s nodes.

## Reconciliation and validation

1. Reconcile `metallb-helmop` and wait for the controller Deployment and
   speaker DaemonSet to become ready.
2. Reconcile `metallb-config` and verify the two address pools and Layer 2
   advertisement.
3. Reconcile the qBittorrent bundle and confirm
   `media/qbittorrent-torrent` remains on `192.168.3.16`.
4. Run the Ansible Cilium validation entrypoint and confirm Traefik remains on
   `192.168.3.3`.
5. From a LAN client, resolve a `*.home` name, open an HTTPS endpoint, and test
   the qBittorrent peer ports.
6. Repeat the LAN checks during a controlled WAN disconnect.
