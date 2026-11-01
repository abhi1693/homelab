#!/usr/bin/env python3
"""Read-only Ubuntu Pi host acceptance, including Ubuntu vendor A/B boot assets."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def query(package, field):
    return subprocess.check_output(['dpkg-query', '-W', '-f=${' + field + '}', package], text=True).strip()


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def boot_selection(text):
    """Resolve normal Pi 5 boot, preserving Ubuntu's vendor A/B fallback."""
    active = True
    trial = False
    trial_prefix = None
    selected = {}
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('['):
            require(line in ['[all]', '[tryboot]', '[pi5]', '[pi4]', '[pi3]', '[pi3+]', '[pi2]', '[pi0]', '[pi02]', '[cm4]', '[none]'], 'Review unsupported boot conditional: ' + line)
            trial = line == '[tryboot]'
            active = line in ['[all]', '[pi5]']
            continue
        require(not line.startswith('include '), 'Review included boot configuration')
        if trial:
            require(line == 'os_prefix=new/', 'Review alternate trial boot directive: ' + line)
            trial_prefix = 'new/'
            continue
        if not active:
            continue
        require(not line.startswith(('overlay_prefix=', 'armstub=', 'tryboot_a_b=')), 'Review alternate firmware loader')
        if line.startswith('os_prefix='):
            require(line == 'os_prefix=current/', 'Review alternate OS prefix')
            selected['prefix'] = 'current/'
        elif line.startswith('kernel='):
            selected['image'] = line.split('=', 1)[1]
        elif line.startswith('initramfs '):
            args = line.split()
            require(len(args) == 3 and args[2] == 'followkernel', 'Review initramfs addressing')
            selected['initramfs'] = args[1]
    require(selected.get('image') == 'vmlinuz' and selected.get('initramfs') == 'initrd.img', 'Expected the Ubuntu vmlinuz/initrd.img boot layout')
    require(('prefix' in selected) == (trial_prefix == 'new/'), 'Incomplete Ubuntu A/B boot configuration')
    require('[tryboot]' not in text or trial_prefix == 'new/', 'Incomplete trial boot section')
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-pending-boot", action="store_true")
    args = parser.parse_args()
    require(os.geteuid() == 0, 'Run this read-only validation with sudo; kernel artifacts are root-readable')
    release = platform.release()
    require(platform.machine() == 'aarch64' and re.fullmatch(r'\d+\.\d+\.\d+-\d+-raspi', release), 'Expected a vendor ARM64 raspi kernel')
    require(query('linux-image-raspi', 'Status') == 'install ok installed', 'Ubuntu kernel tracking package missing')
    depends = query('linux-image-raspi', 'Depends')
    images = re.findall(r'(?:^|,\s*)linux-image-(\d+\.\d+\.\d+-\d+-raspi)(?:\s|,|$)', depends)
    require(len(images) == 1, 'Expected one installed raspi tracking kernel')
    expected = images[0]
    if not args.allow_pending_boot:
        require(expected == release, 'Running kernel differs from the installed raspi tracking package; reboot required')
    require(query('linux-image-' + expected, 'Status') == 'install ok installed', 'Versioned vendor image missing')
    require(not subprocess.check_output(['dpkg', '--verify', 'linux-image-' + expected], text=True).strip(), 'Installed vendor image package content changed')
    config = Path('/boot/config-' + expected).read_text()
    for option in ['CONFIG_DEBUG_INFO_BTF=y', 'CONFIG_ARM64_4K_PAGES=y', 'CONFIG_CGROUPS=y', 'CONFIG_CGROUP_BPF=y', 'CONFIG_BPF_SYSCALL=y']:
        require(option in config.splitlines(), 'Required kernel option missing: ' + option)
    btf = Path('/sys/kernel/btf/vmlinux')
    require(btf.stat().st_size > 24 and btf.read_bytes()[:2] == b'\x9f\xeb', 'Actual running kernel BTF absent or invalid')
    selected = boot_selection(Path('/boot/firmware/config.txt').read_text())
    prefix = selected.get('prefix', '')
    if prefix:
        autoboot = [line.split('#', 1)[0].strip() for line in Path('/boot/firmware/autoboot.txt').read_text().splitlines()]
        require(autoboot == ['[all]', 'tryboot_a_b=1'], 'Review alternate A/B autoboot configuration')
        require(Path('/boot/firmware/current/state').read_text().strip() == 'good', 'Current Ubuntu boot assets are not validated')
        if args.allow_pending_boot and Path('/boot/firmware/new').exists():
            prefix = 'new/'
        else:
            require(not Path('/boot/firmware/new').exists(), 'Trial boot assets remain pending; finish the vendor A/B boot')
    for source, selected in [('vmlinuz', 'vmlinuz'), ('initrd.img', 'initrd.img')]:
        require(sha('/boot/' + source + '-' + expected) == sha('/boot/firmware/' + prefix + selected), 'Firmware boot artifact differs from installed ' + source)
    require(Path('/lib/modules/' + expected).is_dir(), 'Matching modules absent')
    if not args.allow_pending_boot:
        require(not Path('/var/run/reboot-required').exists(), 'A reboot remains pending')
    require(not subprocess.check_output(['swapon', '--noheadings', '--raw', '--show'], text=True).strip(), 'Swap remains active')
    require(not subprocess.check_output(['dpkg', '--audit'], text=True).strip(), 'Package database inconsistent')
    page_bytes = int(subprocess.check_output(['getconf', 'PAGESIZE'], text=True))
    require(page_bytes == 4096, 'Running kernel does not use 4 KiB pages')
    print(json.dumps({'running_kernel': release, 'expected_kernel': expected, 'kernel': release, 'btfSHA256': sha(btf), 'btfBytes': btf.stat().st_size,
                      'imageSHA256': sha('/boot/vmlinuz-' + expected), 'pageBytes': page_bytes, 'bootPrefix': prefix}))


if __name__ == '__main__':
    main()
