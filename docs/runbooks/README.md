---
title: Runbooks
---

# Runbooks

Runbooks document repeatable operator procedures for known symptoms, alerts, or
high-risk maintenance tasks.

## Media

- [Completed torrent import recovery](completed-torrent-import-recovery.md):
  distinguish recoverable Arr mapping failures, safely copy Sonarr pack-title
  mismatches without the stale download association, and prove the library
  before cleaning exact torrents.

## Networking

- [UniFi infrastructure to NetBox drift detection and manual reconciliation](networking/unifi-netbox-drift-reconciliation.md):
  collect a secret-free infrastructure snapshot, exclude all Network client
  data, detect inventory drift, and apply only reviewed changes through the
  NetBox MCP server.

## Infrastructure inventory

- [NetBox hardware lifecycle data](netbox-hardware-lifecycle.md): distinguish
  product EOS/EOL from per-unit procurement, warranty, operational state, and
  retirement data before applying evidence-backed lifecycle updates.

## Standard Format

Use this structure for new runbooks:

- `Meaning`: what the symptom means and the affected system boundary.
- `Impact`: user-visible or operator-visible consequences.
- `Diagnosis`: read-only checks that confirm or rule out the issue.
- `Mitigation`: the smallest corrective action and any persistent fix.
- `Verification`: checks that prove the issue is resolved.
- `Rollback`: how to undo the mitigation if it causes a regression.
- `References`: upstream docs, related repo docs, or issue links.

Keep the first four sections present for every runbook. Add the remaining
sections when they help the operator apply or undo a local change safely.

## Storage

- [Longhorn disk available space alerts](storage/longhorn-disk-available-space-alerts.md):
  correlate schedulable space, volume health, host usage, and targeted image
  cache pruning without weakening disk reservation.
- [NFS CSI volume ownership storms](storage/nfs-csi-volume-ownership-storms.md):
  diagnose and stop root-squashed NFS `fsGroup` recursion, blocked pod starts,
  Job deadlines, and Raspberry Pi I/O wait.
- [Raspberry Pi high I/O wait](storage/raspberry-pi-high-iowait.md): distinguish
  an actual I/O queue from healthy synchronous Longhorn writes, then route to
  NFS, Longhorn, PostgreSQL, or physical-disk recovery.
- [Anime library relocation and Shoko recovery](storage/anime-library-relocation-and-shoko-recovery.md):
  move misplaced anime into the NAS anime library, preserve media-manager
  ownership, and repair unrecognized Shoko files.
- [Ryokan batch import corruption recovery](storage/ryokan-batch-import-corruption-recovery.md):
  quarantine a bad batch, recover only missing torrent files, perform a
  manifested manual import, and verify Ryokan, Shoko, and Jellyfin end to end.
- [NAS rebuild maintenance](storage/nas-rebuild-maintenance.md): stop all
  Kubernetes access to the NAS-backed media library before rebuilding the NAS.

## Kubernetes

- [K3s cluster to NetBox drift detection and manual reconciliation](k3s-netbox-drift-reconciliation.md):
  compare Git, live Kubernetes, hardware identity, UniFi attachment evidence,
  and NetBox before applying reviewed documentation updates through MCP.
- [K3s Raspberry Pi node maintenance](k3s-node-maintenance.md): preflight,
  drain, clean shutdown, physical maintenance, and recovery gates for one node
  at a time, including kube-vip and Prometheus PDB stop conditions.
- [Alertmanager firing alert triage](alertmanager-firing-alert-triage.md):
  inventory live alerts, interpret `Watchdog` and `InfoInhibitor`, and clean up
  only diagnosed obsolete failed Jobs.
- [Kubernetes CPU overcommit](kubernetes-cpu-overcommit.md): distinguish N-1
  scheduler capacity from runtime usage and right-size requests from history.
- [StatefulSet OnDelete rollout recovery](statefulset-ondelete-rollout-recovery.md):
  roll Valkey ordinals safely around Sentinel primary placement and quorum.
- [PgBouncer client queueing](postgresql-pgbouncer-client-queueing.md):
  distinguish backend saturation from PostgreSQL pressure and safely resize a
  session-mode application pool.
- [Node saturation and zombie processes](node-saturation-and-zombie-processes.md):
  separate CPU, load, I/O, and process-table pressure before a targeted repair.
- [Kubernetes resource policy](kubernetes-resource-policy.md): production
  requests, selective limits, generated-container defaults, and Longhorn
  exceptions.
