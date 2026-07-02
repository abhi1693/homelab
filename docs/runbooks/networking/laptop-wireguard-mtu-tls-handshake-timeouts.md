---
title: Laptop WireGuard MTU TLS Handshake Timeouts
---

# LaptopWireGuardMtuTlsHandshakeTimeouts

## Meaning

The operator laptop can route to the home lab over a NetworkManager-managed
WireGuard interface, but the tunnel MTU is too large for the current underlay.
The oversized packets are blackholed or badly delayed, so TLS handshakes to the
K3s API server and `*.home` ingresses stall even though TCP connects and DNS
resolution work.

This is a client-side laptop VPN issue, not a Kubernetes workload or Fleet
reconciliation issue.

Known affected paths:

- Kubernetes API: `https://192.168.3.2:6443`
- Traefik ingress VIP: `192.168.3.3`
- Internal hostnames such as `rancher.home`

## Impact

- `kubectl get nodes` and other Kubernetes API calls fail with TLS or client
  timeout errors.
- `https://*.home` pages hang during TLS setup or load only after long delays.
- Operators may misdiagnose healthy cluster services as down because DNS and
  TCP connection setup can still succeed.

## Diagnosis

Confirm the route uses a WireGuard VPN interface:

```sh
ip route get 192.168.3.2
ip route get 192.168.3.3
nmcli -t -f NAME,TYPE,DEVICE,STATE connection show --active
```

Expected bad signal:

```text
192.168.3.2 dev wg... table 51820 src 192.168.2.2
wg...:wireguard:wg...:activated
```

Check the active WireGuard MTU:

```sh
ip -d link show <wireguard-interface>
nmcli device show <wireguard-interface> | sed -n '1,40p'
```

Expected bad signal:

```text
wg... mtu 1420
GENERAL.MTU: 1420
```

Confirm DNS resolves through the VPN:

```sh
resolvectl query rancher.home
```

Expected signal:

```text
rancher.home: 192.168.3.3 -- link: wg...
```

Reproduce the TLS symptoms with short timeouts:

```sh
kubectl get nodes --request-timeout=8s
curl -kIv --connect-timeout 5 --max-time 8 https://rancher.home/
```

Known failure examples:

```text
net/http: TLS handshake timeout
net/http: request canceled while waiting for connection
Client.Timeout exceeded while awaiting headers
```

For ingress, `curl -kIv` may show TCP connect and TLS ClientHello before
stalling:

```text
Connected to rancher.home (192.168.3.3) port 443
TLSv1.3 (OUT), TLS handshake, Client hello (1)
SSL connection timeout
```

## Mitigation

Lower the laptop WireGuard MTU to `1280`. This value is conservative and works
across IPv4, IPv6, WireGuard, and variable WAN or hotspot underlays.

Apply the fix to the currently active interface:

```sh
sudo ip link set dev <wireguard-interface> mtu 1280
```

Persist the MTU on the active NetworkManager connection:

```sh
nmcli connection modify <wireguard-connection-name> wireguard.mtu 1280
```

If the VPN client creates new random `wg...` NetworkManager profiles, update all
existing WireGuard profiles:

```sh
nmcli -t -f NAME,TYPE connection show \
  | awk -F: '$2=="wireguard" {print $1}' \
  | while IFS= read -r name; do
      nmcli connection modify "$name" wireguard.mtu 1280
    done
```

Install a NetworkManager dispatcher hook so newly created WireGuard interfaces
also get the safe MTU:

```sh
sudo tee /etc/NetworkManager/dispatcher.d/90-wireguard-mtu >/dev/null <<'EOF'
#!/bin/sh

IFACE="$1"
ACTION="$2"
MTU=1280
IP=/usr/sbin/ip
GREP=/usr/bin/grep

case "$ACTION" in
  up|vpn-up|reapply)
    ;;
  *)
    exit 0
    ;;
esac

[ -n "$IFACE" ] || exit 0
[ -d "/sys/class/net/$IFACE" ] || exit 0

if "$IP" -d link show dev "$IFACE" 2>/dev/null | "$GREP" -qw wireguard; then
  "$IP" link set dev "$IFACE" mtu "$MTU"
fi
EOF

sudo chmod 0755 /etc/NetworkManager/dispatcher.d/90-wireguard-mtu
sudo chown root:root /etc/NetworkManager/dispatcher.d/90-wireguard-mtu
```

Run the dispatcher hook once for the active interface:

```sh
sudo /etc/NetworkManager/dispatcher.d/90-wireguard-mtu \
  <wireguard-interface> up
```

Do not mutate the cluster to repair this symptom. The failure is on the laptop
VPN path.

## Verification

Check the live interface:

```sh
ip -d link show <wireguard-interface>
```

Expected result:

```text
wg... mtu 1280
```

Check the NetworkManager profile:

```sh
nmcli -f connection.id,wireguard.mtu connection show <wireguard-connection-name>
```

Expected result:

```text
wireguard.mtu: 1280
```

Check Kubernetes API access:

```sh
kubectl get nodes --request-timeout=12s
```

Expected result:

```text
NAME       STATUS   ROLES                AGE   VERSION
k8s-rpi1   Ready    control-plane,etcd   ...
```

Check ingress TLS:

```sh
curl -kIs --connect-timeout 4 --max-time 6 https://rancher.home/
```

Expected result:

```text
HTTP/2 200
```

## Rollback

Remove the dispatcher hook:

```sh
sudo rm -f /etc/NetworkManager/dispatcher.d/90-wireguard-mtu
```

Return a NetworkManager WireGuard profile to automatic MTU selection:

```sh
nmcli connection modify <wireguard-connection-name> wireguard.mtu 0
```

Optionally reset the live interface to NetworkManager's usual WireGuard default
until the next reconnect:

```sh
sudo ip link set dev <wireguard-interface> mtu 1420
```

Reconnect the VPN after rollback and re-run the diagnosis commands.

## References

- NetworkManager WireGuard `wireguard.mtu` setting: https://networkmanager.dev/docs/api/latest/nm-settings-nmcli.html
- NetworkManager dispatcher scripts: https://networkmanager.dev/docs/api/1.44.4/NetworkManager-dispatcher.html
