"""Exercise installed/running Ubuntu kernels against real temporary boot assets."""
from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('vendor', Path(__file__).resolve().parents[1] / 'files/check_vendor_kernel.py')
vendor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vendor)


class VendorKernelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.running = '7.0.0-1020-raspi'
        self.expected = self.running
        self.write('/boot/config-' + self.expected, '\n'.join([
            'CONFIG_DEBUG_INFO_BTF=y', 'CONFIG_ARM64_4K_PAGES=y', 'CONFIG_CGROUPS=y',
            'CONFIG_CGROUP_BPF=y', 'CONFIG_BPF_SYSCALL=y']))
        for kind in ['vmlinuz', 'initrd.img']:
            self.write('/boot/' + kind + '-' + self.expected, kind)
            self.write('/boot/firmware/current/' + kind, kind)
        self.write('/boot/firmware/config.txt', '[all]\nos_prefix=current/\n[tryboot]\nos_prefix=new/\n[all]\nkernel=vmlinuz\ninitramfs initrd.img followkernel\n')
        self.write('/boot/firmware/autoboot.txt', '[all]\ntryboot_a_b=1\n')
        self.write('/boot/firmware/current/state', 'good\n')
        self.write('/sys/kernel/btf/vmlinux', b'\x9f\xeb' + b'BTF' * 16)
        self.path('/lib/modules/' + self.expected).mkdir(parents=True)

    def path(self, value):
        p = Path(value)
        return p if p.is_relative_to(self.root) else self.root / str(value).lstrip('/')

    def write(self, name, value):
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(value if isinstance(value, bytes) else value.encode())

    def run_check(self, pending=False):
        def query(package, field):
            return 'linux-image-' + self.expected + ' (= 7.0.0-1020.20)' if field == 'Depends' else 'install ok installed'
        def command(argv, **kwargs):
            return '4096\n' if argv[0] == 'getconf' else ''
        with ExitStack() as stack:
            for target, value in [(vendor.os, ('geteuid', lambda: 0)),
                                  (vendor.platform, ('machine', lambda: 'aarch64')),
                                  (vendor.platform, ('release', lambda: self.running)),
                                  (vendor, ('Path', self.path)), (vendor, ('query', query)),
                                  (vendor.subprocess, ('check_output', command))]:
                stack.enter_context(patch.object(target, value[0], value[1]))
            stack.enter_context(patch('sys.argv', ['check'] + (['--allow-pending-boot'] if pending else [])))
            output = stack.enter_context(redirect_stdout(io.StringIO()))
            vendor.main()
            return json.loads(output.getvalue())

    def test_good_running_boot_passes(self):
        r = self.run_check()
        self.assertEqual(r['running_kernel'], self.expected)
        self.assertEqual(r['bootPrefix'], 'current/')

    def test_bad_btf_or_boot_hash_is_rejected(self):
        self.write('/sys/kernel/btf/vmlinux', b'bad' * 20)
        with self.assertRaisesRegex(RuntimeError, 'BTF absent'):self.run_check()
        self.write('/sys/kernel/btf/vmlinux', b'\x9f\xeb' + b'BTF' * 16)
        self.write('/boot/firmware/current/vmlinuz', 'unexpected image')
        with self.assertRaisesRegex(RuntimeError, 'boot artifact differs'):self.run_check()

    def test_staged_next_boot_is_checked_but_not_accepted_as_running(self):
        self.running = '7.0.0-1017-raspi'
        for kind in ['vmlinuz', 'initrd.img']:self.write('/boot/firmware/new/' + kind, kind)
        self.write('/var/run/reboot-required', '')
        r = self.run_check(pending=True)
        self.assertEqual(r['expected_kernel'], self.expected)
        self.assertEqual(r['running_kernel'], self.running)
        self.assertEqual(r['bootPrefix'], 'new/')
        with self.assertRaisesRegex(RuntimeError, 'reboot required'):self.run_check()

    def test_pending_boot_with_wrong_initramfs_is_rejected(self):
        for kind in ['vmlinuz', 'initrd.img']:self.write('/boot/firmware/new/' + kind, kind)
        self.write('/boot/firmware/new/initrd.img', 'wrong initramfs')
        with self.assertRaisesRegex(RuntimeError, 'boot artifact differs'):self.run_check(pending=True)

    def test_trial_assets_and_reboot_marker_block_runtime_acceptance(self):
        self.write('/var/run/reboot-required', '')
        with self.assertRaisesRegex(RuntimeError, 'reboot remains pending'):self.run_check()
        self.path('/var/run/reboot-required').unlink()
        self.path('/boot/firmware/new').mkdir()
        with self.assertRaisesRegex(RuntimeError, 'Trial boot assets remain pending'):self.run_check()

    def test_non_vendor_kernel_is_rejected_even_in_plan_mode(self):
        self.running = '7.0.0-custom'
        with self.assertRaisesRegex(RuntimeError, 'vendor ARM64'):self.run_check(pending=True)

    def test_missing_modules_are_rejected(self):
        self.path('/lib/modules/' + self.expected).rmdir()
        with self.assertRaisesRegex(RuntimeError, 'Matching modules absent'):self.run_check()
