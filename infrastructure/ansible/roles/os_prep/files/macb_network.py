"""Read-only NIC validation and bounded TX-stall evidence for selected macb hosts."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import time


def offloads(text):
    values = {}
    for line in text.splitlines():
        key, separator, value = line.strip().partition(': ')
        if separator and key in ('tcp-segmentation-offload', 'scatter-gather'):
            state = value.split()[0]
            if state not in ('on', 'off'):
                raise ValueError('Unknown offload state')
            values[key] = state == 'on'
    if len(values) != 2:
        raise ValueError('Required offload settings are missing')
    return values


def inspect():
    root = Path('/sys/class/net/eth0')
    if 'DRIVER=macb' not in (root / 'device/uevent').read_text().splitlines():
        raise ValueError('Only the approved macb NIC may be inspected')
    text = subprocess.check_output(['/usr/sbin/ethtool', '-k', 'eth0'], text=True, timeout=10)
    result = {'node': socket.gethostname(), 'time': time.time(),
              'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), **offloads(text)}
    result['carrier'] = int((root / 'carrier').read_text())
    for key in ['tx_packets', 'tx_bytes', 'tx_errors', 'tx_dropped', 'rx_packets', 'rx_bytes', 'rx_errors']:
        result[key] = int((root / 'statistics' / key).read_text())
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['validate', 'metrics'])
    args = parser.parse_args()
    state = inspect()
    if args.action == 'validate':
        if state['tcp-segmentation-offload'] or state['scatter-gather']:
            raise RuntimeError('Approved offload workaround is not active')
    else:
        qdisc = subprocess.run(['/usr/sbin/tc', '-s', 'qdisc', 'show', 'dev', 'eth0'],
                               capture_output=True, text=True, timeout=10, check=False)
        state['qdisc'] = qdisc.stdout[:4096]
        directory = Path('/var/lib/node_exporter/textfile_collector')
        lines = [f'home_lab_macb_{key} {int(state[key])}' for key in
                 ['carrier', 'tx_packets', 'tx_bytes', 'tx_errors', 'tx_dropped', 'rx_packets', 'rx_bytes', 'rx_errors']]
        lines += [f'home_lab_macb_tso_enabled {int(state["tcp-segmentation-offload"])}',
                  f'home_lab_macb_sg_enabled {int(state["scatter-gather"])}',
                  f'home_lab_macb_last_check_seconds {state["time"]:.3f}']
        temporary = directory / '.home_lab_macb.tmp'
        temporary.write_text('\n'.join(lines) + '\n')
        temporary.replace(directory / 'home_lab_macb.prom')
    print(json.dumps({'event': 'macb_network_health', **state}), flush=True)


if __name__ == '__main__':
    main()
