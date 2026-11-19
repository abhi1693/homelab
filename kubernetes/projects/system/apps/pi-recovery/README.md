# Pi Recovery deployment

Fleet deploys the ARM64-only [Pi Recovery v0.0.7](https://github.com/abhi1693/pi-recovery/tree/v0.0.7)
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
seconds. Active and uncertain recoveries, and failed control-plane recoveries,
remain globally interlocked independently of the cooldown. A recorded worker
verification failure may yield to a control-plane recovery after the Lease and
cooldown expire. Its `deferred_failure` remains in the ledger across aborted
checks and successful control-plane recovery, keeps review metrics active, and
blocks worker retries until its exact action ID is acknowledged through Git.
Live role inventory, resourceVersion fencing and all final safety checks still
apply. Recent audit history is bounded and is not a recovery quota.

Pre-failure CPU and I/O checks prefer rates. If only one successful post-boot
scrape exists, valid current-boot counter averages can be used after at least
two minutes of measured uptime. The 15-minute recent-boot guard still applies.
Missing or ambiguous evidence blocks recovery; logs identify the missing check
and whether resource evidence uses a rate or a boot average.

Saturation readings from the last successful scrape remain a veto for five
minutes. Older readings are explicitly historical: they require at least three
minutes of independently fresh switch evidence proving a frozen transmit path
while inbound traffic advances. Logs include the evidence timestamp, age, values
and decision. Missing, invalid or over-one-hour-old resource evidence still
blocks recovery. Every peer, quorum, maintenance, identity, port and power check
remains mandatory, including immediately before reserving the action. This does
not distinguish every silent NIC failure from a wider OS or storage hang.

## Configuration and credentials

`secrets.sops.yaml` is an encrypted SopsSecret. The existing SOPS operator renders
`pi-recovery-runtime`; the receiver mounts `config.json`, and Alertmanager reads
the matching webhook bearer token. Never commit decrypted configuration.

Deployment environment pins this installation's exact approved kernel allowlist, node-exporter
port, Lease namespace, state annotation and maintenance annotation. The encrypted
configuration contains the reviewed controller certificate, application version,
switch identity, physical NIC bindings and node-to-port mappings. Start a new
installation in observation mode with `enabled=false`.

A change to Secret configuration also needs a new pod-template
`home-lab.io/policy-revision` value so both replicas reload it. Intended changes
flow through Git and Fleet.

The reviewed UniFi Network version is `11.0.99`. Its upgrade migrated the legacy
switch API ID to a UUID; Pi Recovery v0.0.7 accepts this format while retaining
exact version, certificate, integration ID, legacy ID and physical MAC checks.
The replacement pins were verified against both APIs and all nine port schemas.

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

## Nine-node inventory correction

The runtime inventory now includes `k8s-rpi9` at `192.168.3.245`. Its physical
Ethernet MAC was read directly from the host and independently matched to port 9
of the configured switch, with one learned device, link up and healthy PoE.
The prior eight-node inventory made the strict live-node equality check reject
alerts after the ninth worker joined; the webhook surfaced that refusal as HTTP
400 `invalid payload`. No parser, power limits or safety guards are relaxed.

The encrypted configuration changes only the node inventory. A new pod-template
policy revision reloads it on both replicas; credentials, approved kernel,
existing physical bindings and retained action ledger remain unchanged. Adding
or removing a node must include this explicit inventory reconciliation, with
independent physical-port verification before enabling recovery for a new node.

## Reviewed rpi5 recovery acknowledgement

The encrypted configuration acknowledges only action
`4b47fbc9-d0d7-4f2f-997c-eab1d0e1c783`. That earlier worker attempt failed
verification, but rpi5 subsequently returned Ready and hosted healthy workloads
before a separate outage. This exact acknowledgement permits a fresh assessment;
it does not issue a power cycle or acknowledge any future failure. The retained
Lease, cooldown, quorum, physical switch evidence and final checks remain in
force. Policy revision `6-reviewed-rpi5-action-ack` reloads both receivers.

## Reviewed rpi3 recovery acknowledgement

The encrypted configuration acknowledges only action
`d5bfa81c-0f18-4f51-8d35-67cda6592fb3` from November 12, 2026.
The power cycle at 04:02:22 UTC was followed by a new boot at 04:02:45 UTC,
but the node did not report Ready until 04:13:10 UTC, beyond the 450-second
verification window. Read-only review confirmed the node Ready, a healthy
node-exporter scrape, and all nine cluster nodes Ready before acknowledgement.
The ledger does not retain the original node UID and boot ID snapshot, so the
historical recovery verification is limited to available boot-time and status evidence.

This acknowledgement permits fresh recovery assessment without deleting or
resetting the retained Lease, forcing a power cycle, or acknowledging future
failures. Policy revision `8-reviewed-rpi3-action-ack` reloads both replicas.
The review alert can remain active while the ledger retains its failed phase;
do not manufacture a recovery solely to clear the notification.

## Mixed control-plane kernel rollout

Pi Recovery v0.0.7 accepts the explicit JSON-array `APPROVED_KERNELS` allowlist
containing only `7.0.0-1020-raspi` and `7.0.0-1023-raspi`. This covers the
unchanged workers and upgraded control-plane nodes. It is exact matching, not a
range, wildcard or prefix; unknown kernels remain blocked. Policy revision
`9-exact-mixed-kernel-allowlist` reloads both replicas. No encrypted credentials,
node bindings, cooldowns, quorum checks, physical evidence checks, action
acknowledgements or retained recovery ledger are changed. Deployment does not
request a power cycle.
