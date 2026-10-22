# Operating System Preparation

`main` prepares a host during bootstrap, including a distribution upgrade that
can request a reboot. `validation` checks hostname, timezone, common packages,
host security baselines, and pending-reboot state.

## Rolling OS Updates

Use the maintenance entrypoints for an established cluster:

| Entrypoint | Behavior |
| --- | --- |
| `os_updates_plan` | Converge the managed Debian HTTPS source policy, refresh metadata, and report the transaction and host prerequisites without changing installed packages or rebooting. |
| `os_updates` | Upgrade packages from existing Debian 13 repositories, reboot when needed, and require recovery before advancing. |
| `os_updates_validation` | Check installed packages, running and boot kernels, security baselines, and cluster health without updates or restarts. |

Run from `infrastructure/ansible`. Review the plan's current database-primary
placement and select a worker that does not host a primary for the canary:

```sh
ansible-playbook --syntax-check playbooks/os_prep.yml
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=os_updates_plan
os_update_canary=worker-2 # Example; choose from the current plan, not a saved primary location.
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=os_updates --limit "$os_update_canary"
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=os_updates
ansible-playbook playbooks/os_prep.yml -e os_prep_entrypoint=os_updates_validation
```

Planning first applies the inventory's exact HTTP-to-HTTPS URI replacements to
the managed official Debian source files. It preserves their suites, components,
signing keys, and other fields, and leaves Raspberry Pi archive URLs untouched.
The smartctl backports source uses the same HTTPS policy so later role runs
preserve it. Validation rejects a managed Debian URI that still uses HTTP.

Plan and apply first read each CloudNativePG Cluster's current primary and its
owned instance Pod to map it to the inventory. They preserve the selected host
set, process servers in inventory order, then non-primary workers, then current
primary workers. This leaves updated failover candidates available for the
primary's reboot. A missing, ambiguous, or transitioning primary stops selection.
The order is a placement snapshot at the start of each invocation; it does not
perform a switchover or promise unchanged placement during unrelated activity.

Planning refreshes APT metadata because a stale cache can incorrectly report
that no updates exist. Check mode leaves metadata unchanged and therefore
cannot replace the live plan. The apply entrypoint recalculates the transaction
before changing packages. It preserves package holds and permits removals only
when the inventory declares a matching replacement package.

The apply entrypoint downloads the complete transaction with native APT before
installation or disruptive maintenance. APT verifies archives against its
authenticated metadata, retaining valid cached packages. A download or checksum
failure stops the workflow before packages are installed; investigate the
rejected object and source metadata before retrying. Keep signature and hash
verification enabled, and preserve useful evidence from the failed transfer.

Each host must pass API, etcd consensus, node, Longhorn, PostgreSQL, Fleet, and
all Deployment, StatefulSet, and DaemonSet readiness checks before package
changes. The workflow updates one host at a time, suppresses automatic service
restarts during installation, and reboots when packages changed or the running
kernel requires it. It stops
remaining hosts on failure and requires stable recovery samples before
advancing. Services with a single replica restart when their host reboots.
Preflight has a 600-second limit. Recovery and standalone validation allow
`os_prep.maintenance_recovery_timeout` seconds (1800 by default, minimum 600),
so storage rebuilds can finish after an OS reboot. The readiness requirements
remain the same throughout that bounded wait.

The update records and verifies K3s binary and configuration checksums. It
checks the running kernel against the installed current-flavor kernel and the
firmware boot image, verifies the package manager has no unfinished work, and
reports the Raspberry Pi EEPROM state without changing its update policy.
It recognizes both boot-partition staging files and the upstream updater's
current-boot reboot marker, including immediate SPI updates. If the existing
boot service records an update, it allows one additional reboot after full
recovery and requires all pending update state to clear before advancing.
K3s versions, distribution releases, and application image updates retain their
existing owners and workflows.

Keep Cilium at the inventory/Fleet pin while updating these Raspberry Pi
kernels; the existing BTF compatibility restriction still applies.

## Host Security Baselines

The inventory owns persistent policy through `os_prep.minimum_packages`,
`os_prep.distrusted_ca_sha256`, `os_prep.package_replacements`, and
`os_prep.apt_https_sources`.

The package baseline includes Debian 13 `ca-certificates >= 20250419+deb13u1`,
the [Debian security update](https://lists.debian.org/debian-security-announce/2026/msg00487.html)
for the compromised eMudhra certificate chains. The distrusted SHA-256
fingerprints identify the `emSign ECC Root CA - G3` and `AAA Certificate Services`
trust anchors. Validation checks the installed package floor and confirms a
fresh TLS context excludes those roots. Package replacement policy currently
records Raspberry Pi OS's `pcmanfm` to `pcmanfm-pi` transition.

Reboots refresh long-lived services that cache trust. Container images retain
independent CA stores and embedded runtimes; update them through their own
GitOps image workflows.

## Development Validation

The repository's Ansible pre-commit check runs every role's regression tests.
This role tests transaction replacement policies, exact archive URI changes,
transport validation, and download ordering. It renders embedded Python
through Jinja before compiling it, catching template collisions before a live
maintenance run.

```sh
scripts/run-pre-commit-validation.sh ansible
```
