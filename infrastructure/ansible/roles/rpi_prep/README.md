# Ubuntu Raspberry Pi host preparation

Supports Ubuntu Server 26.04 LTS ARM64. `main`, `validation` and `reset` use
`/boot/firmware/current/cmdline.txt` and, when present, `new/cmdline.txt`.
Both boot command lines preserve required Kubernetes parameters. The vendor
A/B mechanism, image/initramfs and `old/` fallback assets remain vendor-owned.
Unsupported host distributions are rejected before changing host settings.

The role disables swap in fstab/runtime, persists and loads `overlay` and
`br_netfilter`, manages forwarding/kubelet/inotify settings, and installs the
Raspberry Pi throttling exporter. Firmware-disabled wireless interfaces are
removed from Netplan without changing wired routes; cloud-init cannot restore
those stale interfaces. Network configuration is generated without a live
network restart and applied on the normal reboot handler.

`validation` verifies runtime modules, sysctls, swap, command lines, boot config
and hardware telemetry. Its `kernel_validation` entrypoint checks Canonical's
installed `linux-image-raspi`, package integrity, native sysfs BTF, 4 KiB pages,
matching modules and selected image/initramfs hashes. Current A/B state must be
`good` with no pending trial or reboot. The same helper supports an explicit
`--allow-pending-boot` inspection for supervised OS maintenance, validating the
installed next kernel and staged assets before reboot without accepting them
as a qualified running kernel.

`reset` removes only role-managed parameters, tunables, module-loading files
and exporter resources. It never unloads in-use modules or rewrites vendor boot
fallbacks. Physical NVMe checks remain in `smartctl_exporter` validation.
