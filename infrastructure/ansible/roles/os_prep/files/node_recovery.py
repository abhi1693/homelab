"""Manage bounded remote kernel capture and inspect evidence collection health."""
import argparse
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
import socket
import subprocess
import time

CONFIG = Path('/etc/home-lab/node-recovery.json')
TARGETS = Path('/sys/kernel/config/netconsole')
PREFIX = 'home_lab_'


def load_config(path=CONFIG):
    config = json.loads(path.read_text())
    ipaddress.IPv4Address(config['address'])
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+', config['interface']):
        raise ValueError('Invalid network interface')
    if not re.fullmatch(r'k8s-rpi[1-8]', config['node']):
        raise ValueError('Unknown source node')
    if len(config['receivers']) < 2:
        raise ValueError('At least two independent receivers are required')
    for peer in config['receivers']:
        ipaddress.IPv4Address(peer['address'])
        if not re.fullmatch(r'[0-9a-f]{2}(:[0-9a-f]{2}){5}', peer['mac']):
            raise ValueError('Invalid receiver MAC')
        if not re.fullmatch(r'k8s-rpi[1-3]', peer['node']):
            raise ValueError('Unknown receiver')
    for address, node in config['sources'].items():
        ipaddress.IPv4Address(address)
        if not re.fullmatch(r'k8s-rpi[1-8]', node):
            raise ValueError('Unknown allowed source')
    return config


def target_values(config, peer):
    return {'dev_name': config['interface'], 'local_ip': config['address'],
            'local_port': '6665', 'remote_ip': peer['address'], 'remote_port': '6666',
            'remote_mac': peer['mac'], 'extended': '1'}


def configure(config):
    changed = False
    wanted = set()
    for peer in config['receivers']:
        if peer['address'] == config['address']:
            continue
        name = PREFIX + peer['node'].replace('-', '_')
        wanted.add(name)
        target = TARGETS / name
        target.mkdir(exist_ok=True)
        values = target_values(config, peer)
        if all((target / key).read_text().strip() == value for key, value in values.items()) and (target / 'enabled').read_text().strip() == '1':
            continue
        # Configfs rejects writing the current enable state with EINVAL.
        if (target / 'enabled').read_text().strip() == '1':
            (target / 'enabled').write_text('0')
        for key, value in values.items():
            (target / key).write_text(value)
        (target / 'enabled').write_text('1')
        changed = True
    for target in TARGETS.glob(PREFIX + '*'):
        if target.name not in wanted:
            if (target / 'enabled').read_text().strip() == '1':
                (target / 'enabled').write_text('0')
            target.rmdir()
            changed = True
    print(json.dumps({'event': 'netconsole_configured', 'changed': changed, 'targets': len(wanted)}))


def inspect(config):
    targets = 0
    for peer in config['receivers']:
        if peer['address'] == config['address']:
            continue
        target = TARGETS / (PREFIX + peer['node'].replace('-', '_'))
        if target.is_dir() and (target / 'enabled').read_text().strip() == '1' and all(
                (target / key).read_text().strip() == value for key, value in target_values(config, peer).items()):
            targets += 1
    expected = sum(p['address'] != config['address'] for p in config['receivers'])
    is_receiver = any(p['address'] == config['address'] for p in config['receivers'])
    receiver_active = is_receiver and subprocess.run(
        ['systemctl', 'is-active', '--quiet', 'home-lab-kernel-receiver.service'], check=False).returncode == 0
    return {'netconsole_targets': targets, 'expected_targets': expected,
            'is_receiver': is_receiver, 'receiver_active': receiver_active}


def record_for_packet(packet, address, sources):
    """Only known LAN peers; JSON escaping keeps each datagram to one journal line."""
    if address not in sources:
        return None
    return {'event': 'remote_kernel', 'source_node': sources[address], 'source_ip': address,
            'received_at': datetime.now(timezone.utc).isoformat(),
            'message': packet[:8192].decode('utf-8', errors='replace')}


def receive(config):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((config['address'], 6666))
    # A per-source ceiling bounds malformed or flood traffic; journald has a second cap.
    windows = {}
    print(json.dumps({'event': 'kernel_receiver_ready', 'node': config['node']}), flush=True)
    while True:
        packet, peer = sock.recvfrom(8192)
        record = record_for_packet(packet, peer[0], config['sources'])
        if record is None:
            continue
        epoch = int(time.monotonic())
        old_epoch, count = windows.get(peer[0], (epoch, 0))
        count = count + 1 if old_epoch == epoch else 1
        windows[peer[0]] = (epoch, count)
        if count == 201:
            print(json.dumps({'event': 'kernel_receiver_rate_limited', 'source_node': config['sources'][peer[0]]}), flush=True)
        if count <= 200:
            print(json.dumps(record), flush=True)


def metrics(config):
    state = inspect(config)
    lines = ['# Managed by home-lab node recovery; host-only health, not crash proof.']
    for key in ('netconsole_targets', 'expected_targets', 'is_receiver', 'receiver_active'):
        lines.append(f'home_lab_host_recovery_{key} {int(state[key])}')
    lines.append(f'home_lab_host_recovery_last_check_seconds {time.time():.3f}')
    directory = Path('/var/lib/node_exporter/textfile_collector')
    directory.mkdir(mode=0o755, parents=True, exist_ok=True)
    target = directory / 'home_lab_recovery.prom'
    temporary = directory / '.home_lab_recovery.tmp'
    temporary.write_text('\n'.join(lines) + '\n')
    temporary.replace(target)
    print(json.dumps({'event': 'host_recovery_health', **state}), flush=True)


def boot_evidence(config):
    # Root-only existing pstore archives remain the authoritative crash artifacts.
    result = subprocess.run(['journalctl', '-b', '-1', '-k', '-p', 'warning', '-n', '40',
                             '--no-pager', '-o', 'short-iso'], capture_output=True, text=True, timeout=20)
    print(json.dumps({'event': 'previous_boot_kernel_summary', 'node': config['node'],
                      'current_boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                      'pstore_files': len(list(Path('/sys/fs/pstore').glob('*'))),
                      'previous_kernel_warnings': result.stdout[-16000:]}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['configure', 'validate', 'receive', 'metrics', 'boot-evidence', 'canary'])
    args = parser.parse_args()
    config = load_config()
    if args.action == 'configure':
        configure(config)
    elif args.action == 'validate':
        state = inspect(config)
        if state['netconsole_targets'] != state['expected_targets'] or (state['is_receiver'] and not state['receiver_active']):
            raise RuntimeError(state)
        print(json.dumps(state))
    elif args.action == 'receive':
        receive(config)
    elif args.action == 'metrics':
        metrics(config)
    elif args.action == 'boot-evidence':
        boot_evidence(config)
    else:
        # One tagged delivery probe at ERR priority passes the unchanged console threshold.
        # This is a transport test, never a panic, stall, reboot or real error injection.
        marker = f'home-lab-netconsole-canary node={config["node"]} boot_id={Path("/proc/sys/kernel/random/boot_id").read_text().strip()}'
        with open('/dev/kmsg', 'w') as stream:
            stream.write('<3>' + marker + '\n')
        print(marker)


if __name__ == '__main__':
    main()
