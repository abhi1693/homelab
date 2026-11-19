# MACB kernel canary on rpi1

## Selection evidence

The November 13, 2026 investigation queried the preceding 15 days of Loki logs
with `{namespace="cattle-monitoring-system"} |= "cycled"`, selecting JSON
`event="pi_recovery"`, `outcome="cycled"` records and deduplicating by
`action_id`. It returned 44 distinct actions, with event timestamps spanning
October 29, 23:43 UTC through November 12, 13:46 UTC. These are automatic power
cycles following suspected silent-transmit failures, not proof that every
incident was caused by MACB. General boot counts also include maintenance,
storage faults and clock anomalies and were not used to attribute the cause.

| Node | Distinct power cycles |
| --- | ---: |
| k8s-rpi1 | 14 |
| k8s-rpi2 | 1 |
| k8s-rpi3 | 11 |
| k8s-rpi4 | 3 |
| k8s-rpi5 | 9 |
| k8s-rpi6 | 0 |
| k8s-rpi7 | 2 |
| k8s-rpi8 | 0 |
| k8s-rpi9 | 4 |

## Authorized test

Selected `server-1` / `k8s-rpi1` (`192.168.3.243`), the highest-count node.
The test installs only Ubuntu `linux-raspi=7.0.0-1023.23` and required kernel
dependencies from the configured Ubuntu 26.04 updates/security repositories.
The previous running kernel was `7.0.0-1020-raspi`; the other eight nodes
remain on that kernel. Ubuntu first included the TX-stall timeout callback
and TX-buffer cleanup on close in `7.0.0-1021.21`.

A single-node Ansible transaction runs the existing `k3s_server` health gates
from server-2, preserves etcd membership, validates staged Ubuntu boot assets,
reboots only rpi1, and repeats the health and vendor-kernel checks. It does
not mutate Kubernetes resources or perform a general OS package upgrade.

The existing rpi7 offload mitigation remains in place. rpi1 retains its
existing offloads so observation tests the updated driver with normal traffic.

## Original recovery policy limitation

Pi Recovery v0.0.6 requires an exact global approved kernel of
`7.0.0-1020-raspi`. After this canary upgrade it refuses automatic power
cycling for rpi1 with `kernel_not_approved`; it continues to assess the
other eight nodes under the existing policy. Supporting both kernels requires
a separately validated per-node approval policy and Git/Fleet deployment.
Do not change the global pin to 1023 while the other nodes still run 1020.

## Acceptance

Acceptance passed at approximately November 12, 22:28 UTC (November 13 IST):

- The single-node Ansible transaction completed successfully, including the
  established preflight and post-reboot API/etcd/storage/database/Fleet gates
  with consecutive stability samples and unchanged etcd membership.
- rpi1 runs `7.0.0-1023-raspi`; its new boot ID is
  `52b90eb9-334e-474a-b13e-d61f1866bd64` (previously
  `319b264b-9539-4621-8d16-a962392e530b`). Other nodes remain on 1020.
- The loaded MACB module exposes `macb_tx_timeout`. TSO and scatter-gather
  remain enabled. A 10-packet peer ping had zero loss; NIC TX errors are zero.
- Vendor validation confirmed matching installed/running kernel and boot
  artifacts, completed `current/` A/B boot, native BTF, matching modules,
  4 KiB pages, and a consistent package database. No kernel error-priority
  messages were recorded in this boot during acceptance.
- All nine nodes and Longhorn nodes are Ready. All attached volumes are
  healthy; the existing idle, detached Wardn volume remains unchanged.
  PostgreSQL is 3/3, all Fleet bundles are Ready, and all Deployments,
  StatefulSets and DaemonSets have their desired ready counts.

During recovery, Cilium rate-limited the initial pod startup burst. Longhorn's
rpi1 manager retried settings-update conflicts and recovered automatically.
CUPS briefly lost its volume and recovered through its controllers. Monitoring
replicas rebuilt serially; the last rebuild retried a startup timeout and then
completed. No manual Kubernetes repair was performed.

A healthy reboot establishes compatibility only. Sustained observation is
needed to assess stall recurrence; do not expand the kernel rollout based
solely on this boot. Compare new recovery action IDs and kernel TX-timeout
messages against the baseline above. Automatic Pi Recovery for rpi1 remains
subject to the exact-kernel limitation described above.

Sources: [Ubuntu changelog](https://changelogs.ubuntu.com/changelogs/pool/main/l/linux-raspi/linux-raspi_7.0.0-1023.23/changelog)
and [upstream timeout recovery](https://github.com/torvalds/linux/commit/e438ec3e9e95).

## Controlled extension to the remaining control plane

On November 13, the operator authorized the same kernel-only upgrade on rpi2
and rpi3. The committed workflow is now `playbooks/os_kernel_update.yml`.
It requires one explicit server target, retains the same cluster-health gates,
installs only `linux-raspi=7.0.0-1023.23` and its kernel dependencies, and never
runs a general OS upgrade. Existing K3s files, APT holds and etcd membership
must remain unchanged. A node already running the installed target kernel is
validated without another reboot.

Run from `infrastructure/ansible`, one invocation at a time. Complete the first
node's API, etcd, Longhorn, database, Fleet and workload recovery before starting
the next node. Do not bypass a failed gate.

```sh
ansible-playbook --syntax-check playbooks/os_kernel_update.yml -e target=server-3
ansible-playbook playbooks/os_kernel_update.yml -e target=server-3
ansible-playbook playbooks/os_kernel_update.yml -e target=server-2
```

The initial rpi3 extension used the same kernel-only transaction before it was
moved into this committed playbook; rerunning the committed workflow validates
that node idempotently. These commands do not alter the Pi Recovery global
kernel policy described above. All upgraded nodes remain subject to that
exact-kernel limitation; the six workers stay on 1020.

### Extension acceptance

Verified on 2026-11-13 09:41 UTC: rpi2 and rpi3 both run
`7.0.0-1023-raspi`, matching rpi1. The repository playbook rerun on rpi3
completed with zero changes and skipped its reboot; rpi2 completed its bounded
kernel transaction and reboot. Both passed unchanged etcd membership, full
cluster/platform/workload recovery, vendor boot/native BTF checks, clean dpkg,
and preservation of K3s files and APT holds. Longhorn replica rebuilds finished
through normal controllers before acceptance. This establishes upgrade and
recovery success, not proof that the original network stalls can never recur.

## Dual-kernel recovery policy

The operator subsequently authorized Pi Recovery v0.0.7 to accept an explicit
allowlist of `7.0.0-1020-raspi` and `7.0.0-1023-raspi`. This supersedes the
original single-kernel limitation above while mixed worker/control-plane
kernels remain in service. Home Lab configures `APPROVED_KERNELS` with exactly
those two releases. All non-kernel safety checks and retained state remain
unchanged; no recovery action is triggered to validate this policy.
