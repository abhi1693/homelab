"""Read-only safety checks for the bounded Alloy payload filesystem."""

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def inspect(image, mountpoint, size_mib, reserve_mib, validate=False):
    image = Path(image)
    mountpoint = Path(mountpoint)
    for path in (image.parent, image, mountpoint):
        if path.is_symlink():
            raise ValueError(f"Refusing a symlink: {path}")
    parent = image.parent
    while not parent.exists():
        parent = parent.parent
    backing = json.loads(command('findmnt', '--json', '--target', str(parent),
                                 '--output', 'SOURCE,FSTYPE,TARGET'))['filesystems'][0]
    if not os.path.realpath(backing['source']).startswith('/dev/nvme'):
        raise ValueError(f"Queue image must reside on NVMe, found {backing['source']}")
    exists = image.exists()
    size_bytes = size_mib * 1024 * 1024
    space = os.statvfs(parent)
    required_free = reserve_mib * 1024 * 1024 + (0 if exists else size_bytes)
    if space.f_bavail * space.f_frsize < required_free:
        raise ValueError('Insufficient NVMe space for the image and required free-space reserve')
    if exists:
        info = image.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size != size_bytes:
            raise ValueError('Existing queue image must be a regular file of the configured size')
        signature = dict(line.split('=', 1) for line in command(
            'blkid', '-p', '-o', 'export', str(image)).splitlines() if '=' in line)
        if signature.get('TYPE') != 'ext4' or signature.get('LABEL') != 'alloy-otel-queue':
            raise ValueError('Refusing to format or adopt an unrecognized existing queue image')
    mounted = os.path.ismount(mountpoint)
    if mounted:
        mount = json.loads(command('findmnt', '--json', '--mountpoint', str(mountpoint),
                                  '--output', 'SOURCE,FSTYPE,OPTIONS'))['filesystems'][0]
        if not exists or mount['fstype'] != 'ext4':
            raise ValueError('Refusing an unexpected existing mount')
        loops = json.loads(command('losetup', '--json', '--list', '--output', 'NAME,BACK-FILE'))['loopdevices']
        if not any(loop['name'] == mount['source'] and
                   os.path.realpath(loop['back-file']) == str(image.resolve()) for loop in loops):
            raise ValueError('Existing mount is not backed by the configured queue image')
        if not {'nodev', 'nosuid', 'noexec'}.issubset(set(mount['options'].split(','))):
            raise ValueError('Queue filesystem lacks nodev,nosuid,noexec protection')
        filesystem_bytes = os.statvfs(mountpoint).f_blocks * os.statvfs(mountpoint).f_frsize
        if not size_bytes * 0.90 <= filesystem_bytes <= size_bytes:
            raise ValueError('Mounted queue filesystem capacity does not match its bounded image')
    elif mountpoint.exists() and (not mountpoint.is_dir() or any(mountpoint.iterdir())):
        raise ValueError('Refusing to mount over a nonempty path or a non-directory')
    if validate and not mounted:
        raise ValueError('Bounded queue filesystem is not mounted')
    if validate and (image.stat().st_uid != 0 or stat.S_IMODE(image.stat().st_mode) != 0o600):
        raise ValueError('Queue image must be root-owned with mode 0600')
    if validate and (mountpoint.stat().st_uid != 0 or stat.S_IMODE(mountpoint.stat().st_mode) != 0o700):
        raise ValueError('Queue filesystem root must be root-owned with mode 0700')
    if validate:
        data = mountpoint / 'data'
        if data.is_symlink() or not data.is_dir():
            raise ValueError('Verified filesystem must contain the fail-closed collector data directory')
        if data.stat().st_dev != mountpoint.stat().st_dev or data.stat().st_dev == parent.stat().st_dev:
            raise ValueError('Collector data must reside on the bounded filesystem, not the root disk')
        if data.stat().st_uid != 0 or stat.S_IMODE(data.stat().st_mode) != 0o700:
            raise ValueError('Collector data directory must be root-owned with mode 0700')
    return {'image_exists': exists, 'mounted': mounted, 'image_bytes': size_bytes,
            'backing_source': backing['source']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True)
    parser.add_argument('--mountpoint', required=True)
    parser.add_argument('--size-mib', type=int, required=True)
    parser.add_argument('--reserve-mib', type=int, required=True)
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    print(json.dumps(inspect(args.image, args.mountpoint, args.size_mib,
                             args.reserve_mib, args.validate)))


if __name__ == '__main__':
    main()
