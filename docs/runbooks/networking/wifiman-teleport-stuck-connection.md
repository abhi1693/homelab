---
title: WiFiman Teleport Stuck Connecting or Disconnecting
---

# WiFiman Teleport Stuck Connecting or Disconnecting

## Meaning

WiFiman Desktop can leave a local WireGuard interface and its `wg-quick-*`
firewall tables behind after an interrupted or failed Teleport session. The
desktop app, background service, and operating system can then disagree about
whether the VPN is connected. Restarting only the app or service may preserve
that stale state.

Use this runbook for a Linux laptop whose WiFiman window remains on
**Connecting…** or **Disconnecting…**, or repeatedly connects and drops. It
covers local diagnosis and removal of an identified inactive WiFiman tunnel.
It does not authorize gateway, AP, firewall-controller, or cluster changes.

Recovery was verified on **2026-09-08**, using Ubuntu, systemd,
NetworkManager, and **WiFiman Desktop 1.2.8**. The observed sequence was:

1. WiFiman logged `Teleport connected successfully`, and IPv4 home-lab traffic
   worked, while the window still displayed **Connecting…**.
2. Later attempts logged ten consecutive UDP echo timeouts, followed by
   `TELEPORT_UDP_ECHO_FAILED`, teardown, and automatic retries.
3. An old WireGuard interface remained down without addresses, with its two
   nftables tables still present. App/service restarts had not removed it.
4. Stopping both processes, removing that inactive interface and its exact
   tables, then reconnecting produced a new interface and working IPv6 health
   replies. The window showed **Connected**; over six minutes passed without
   health-probe failures or reconnects.

This establishes a successful local recovery, not a vendor-confirmed explanation
of the original failure. A UDP echo timeout by itself does not prove stale
firewall state or a gateway outage.

## Impact

- Home-lab access may fail, work briefly, or disappear during automatic retries.
- A green gateway icon, a running service, or a single successful API request
  can conceal an incomplete connection.
- Full-tunnel routes can also affect ordinary internet access.
- Recovery interrupts this laptop's Teleport session. Run it from the laptop's
  local desktop, not through a remote session that depends on that VPN.

## Diagnosis

### 1. Inspect the app, service, and actual interfaces

Use a local terminal with `sudo` access. Required tools are `systemctl`,
`ip`, `nmcli`, `nft`, Python 3, and `ping`; `kubectl` and `tcpdump` are optional.
The cleanup below uses an explicit Bash session.

```bash
date -Is
dpkg-query -W -f='${Package} ${Version}\n' wifiman-desktop
systemctl show wifiman-desktop.service \
  -p ActiveState -p SubState -p MainPID -p NRestarts
nmcli -f NAME,TYPE,DEVICE connection show --active
ip -d link show type wireguard
ip -brief address
ip rule show
ip -6 rule show
ip route get 192.168.3.2
```

Observe the actual WiFiman window and selected destination. For this home lab,
the expected destination is **Home - UDM Pro**. Other saved gateways need their
own reachability targets.

An established home-lab tunnel should route `192.168.3.2` through its current
`wg...` interface. A route through the Wi-Fi gateway alone does not establish
Teleport connectivity. Inspect all WireGuard links: `nmcli --active` can omit
an inactive leftover interface.

For transfer counters, the bundled utility is available even when `wg` is not
on the shell's PATH:

```bash
sudo /usr/lib/wifiman-desktop/wg show \
  | rg 'interface:|transfer:'
```

The bundled 1.2.8 utility's output differs from standard WireGuard tools. Do
not assume tabular `wg show all latest-handshakes` or `dump` parsing works.
Never use `showconf` or print private keys for an incident report.

### 2. Read connection events without exposing credentials

The application log is more useful than the service journal for connection
failures. It can also contain authentication material, invitation secrets,
WireGuard configuration, and MQTT payloads. Do not paste or commit raw logs,
`service.json`, or generated `.conf` files.

This projection prints only timestamps and known event labels:

```bash
python3 - <<'PY'
from pathlib import Path
import re

events = (
    'Tauri: Connecting teleport',
    'Tauri: Disconnecting teleport',
    'Teleport connected successfully',
    'Teleport disconnected successfully',
    'Teleport connection timeout',
    'TELEPORT_CONNECTION_NOT_FOUND',
    "Couldn't read UDP echo response",
    'Unmatched UDP echo response',
    'TELEPORT_UDP_ECHO_FAILED',
    'Stopping teleport',
    'Teleport.Off completed',
    'wg config file not found',
)
path = Path('/usr/lib/wifiman-desktop/wifiman-desktop.log')
rows = []
for line in path.read_text(errors='replace').splitlines():
    if not re.match(r'^\d{4}-\d{2}-\d{2}T\S+ ', line):
        continue
    for event in events:
        if event in line:
            rows.append(f'{line.split()[0]} {event}')
            break
print('\n'.join(rows[-80:]))
PY
```

| Finding | Next step |
| --- | --- |
| Service runs, but there is no usable tunnel | Inspect the setup events; service health alone is insufficient. |
| Success followed by ten UDP echo timeouts and teardown | Investigate the IPv6 health path and leftover local state below. |
| App spinner persists while traffic works | Compare the app with sustained health-probe results; brief IPv4 success does not clear the incident. |
| `wg config file not found` during teardown | Inspect links and nftables separately; a missing temporary file does not prove cleanup completed. |
| `TELEPORT_CONNECTION_NOT_FOUND` persists after refreshing the connection list | Validate the selected gateway and account/invitation access; do not delete saved connections as the first action. |
| Tunnel stays connected, but large TLS exchanges stall | Use the [WireGuard MTU runbook](laptop-wireguard-mtu-tls-handshake-timeouts.md). |

### 3. Identify the exact tunnel and its firewall tables

Start Bash, then enter the interface identified from current WiFiman events,
routes, and link state. Random interface names from a previous incident must
not be reused. A `wg...` name alone does not prove WiFiman owns it.

```bash
bash
read -r -p 'Current WiFiman interface to inspect: ' TELEPORT_IFACE
ip -d address show dev "$TELEPORT_IFACE"
sudo nft list tables
sudo nft list table ip "wg-quick-$TELEPORT_IFACE"
sudo nft list table ip6 "wg-quick-$TELEPORT_IFACE"
```

The tables normally include rules scoped to the interface and VPN client
addresses. They are expected while that tunnel is in use. Leftover rules can
also interfere with a replacement tunnel using the same client addresses, so
do not treat them as harmless merely because the old interface is down.

Stop if ownership is uncertain. Do not flush nftables, remove every `wg*`
interface, delete unrelated NetworkManager profiles, or clear shared policy
tables such as `51820` by number.

### 4. Distinguish IPv6 health failure from general tunnel failure

During a connection attempt, obtain the echo destination and UDP port from the
current timeout event locally. These values are session-specific; the observed
port was `47411`, but it must be checked again.

```bash
read -r -p 'IPv6 echo destination from the current WiFiman event: ' TELEPORT_ECHO_ADDR
read -r -p 'UDP echo port from that event: ' TELEPORT_ECHO_PORT
ip -6 route get "$TELEPORT_ECHO_ADDR"
ping -6 -n -c 3 -W 2 "$TELEPORT_ECHO_ADDR"
```

Expected: the destination routes through the current tunnel. ICMP replies help
establish IPv6 reachability; the app's UDP replies are the decisive health check.
For a bounded packet-header trace while connecting:

```bash
sudo timeout 20 tcpdump -nn -i "$TELEPORT_IFACE" -c 30 \
  "ip6 and udp port $TELEPORT_ECHO_PORT"
```

Expected: outbound probes and inbound replies. Timeout exit code `124` only
means the capture duration ended. Do not add payload-printing flags or export
a packet capture containing unrelated traffic. If the interface changes,
select the new name before repeating a check.

## Mitigation

### 1. Stop retries and both WiFiman components

Quit the desktop app using its tray/menu **Quit** action. Closing its window
may leave it running. If it will not quit, send `TERM` only to the current
user's desktop process, then stop the background service:

```bash
pkill -TERM -u "$(id -u)" -f '^(/usr/bin/)?wifiman-desktop([[:space:]]|$)'
sudo timeout 20 systemctl stop wifiman-desktop.service
systemctl show wifiman-desktop.service -p ActiveState -p SubState
```

`pkill` returning `1` means no matching desktop process remained. Expected
service state: `inactive` / `dead`. If stopping times out, inspect
`journalctl -u wifiman-desktop.service -n 30 --no-pager` and wait for the stop
job; do not start another copy or proceed while it is stopping.

### 2. Remove only the confirmed inactive tunnel and its exact tables

Recheck the interface after stopping WiFiman. This recovery requires the old
interface to be **down with no assigned addresses**. If it remains up or has
addresses, stop and determine whether NetworkManager or another VPN still owns
it. Do not force it down just to satisfy the guard.

The block below checks those conditions, saves only the matching firewall
tables in a private temporary directory, and removes the inactive interface
and those tables. It preserves account data, invitations, and other VPNs.
Keep the same Bash session and `TELEPORT_IFACE` selected during diagnosis.

```bash
sudo -v
python3 - "$TELEPORT_IFACE" <<'PY'
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

iface = sys.argv[1]
if not re.fullmatch(r'wg[0-9a-f]{8}', iface):
    sys.exit('STOP: select the exact WiFiman interface from current evidence')

def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout

state = run('systemctl', 'show', 'wifiman-desktop.service',
            '-p', 'ActiveState', '--value').strip()
if state != 'inactive':
    sys.exit('STOP: WiFiman service must be inactive')
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        if (proc.stat().st_uid == os.getuid()
                and (proc / 'exe').resolve() == Path('/usr/bin/wifiman-desktop')):
            sys.exit('STOP: quit the WiFiman desktop app first')
    except OSError:
        continue

links = json.loads(run('ip', '-d', '-j', 'address', 'show', 'dev', iface))
if len(links) != 1:
    sys.exit('STOP: expected one existing interface')
link = links[0]
if link.get('linkinfo', {}).get('info_kind') != 'wireguard':
    sys.exit('STOP: selected interface is not WireGuard')
if 'UP' in link['flags'] or link.get('addr_info'):
    sys.exit('STOP: selected interface is still up or has addresses')

name = f'wg-quick-{iface}'
inventory = json.loads(run('sudo', '-n', 'nft', '-j', 'list', 'tables'))
tables = [item['table'] for item in inventory['nftables']
          if 'table' in item and item['table']['name'] == name
          and item['table']['family'] in ('ip', 'ip6')]
backup = Path(tempfile.mkdtemp(prefix='wifiman-recovery-'))
print(f'Firewall snapshots: {backup}', flush=True)
for table in tables:
    family = table['family']
    contents = run('sudo', '-n', 'nft', 'list', 'table', family, name)
    path = backup / f'{family}.nft'
    path.write_text(contents)
    path.chmod(0o600)

# Recheck immediately before deletion; never remove a newly active tunnel.
link = json.loads(run('ip', '-j', 'address', 'show', 'dev', iface))[0]
if 'UP' in link['flags'] or link.get('addr_info'):
    sys.exit('STOP: interface state changed; repeat diagnosis')
run('sudo', '-n', 'ip', 'link', 'delete', 'dev', iface)
for table in tables:
    run('sudo', '-n', 'nft', 'delete', 'table', table['family'], name)
print('Removed the inactive WiFiman interface and its matching firewall tables')
PY
```

Any failed command stops the block. If the interface was already absent, do
not substitute another name to make the command pass: review any remaining
tables and their ownership separately. If a failure occurs after interface
deletion, retain the printed snapshot path and inspect the exact remaining
tables before retrying. Do not proceed to reconnect with a partial cleanup.

Verify the selected objects are gone:

```bash
ip link show dev "$TELEPORT_IFACE"
sudo nft list tables | rg -F "wg-quick-$TELEPORT_IFACE"
ip rule show
ip -6 rule show
```

Expected: `ip` reports that the device does not exist; `rg` finds no matching
table. If stale routes or rules remain, inspect their ownership rather than
flushing all policy rules. The verified incident did not require manual route
or policy-rule deletion.

### 3. Start WiFiman and connect once

```bash
sudo systemctl start wifiman-desktop.service
systemctl is-active wifiman-desktop.service
date -Is
```

Expected: `active`. Open **WiFiman Desktop** from the application launcher,
select the intended gateway, and click **Connect once**. Record the connection
time for log filtering. Avoid overlapping Connect/Cancel/Disconnect requests.

This is a one-time cleanup, not a persistent configuration change. The
existing MTU `1280` mitigation remained in place during recovery; changing MTU,
disabling IPv6, resetting invitations, or reinstalling the app was not needed.
Do not install a broad automatic `wg*` cleanup hook from this procedure.

## Verification

Require all of the following before declaring recovery:

1. **Visible app state:** the intended gateway shows **Connected for …**, with
   an advancing timer, traffic counters, and an enabled **Disconnect** button.
   There must be no Connecting/Disconnecting spinner or pending Cancel control.
2. **Fresh operating-system state:** identify the current tunnel again. Its
   addresses and route are present, and the old interface/tables remain absent.
3. **Sustained health:** observe at least **six minutes**. Rerun the event
   projection and count only events after the recorded fresh connection time.
   Require no UDP echo failures, connection timeouts, teardown, or automatic
   reconnects. Intermittent warning-only timeouts warrant continued observation.
4. **Actual access:** verify the home path and ordinary internet access:

```bash
nmcli -f NAME,TYPE,DEVICE connection show --active
ip -d link show type wireguard
ip route get 192.168.3.2
ping -n -c 3 -W 2 192.168.3.1
getent ahostsv4 rancher.home
kubectl --request-timeout=8s get --raw=/readyz
curl -4 --connect-timeout 5 --max-time 10 -sS -o /dev/null \
  -w 'Internet HTTPS: %{http_code}\n' https://ui.com
```

Expected for this home lab: the API route uses the current tunnel, gateway
pings succeed, `rancher.home` resolves to the ingress VIP, `/readyz` returns
`ok`, and the internet HTTPS check returns `200`. The `kubectl` probe is
read-only; use the configured home-lab context, or test a known internal
application if that context is unavailable.

Repeat the IPv6 health check using the current echo destination, and confirm
both sent and received tunnel counters increase. A single passing IPv4 probe
does not replace the app-state and sustained-health requirements.

If testing `https://rancher.home`, use the trusted home-lab CA. A certificate
trust error is a separate verification limit, not evidence that the VPN failed;
do not silently disable certificate verification and report a full TLS pass.

## Rollback

No account/profile files or persistent firewall policy are edited. A deleted
inactive tunnel is recreated by WiFiman during a fresh connection; do not try
to reconstruct it from logged keys or restore its stale firewall tables over
a new tunnel. The private `.nft` snapshots are for reviewing exact removed
rules, not an automatic full-firewall restore.

If reconnecting causes a regression, click **Disconnect** and quit the app.
If the app is stuck, repeat the stop procedure, then diagnose the new interface
before considering another scoped cleanup. With the VPN disconnected, verify
the laptop has its ordinary Wi-Fi route and internet access:

```bash
ip route get 1.1.1.1
nmcli -f NAME,TYPE,DEVICE connection show --active
curl -4 --connect-timeout 5 --max-time 10 -sS -o /dev/null \
  -w 'Internet HTTPS: %{http_code}\n' https://ui.com
```

Expected: traffic uses the normal Wi-Fi gateway and HTTPS succeeds. If an
unrelated interface or firewall rule was removed, stop further changes and
review the saved scope before restoring anything. Restoring old anti-spoof
rules while their interface is absent can break a replacement connection.

## Escalation

Stop local reset attempts if one complete cleanup still fails the six-minute
verification, or if ownership cannot be established. Continue with read-only
diagnosis and provide the laptop/home-lab operator with:

- app/package version, selected gateway, and timestamps with timezone;
- projected state transitions and exact failure labels;
- current interface names, route choice, MTU, and scoped table names;
- whether IPv4, IPv6 ICMP, and UDP health replies work independently;
- a description of the visible app state and whether another underlay works.

For suspected gateway-side failure, use the Wardn UniFi Network MCP when
available and inspect current Teleport/firewall state. This runbook does not
authorize gateway resets or changes to Fleet-managed cluster resources.
For a repeatable app failure, the operator can open a case through
[Ubiquiti Support](https://help.ui.com/), reviewing any requested support bundle
for credentials before sharing it. Do not send raw logs to a public issue.

## References

- [Ubiquiti: Teleport VPN](https://help.ui.com/hc/en-us/articles/5246403561495-UniFi-Gateway-Teleport-VPN)
- [WiFiman Desktop 1.2.8 release](https://community.ui.com/releases/a461e7ac-9472-4228-b451-a6b0a02c345d)
- [Official desktop downloads](https://ui.com/download/app/wifiman-desktop)
- [Laptop WireGuard MTU and TLS timeouts](laptop-wireguard-mtu-tls-handshake-timeouts.md)
- [UniFi LAN integration](../../../infrastructure/network/unifi/README.md)

The observed installed version is historical evidence, not a permanent latest
version claim. Compare official release notes and the actual download version
before choosing an upgrade; a download-page link can point to an older build.
