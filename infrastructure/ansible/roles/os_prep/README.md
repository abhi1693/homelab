# Ubuntu host preparation and maintenance

Supports Ubuntu Server 26.04 LTS ARM64 on the lab's Raspberry Pi 5 nodes.
Inventory owns packages, CA security floors, official archive URI and the
`resolute`, `resolute-updates`, `resolute-security` pockets. Host preparation
manages automation sudo, hostname, timezone, NTP and shared NFS/iSCSI tools.
Autonomous package upgrades and reboots are disabled in favor of supervised
maintenance. Existing CA distrust fingerprints remain enforced.

## Prohibited cloning tools

Normal host preparation removes `rpi-clone` and `rpi-clone-setup` from
`/usr/local/sbin` and `/usr/local/bin`, plus the `rpi-clone` checkout in `/root`
and each direct user directory under `/home`. Symlinked home directories are
not traversed. Normal validation fails if any of these paths exist, including
broken symlinks. This policy also covers new workers during onboarding.

Dedicated entrypoints let operators preview, clean and verify these paths
without package upgrades, reboots or K3s changes. From `infrastructure/ansible`:

```sh
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=rpi_clone_cleanup --check
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=rpi_clone_cleanup
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=rpi_clone_validation
```

Add `--limit 'k3s_nodes:!worker-6'` to exclude the new Pi during a rollout.
These are Ansible convergence and validation steps, not a continuous install
block: an administrator can recreate files between runs. Arbitrarily renamed
copies and checkouts outside these standard locations are outside this policy.

## Network time on all nodes

`time` preserves the active chrony/NTS or systemd-timesyncd client, enables it
persistently and waits for synchronization without forcing a clock step.
`time_validation` requires exactly one enabled/running client, synchronized
NTP and the inventory timezone. Neither entrypoint upgrades packages or reboots.

```sh
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=time
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=time_validation
```

## K3s startup waits for Chrony

The Home Lab inventory enables `k3s_time_gate`. Both K3s server and agent
service definitions append a pre-start `chronyc waitsync` check after starting
Chrony. Each start requires synchronization and at most 0.1 seconds remaining
clock correction. Sixty checks at five-second intervals allow about five
minutes; an outer 310-second timeout (plus a five-second kill grace) also bounds
RPC stalls. No command forces a clock step or changes the distribution's sources.

Failure prevents that K3s start; it never starts with an unsynchronized clock.
The existing K3s `Restart=always` policy retries after its existing five-second
delay, including after NTP connectivity recovers. The drop-in adds only a
`Wants`/`After` relationship to Chrony: losing Chrony later does not stop a running
K3s process. It does not enable the distribution's unbounded wait command or
reset existing `ExecStartPre` commands, K3s startup timeouts or restart policies.

Convergence installs drop-ins and reloads systemd only. Existing K3s processes
are left running; never restart all nodes to test this change. The gate requires
Chrony enabled/running and refuses to silently switch a timesyncd deployment.
The ordinary `time` entrypoint installs it; a dedicated serial apply avoids all
other host preparation, package upgrades and reboots:

```sh
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=time_startup_gate --check --limit worker-2
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=time_startup_gate --limit worker-2
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=time_startup_gate_validation --limit worker-2
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=time_startup_gate
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=time_startup_gate_validation
```

Validation compares both installed files with inventory, checks effective
pre-start commands on installed K3s units, and runs the real bounded check
against the current clock without restarting K3s. A currently synchronized
clock cannot prove cold-boot behavior; verify ordered startup during the next
individually approved node maintenance. Startup gating does not repair runtime
metadata already recorded with an incorrect clock. Diagnose that independently
before selecting a one-node recovery plan.

## Persistent host logs and payload buffering

`logging` converges only host logging: it installs e2fsprogs if absent, manages
the journal drop-in and creates/mounts a dedicated payload filesystem. It does
not perform the general role's package upgrades, reboot hosts, change NTP or
restart K3s. Journald restarts only when its policy changes; `journalctl --flush`
moves volatile entries into persistent storage without deleting existing logs.
`logging_validation` is read-only. Run a canary before the remaining nodes:

```sh
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=logging --check --limit server-1
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=logging --limit server-1
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=logging_validation --limit server-1
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=logging
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=logging_validation
```

Check mode performs the read-only filesystem preflight and reports the planned
operations; it does not attempt to validate image files or units not yet created.
Actual convergence runs serially and stops on the first host failure.

Inventory requests persistent journals with a 512MiB target, 2GiB free-space
reserve, 64MiB volatile ceiling, 7-day maximum age and 30-second sync interval.
These bound storage and ordinary journal sync exposure; they do not guarantee
seven days of retained history or lossless sudden-power recovery. Journald can
retain active files above its target until rotation and can vacuum sooner when
space is constrained. Validation reports actual boot/time coverage and usage.
The 10000-message/30-second per-service rate policy retains protection against
log storms (journald can multiply the burst limit based on free space); any
`Suppressed ... messages` record is evidence of missing source records and must
remain visible in central logging. Individual systemd units may override their
own rate settings; the source inventory must record any such overrides.

The OpenTelemetry payload directory `/var/lib/alloy-node-logs/otel` is a native
systemd-managed ext4 loop mount backed by a preallocated 4GiB NVMe file,
`/var/lib/alloy-node-logs/otel-queue.ext4`. Initial allocation requires another
2GiB free after allocation. The root-owned filesystem uses mode 0700 and
`nodev,nosuid,noexec,noatime`; it is enabled before K3s starts at boot. Existing
nonempty mountpoints, symlinks, unexpected backing mounts and unrecognized
image files stop convergence. Existing images are never reformatted or resized.
The `data` child is created only after the verified filesystem is mounted.
Alloy binds that child using hostPath `Directory`, so a missing boot mount leaves
no valid collector volume rather than an unbounded fallback on the root disk.
Never create that child beneath an unmounted queue path by hand.
An interrupted initial allocation/format requires operator inspection rather
than automatic destruction. Do not unmount or resize it while Alloy is running.
Kubernetes ephemeral-storage limits do not bound hostPath writes; this dedicated
filesystem provides the hard capacity bound. Size exporter queues below usable
capacity with compaction headroom and measure fsync/replay I/O before expansion.
Filling the queue filesystem must alert without consuming the node's remaining
root capacity. Local payloads survive process replacement when their identity
and disk survive; loss of that node/disk can still lose its backlog.

Alloy's Fleet bundle owns collection and exporter configuration. Deploy/recreate
the collector after this host mount exists so its bind mount contains the
payload filesystem; do not create a second journal or container collection path.
The payload filesystem contains log bodies and attributes and must receive the
same access and physical-storage protections as the sources.

`/var/log/kubernetes-audit` exposes only `/var/lib/rancher/k3s/server/logs` through
a root-owned symlink on servers; workers receive an empty root-only directory.
This lets Alloy mount a uniform read-only host directory without mounting the
K3s server tree or credentials. Existing unexpected paths stop convergence.
Audit enablement, Metadata policy and local rotation remain owned by the
`k3s_server` role; this entrypoint neither changes them nor restarts K3s.

`home-lab-log-canary.timer` invokes a bounded systemd oneshot every
60 seconds using monotonic time. `/usr/bin/logger` emits an INFO record with
`SYSLOG_IDENTIFIER=home-lab-log-canary` and a JSON body containing
`event=os-log-canary`, `node`, `boot_id`, integer UTC `unix_time`,
`queue_available_bytes` and `queue_capacity_bytes`. Free space comes directly
from the queue filesystem's `statvfs`, covering loop mounts that other disk
exporters might exclude. The service uses UID 0 to stat the root-only queue
directory, with no capabilities, a read-only system, 32MiB memory cap and a
10-second runtime bound. It requires the payload mount before execution.
It generates no artificial error. Validation checks the enabled/active timer,
successful service result and a recent local journal record. This proves local
generation only; the independently scheduled Loki checker must reconcile those
node canaries to prove collection, transport, ingestion and query freshness.

## Bounded package patches without reboot

`playbooks/os_safe_packages.yml` applies the inventory's exact `safe_package_pins`
serially. Its allow-list contains only libbrotli1 and the reviewed bpftool,
Linux userspace headers, performance-tool and tmux packages. The current tool
cohort pins `bpftool` to `7.7.0+7.0.0-43.43` and `linux-libc-dev`, `linux-perf`
and `linux-tools-common` to `7.0.0-43.43`; the libbrotli1 and tmux pins are
unchanged. It rejects package removals or
additional dependency changes, suppresses package-triggered service restarts,
and checks full cluster health before/after each host and unchanged boot IDs.
It does not upgrade kernel images, systemd, cloud-init or firmware, and never
reboots. Run a single worker first, then the remaining nodes:

```sh
ansible-playbook playbooks/os_safe_packages.yml --syntax-check
ansible-playbook playbooks/os_safe_packages.yml --limit worker-6
ansible-playbook playbooks/os_safe_packages.yml
```

Run the branch's playbook before merging an inventory pin update. Its normal
apply refreshes signed APT metadata and repeats the exact transaction simulation
on each host; cached package availability alone does not qualify an update.
Require all selected hosts to pass package consistency, security floors, cluster
health and unchanged boot-ID checks before merging the PR. A pending reboot
from earlier maintenance blocks this entrypoint and must be resolved through the
guarded rolling maintenance workflow first.

The host security floor now includes `libbrotli1 >= 1.2.0-3ubuntu0.1`.
Installing the library does not reload it into existing processes. Services
still using an older mapped library need the separately guarded maintenance
cycle; this package-only workflow does not claim full runtime remediation.
Other available APT updates remain visible to `os_updates_validation`.

After the Brotli patch, `playbooks/os_refresh_library_consumers.yml` can refresh
only `fwupd` processes retaining deleted Brotli mappings. It rejects other
consumers and requires fwupd's D-Bus status to be exactly IDLE (`u 1`) before
restarting the daemon. It performs no firmware update, device reset or node
reboot, and verifies that obsolete mappings disappear and boot IDs remain.
A busy/unknown daemon stops the play; never bypass the guard.

```sh
ansible-playbook playbooks/os_refresh_library_consumers.yml --limit worker-4
ansible-playbook playbooks/os_refresh_library_consumers.yml
```

## Rolling OS updates

Run from `infrastructure/ansible`:

```sh
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=os_updates_plan
os_update_canary=worker-2 # Select a worker without a database primary.
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=os_updates --limit "$os_update_canary"
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=os_updates
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=os_updates_validation
```

The planner checks dpkg consistency and filesystem space, refreshes HTTPS
metadata and simulates the full transaction. Package removals are rejected
unless inventory explicitly requires an installed replacement in that same
transaction; the default replacement map is empty. Downloads are verified
before changes. No release upgrade or repository-suite switch is performed.

The existing primary-aware ordering excludes database-primary workers and the
etcd leader from the initial canary, processes workers and then follower
servers serially, and stops on failed recovery. It never performs a database
failover or etcd leadership handoff automatically. Read the plan before applying.

Maintenance preserves K3s binaries/configuration and APT holds, suppresses
package-triggered service restarts until reboot, and validates full API, etcd,
storage, database, Fleet and application-controller recovery. Recovery waits
are bounded by `os_prep.maintenance_recovery_timeout` (default 1800 seconds,
minimum 600); preflight stays at 600 seconds. Unready or cordoned peers stop
advancement. Container image upgrades and their trust stores remain Git/Fleet
concerns rather than host package maintenance.

Canonical's installed `linux-image-raspi` package determines the expected kernel.
Pre-reboot checks validate current or staged `new/` boot artifacts against the
installed image/initramfs; post-reboot checks require the running vendor kernel,
native BTF, 4 KiB pages, matching modules and a good, completed A/B boot. The
vendor mechanism owns trial/fallback boot; Ansible neither rewrites fallback
images nor flashes EEPROM firmware. EEPROM maintenance is a separate operation.
This Ubuntu maintenance path still needs an explicitly authorized live canary
before a broad operational rollout; local fixtures and read-only validation do
not constitute a live package-upgrade qualification.

## Validation

`validation` checks the inventory hostname/timezone, packages, CA floors and
excluded roots, Ubuntu sources, supervised maintenance policy and sudo access.
Each `required_nfs_exports` entry is tested with an actual bounded, disposable
read-only NFSv3/TCP mount. Its temporary mount is unmounted normally and the
empty directory removed even on failure; no force/lazy unmount or NAS ACL edit
is used. New client addresses must already be allowed by the NAS.

Raspberry Pi kernel/module/boot and NVMe health checks live in the permanent
`rpi_prep` and `smartctl_exporter` validation entrypoints.

## Remote node recovery and kernel evidence

`playbooks/node_recovery.yml` manages all nine nodes without restarting K3s,
upgrading packages, changing kernel/boot parameters or rebooting hosts. It starts
three rootless, bounded UDP/6666 kernel receivers on the control-plane hosts,
then changes and validates one host at a time. Receivers run under systemd,
outside Kubernetes; they do not depend on pod scheduling or local kubelet health.
Physical receiver MACs are discovered from facts at apply time, not pinned in Git.
The configuration accepts the nine managed Pi identities and is validated
before replacement, so an invalid source cannot be installed before a receiver
restart. Adding a worker also requires refreshing the three receivers' source
allowlists through this playbook.

The former PID 1 hardware-watchdog policy is retired: the 2026-10-29 network
outage left PID 1 responsive and feeding the device, so it did not recover the
node. The playbook removes only `/etc/systemd/system.conf.d/90-home-lab-recovery.conf`
and reloads the manager, restoring the default `RuntimeWatchdogSec=0`. It checks
that an active device permits disarming (`nowayout=0`) before making changes and
verifies an inactive device afterward. No second watchdog daemon, forced expiry,
manager reexec or reboot is used. Re-running the workflow cannot re-enable it.

Dynamic netconsole forwards critical kernel messages over the direct IPv4 LAN
to all three receivers (two peers for a receiver host). Existing console log
levels are retained so audit/info storms are not duplicated. Each UDP source
must be one of the nine inventory IPs. This allowlist is not authentication;
keep UDP/6666 on the trusted management LAN. Each record is JSON escaped,
bounded to 8KiB, and limited to 200 records/source/second, with a visible rate-limit
record. Receiver journal storage inherits the existing 512MiB/seven-day bounds.
UDP has no delivery acknowledgement; forwarding cannot survive a failed NIC,
switch, simultaneous receiver failure, or a hang before the kernel prints.

A bounded previous-boot warning summary is copied into the new boot's journal.
Existing pstore files are counted; no RAM reservation or untested ramoops address
is added. The kernel has pstore support but no configured backing region, so
pstore crash survival is not claimed. Existing persistent journals and Alloy's
central Loki transport remain enabled.

```sh
cd infrastructure/ansible
ansible-playbook --syntax-check playbooks/node_recovery.yml
ansible-playbook playbooks/node_recovery.yml --check
# Install the receivers first, then use worker-4 as the canary.
ansible-playbook playbooks/node_recovery.yml --limit k3s_servers
ansible-playbook playbooks/node_recovery.yml --limit worker-4
ansible-playbook playbooks/node_recovery.yml
ansible-playbook playbooks/node_recovery.yml -e node_recovery_entrypoint=validation
```

Check mode performs only prerequisite reads. Validation checks that the retired
watchdog is disarmed, exact forwarding targets, enabled units and node readiness. An approved
transport test is `python3 /usr/local/libexec/home-lab-node-recovery canary` via
Ansible: one explicitly tagged ERR-priority `home-lab-netconsole-canary` kernel
record crosses the unchanged console threshold. It does not inject a real
error, panic, stall or reboot. Search Loki for
`{job="node/system",unit="home-lab-kernel-receiver.service"} |= "home-lab-netconsole-canary"`.
Extract the outer journal `MESSAGE` before parsing `source_node`; the indexed
`node` is the receiving machine:

```logql
{job="node/system",unit="home-lab-kernel-receiver.service"}
  | json | line_format "{{.MESSAGE}}" | json | source_node="k8s-rpi7"
```

Do not repeatedly emit the kernel canary as an error alert source.

The minute evidence timer remains enabled for netconsole health and the rpi7
NIC collector. It exports `home_lab_host_recovery_netconsole_targets`,
`home_lab_host_recovery_expected_targets` and
`home_lab_host_recovery_last_check_seconds` through the node-exporter textfile
collector. The old watchdog metrics and inactive-watchdog alert are removed.
These metrics prove local configuration health; the canary proves end-to-end
forwarding and Loki ingestion. To retire kernel forwarding separately, encode
the change in Git, disable the netconsole unit and only its `home_lab_*` configfs
targets. Do not unload netconsole if other targets exist, open the watchdog from
another process, or force a reboot to test recovery.

## macb network TX-stall canary

The [rpi1 Ubuntu kernel canary](../../../../docs/runbooks/macb-kernel-canary.md)
records the recovery-event ranking, selected kernel, acceptance and recovery-policy limitation.

The 2026-10-29 rpi7 outage was a partial connectivity failure: old-boot journal
records show PID 1 and the recovery timer still running throughout the 17-minute
network outage. K3s could not reach direct control-plane addresses, and Cilium
could not reach the API VIP. PID 1 kept feeding the hardware watchdog, so the
watchdog did not expire. Hardware-watchdog activation is not proof of network
health or a successful expiry test.

This is consistent with [Ubuntu bug 2133877](https://bugs.launchpad.net/bugs/2133877)
and the [upstream macb TX-timeout recovery fix](https://github.com/torvalds/linux/commit/e438ec3e9e95).
The exact driver TX-stall signature was not captured locally, so this remains a
source-backed mitigation rather than a proven root-cause fix. Only rpi7 is opted
in through host inventory. Its `macb` driver and default TSO/SG settings match
the affected family. `ethtool -K eth0 tso off sg off` disables those two offloads;
Linux may also disable dependent features. The original complete feature list
is retained once at `/var/lib/home-lab-node-network/offloads-before.txt`.

```sh
cd infrastructure/ansible
ansible-playbook --syntax-check playbooks/macb_network.yml
ansible-playbook playbooks/macb_network.yml --check --limit worker-4
ansible-playbook playbooks/macb_network.yml --limit worker-4
ansible-playbook playbooks/macb_network.yml -e macb_network_entrypoint=validation --limit worker-4
```

The enabled oneshot applies before K3s at future boots. Runtime application does
not restart the interface, K3s or the host. Check mode reads prerequisites only;
validation checks offloads, enabled state, three peer APIs and node readiness.
The existing minute health service also records RX/TX counters, carrier, errors,
offloads and bounded qdisc status. These queue through Alloy/Loki, including
replay after a failed network path, and appear as `home_lab_macb_*` textfile
metrics. Read the JSON NIC evidence from `home-lab-recovery-health.service`.
Extra CPU cost from disabling offloads must be observed under representative
traffic before expanding the canary. A successful apply does not prove days-long
stability; the upstream timeout fix in a supported Ubuntu kernel is the longer-term
recovery path, subject to release and reboot gates.

For rollback, first set the inventory opt-in false in Git. Disable
`home-lab-macb-offloads.service`, remove only the managed `30-macb.conf` health
drop-in, reload systemd, and restore the original feature states from the saved
snapshot using ethtool. The captured rpi7 baseline had SG, TSO and GSO enabled;
restore them together with `ethtool -K eth0 sg on tso on gso on`. Retain the
snapshot and remove the obsolete `home_lab_macb.prom` textfile. Do not reboot or
blindly restore unrecorded NIC settings. The retained netconsole
policy continues to collect evidence for its covered failure modes.
