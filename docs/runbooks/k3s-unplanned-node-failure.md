---
title: Unplanned K3s Node Failure
---

# Unplanned K3s Node Failure

Use this procedure when a host has failed and cannot return to service. Planned
maintenance uses [the drain and shutdown runbook](k3s-node-maintenance.md).
These live mutations require explicit break-glass authorization under
`AGENTS.md`; this document does not grant that authorization.

## Preconditions

Confirm physically that the failed host is powered off and keep it off during
failover. Ping or SSH failure alone does not establish that workloads have
stopped. Never detach storage from a host that could still be writing to it.
Record its last heartbeat, boot identity, affected pods and volume attachments.
Check the surviving nodes and PostgreSQL quorum before proceeding.

For each affected Longhorn volume, inspect its engine `replicaModeMap` and
replica node placement. Confirm surviving `RW` replicas on healthy nodes and
enough free storage for rebuilding. Do not equate a bound PVC with healthy data.

```sh
FAILED_NODE=k8s-rpi7
kubectl get node "$FAILED_NODE" -o yaml
kubectl get pods -A --field-selector "spec.nodeName=$FAILED_NODE" -o wide
kubectl get volumeattachments.storage.k8s.io -o json
kubectl -n longhorn-system get volumes.longhorn.io -o wide
kubectl -n longhorn-system get engines.longhorn.io -o json
kubectl -n longhorn-system get replicas.longhorn.io -o json
```

## Release stranded pods and attachments

After power-off confirmation and authorization, use Kubernetes non-graceful
shutdown handling. Preview the exact mutation first, then apply it:

```sh
kubectl taint node "$FAILED_NODE" \
  node.kubernetes.io/out-of-service=nodeshutdown:NoExecute --dry-run=server
kubectl taint node "$FAILED_NODE" \
  node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
```

The controller force-deletes pods that lack a matching toleration and detaches
their volumes. Replacement workloads can then start on healthy nodes. Do not
delete PVCs, PVs, or volume attachments manually. Some system DaemonSets tolerate
all taints and can remain represented on the failed node; that does not mean
the host is running.

Verify that no storage attachment remains on the failed node, replacement
pods become Ready, StatefulSets regain their replicas, and real application
health endpoints work. Check Valkey replication/Sentinel and PostgreSQL health
separately from pod readiness.

## Restore storage redundancy

If Longhorn still has stopped replicas assigned to the failed node and cannot
replenish them, request evacuation after checking surviving replicas and free
space. Obtain authorization for this additional live mutation when it was not
included in the original break-glass scope.

```sh
kubectl -n longhorn-system patch nodes.longhorn.io "$FAILED_NODE" \
  --type=merge \
  -p '{"spec":{"allowScheduling":false,"evictionRequested":true}}' \
  --dry-run=server
kubectl -n longhorn-system patch nodes.longhorn.io "$FAILED_NODE" \
  --type=merge \
  -p '{"spec":{"allowScheduling":false,"evictionRequested":true}}'
```

Longhorn rebuilds replacement replicas before retiring the evicted placement.
Wait for all active volumes to report `healthy` with their configured replica
count, and for the failed node's scheduled replica count to reach zero. Preserve
the configured three-replica policy and do not delete stopped replica resources
just to clear degraded status. If rebuilding stalls, inspect manager logs,
engine rebuild status, disk capacity and scheduling conditions.

## Verification and return to service

Recheck Fleet desired/applied revisions, Deployment/StatefulSet readiness,
storage health, both Prometheus replicas, and application endpoints. A powered-off
registered node remains `NotReady`; node/exporter alerts and affected system
DaemonSet reports must stay visible until hardware recovery or a separately
reviewed retirement. Application failover does not make the failed host healthy.

Record the out-of-service taint and Longhorn scheduling/eviction settings in
the incident handoff. Before returning the host, repair and validate its power,
boot disk and K3s services, confirm healthy replacement workloads and storage,
and obtain authorization for return-to-service mutations. Remove the taint
only once the host is recovered. If evacuation was requested, cancel it before
re-enabling Longhorn scheduling. Follow the normal maintenance runbook's
network, storage, monitoring and Fleet recovery checks; do not simply power
the host on and assume it has rejoined safely.

## Incident: k8s-rpi7, 26 September 2026

At `13:46:47 UTC` (`19:16:47 IST`), Loki retained four host log-read failures
across the Valkey, PostgreSQL pooler and monitoring pods on `k8s-rpi7`. Each
reported `input/output error` while opening or reading `/var/log/pods/...`.
Those paths reside on the NVMe root filesystem. Kubernetes marked the node
unreachable at `13:47:34 UTC`. The host initially answered ping while SSH,
kubelet and exporters refused connections. This is evidence of a host storage
I/O failure; it does not identify the exact failed hardware component.

Pre-outage monitoring showed roughly 68 C CPU temperature, NVMe sensors below
53 C, more than 7 GiB available memory, and over 300 GiB free root storage.
No OOM kills, firmware undervoltage/throttling flags, or UPS on-battery state
were recorded in the inspected pre-failure window. Following recovery, NVMe
SMART reported no media/data-integrity errors, no error-log entries, and no
temperature warning time. These observations do not rule out a transient
controller, PCIe connection, local power, or unmonitored thermal fault.

The operator unplugged the node, let it cool, and plugged it back in. While it
was confirmed off, an explicitly authorized out-of-service taint released
stranded pods and four attachments. Sonarr, Profilarr, Episeerr and Valkey
recovered on other nodes. Once SSH, K3s, clock synchronization and node readiness
were verified after power-on, the temporary taint was removed. The proposed
Longhorn node evacuation was never applied; its scheduling and eviction
settings remained unchanged. All 27 attached volumes subsequently became
healthy, all eight nodes were Ready, and all Fleet GitRepos were Ready. The
retained, intentionally detached Wardn Hub Codex volume was not activated.

The previous kernel journal could not be recovered: Raspberry Pi OS's
`/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf` sets
`Storage=volatile`, and pstore was empty. Alloy collects pod logs, not host
journals. Persistent or remotely shipped host kernel logs are the next
diagnostic improvement; no boot, power-management, or journald settings were
changed during this recovery. Cooling and power-cycling restored service, but
the available evidence does not establish overheating as the root cause.

## References

- [Kubernetes non-graceful node shutdown](https://kubernetes.io/docs/concepts/cluster-administration/node-shutdown/#non-graceful-node-shutdown-handling)
- [Longhorn node and disk eviction](https://longhorn.io/docs/1.12.1/nodes-and-volumes/nodes/disks-or-nodes-eviction/)
