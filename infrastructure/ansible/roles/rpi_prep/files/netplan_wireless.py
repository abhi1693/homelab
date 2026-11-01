#!/usr/bin/env python3
"""Remove only inventory-disabled radios from Netplan; preserve wired settings."""

import copy
import json
import os
from pathlib import Path
import sys
import tempfile

import yaml


def without_radios(document, interfaces):
    result = copy.deepcopy(document)
    network = result.get('network', {})
    radios = network.get('wifis', {})
    removed = set(radios).intersection(interfaces)
    if removed:
        if network.get('version') != 2 or not network.get('ethernets'):
            raise RuntimeError('Refusing to remove wireless configuration without wired Netplan settings')
        for name in removed:
            del radios[name]
        if not radios:
            del network['wifis']
    return result


def main():
    config = json.loads(sys.argv[1])
    interfaces = config['interfaces']
    if not interfaces or any(not name.startswith('wlan') or not name[4:].isdigit() for name in interfaces):
        raise RuntimeError('Expected explicit wlan interface names')
    if config['mode'] not in ['apply', 'validate']:
        raise RuntimeError('Unknown Netplan operation')
    if config['mode'] == 'validate':
        cloud = yaml.safe_load(Path('/etc/cloud/cloud.cfg.d/99-home-lab-network.cfg').read_text())
        if cloud.get('network', {}).get('config') != 'disabled':
            raise RuntimeError('Cloud-init can regenerate disabled radio configuration')
        if any((Path('/sys/class/net') / name).exists() for name in interfaces):
            raise RuntimeError('Disabled radio remains active; reboot before qualification')
    changed = []
    for path in sorted(Path('/etc/netplan').glob('*.y*ml')):
        original = yaml.safe_load(path.read_text())
        updated = without_radios(original, interfaces)
        if original == updated:
            continue
        if config['mode'] == 'validate':
            raise RuntimeError('Disabled radio remains configured in ' + str(path))
        metadata = path.stat()
        fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                yaml.safe_dump(updated, stream, sort_keys=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.chown(temporary, metadata.st_uid, metadata.st_gid)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        changed.append(str(path))
    print(json.dumps({'changed': bool(changed), 'files': changed}))


if __name__ == '__main__':
    main()
