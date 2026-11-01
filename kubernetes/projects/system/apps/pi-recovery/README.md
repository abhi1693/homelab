# Pi Recovery deployment

Fleet deploys the ARM64-only [Pi Recovery v0.0.3](https://github.com/abhi1693/pi-recovery/releases/tag/v0.0.3)
image by immutable digest. Application code, runtime tests and image publishing
live in [abhi1693/pi-recovery](https://github.com/abhi1693/pi-recovery).
This directory owns deployment, encrypted configuration, networking and bootstrap.

## Runtime policy

Two replicas run on separate ARM64 workers. Each requests `10m` CPU and `32Mi`
memory, capped at `100m` and `96Mi`. The image runs as UID/GID 10001 with a read-only
root filesystem, no capabilities, and no host or SSH access.

An alert starts checks against Kubernetes, Prometheus and independently pinned
UniFi switch evidence. Three fresh switch observations must establish a frozen
transmit path before one PoE cycle is reserved. The reviewed static node-to-port
binding can be used if a silent NIC's learned MAC entry aged out. Foreign MACs,
multiple learned devices, physical errors, unhealthy power and ambiguous evidence
still block the action.

Up to two unavailable nodes are supported by default. Healthy peers must remain
reachable and control-plane quorum must be intact. Kubernetes role labels give
control-plane nodes priority over workers, including during the final pre-cycle
check. Only one action can be reserved or verified at a time.

There are no per-node or cluster-wide daily quotas. `cooldown_seconds` in the
runtime JSON configuration controls the global cooldown, defaulting to `300`
seconds. Active, failed and uncertain recoveries remain interlocked independently
of the cooldown. Review an uncertain action before acknowledging its exact action
ID through Git. Recent audit history is bounded and is not a recovery quota.

Pre-failure CPU and I/O checks prefer rates. If only one successful post-boot
scrape exists, valid current-boot counter averages can be used after at least
two minutes of measured uptime. The 15-minute recent-boot guard still applies.
Missing or ambiguous evidence blocks recovery; logs identify the missing check
and whether resource evidence uses a rate or a boot average.

## Configuration and credentials

`secrets.sops.yaml` is an encrypted SopsSecret. The existing SOPS operator renders
`pi-recovery-runtime`; the receiver mounts `config.json`, and Alertmanager reads
the matching webhook bearer token. Never commit decrypted configuration.

Deployment environment pins this installation's approved kernel, node-exporter
port, Lease namespace, state annotation and maintenance annotation. The encrypted
configuration contains the reviewed controller certificate, application version,
switch identity, physical NIC bindings and node-to-port mappings. Start a new
installation in observation mode with `enabled=false`.

A change to Secret configuration also needs a new pod-template
`home-lab.io/policy-revision` value so both replicas reload it. Intended changes
flow through Git and Fleet.

## Retained recovery state

The runtime Lease is `cattle-monitoring-system/pi-recovery-lock`. It records a
reservation before the non-idempotent UniFi request. Ambiguous power requests
are not retried automatically; a new boot ID, unchanged node UID, Ready status
and a healthy scrape are required to confirm recovery.

The chart creates the initial Lease with `helm.sh/resource-policy: keep`. Normal
upgrades omit it and leave its runtime state untouched. The app can get/update
that Lease but cannot create or delete it. Do not delete it to clear an interlock.

The completed legacy migration restored the verified recovery action and added
the keep policy before detaching the ledger from normal chart updates.
`ledgerBootstrap.migrateExisting` must remain `false`. Re-enabling migration
requires reviewing the live UID, resourceVersion and complete action history;
the recorded old resourceVersion must conflict after any concurrent write.
Fleet cannot use live Helm lookups during chart rendering.

Monitoring CRDs are bootstrap prerequisites. Receiver updates deliberately do
not depend on the monitoring bundle being Ready: an unreachable Pi can leave its
DaemonSets at 7/8 or 6/8. Fleet retries resources until their CRDs are available.

## Observe recovery

Inspect `pi_recovery` JSON logs for `lease_requested`, `lease_acquired`, `observed`,
`confirmed`, `reserved`, `cycled`, `verification_pending`, `recovered` and
`lease_released`. Refusals contain a stable reason. The observer node and pod
identify the replica handling the attempt; there is no permanent primary.
Verification progress appears at most once per minute. Routine scrapes stay quiet.

`/metrics` exposes event counters, automatic mode, ledger-read health and review
state. Readiness means the receiver can accept requests; dependency checks run
for every candidate. Existing node alerts still notify the operator if automatic
recovery is blocked.

## Validate

```sh
helm lint kubernetes/projects/system/apps/pi-recovery
helm template pi-recovery kubernetes/projects/system/apps/pi-recovery -n cattle-monitoring-system
python3 -m unittest discover -s kubernetes/projects/system/apps/pi-recovery/tests -v
python3 scripts/validate-workload-catalog.py
```

Use `--is-upgrade` when rendering to verify that normal upgrades omit the Lease.
Run application tests in the dedicated Pi Recovery repository. Release and verify
an ARM64 image there before changing this deployment's digest.
