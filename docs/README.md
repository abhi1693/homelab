# Documentation

This directory contains longer-form architecture decisions and runbooks.

## What Belongs Here

Use `docs/` for information that is too broad or operationally sensitive to
hide inside a manifest comment:

- architecture decisions and their tradeoffs;
- procedures that operators need to follow carefully;
- migration notes;
- recovery plans;
- known limitations and future hardening work.

## Directory Map

| Path | Purpose |
| --- | --- |
| `architecture/` | Architecture decision records and design narratives. |
| `runbooks/` | Operational procedures for recurring or high-risk tasks. |
| `runbooks/networking/` | Client, LAN, VPN, and ingress-path operational procedures. |
| `runbooks/storage/` | Storage, persistence, and Longhorn operational procedures. |

## Current Documents

| Document | Purpose |
| --- | --- |
| `architecture/adr-001-jellyfin-horizontal-scaling.md` | Design decision for Jellyfin horizontal scaling work. |
| `architecture/eight-node-cluster-expansion-roadmap.md` | Phased roadmap for expanding to three control-plane nodes and five workers, isolating user scheduling, and migrating Longhorn placement safely. |
| `architecture/unifi-enterprise-network-roadmap.md` | Dated UniFi audit, target segmentation and topology, hardware integration, security hardening, phased validation, and rollback plan. |
| `architecture/lan-service-resilience-incident-review.md` | Evidence-based ISP-outage learning review and Layer 2 service exposure decision. |
| `runbooks/README.md` | Standard format for new runbooks. |
| `runbooks/alertmanager-firing-alert-triage.md` | Live Alertmanager inventory, synthetic-alert interpretation, and evidence-preserving failed-Job cleanup. |
| `runbooks/completed-torrent-import-recovery.md` | Safe recovery for completed torrents blocked by Arr mappings, including copy-first Sonarr pack-title repair and exact-hash cleanup. |
| `runbooks/fleet-namespace-psa-labels.md` | Procedure for namespace ownership and Pod Security Admission label changes under Fleet. |
| `runbooks/kubernetes-cpu-overcommit.md` | N-1 CPU request capacity diagnosis and evidence-backed request sizing. |
| `runbooks/kubernetes-resource-policy.md` | Production requests, limits, generated-container defaults, validation, and Longhorn exceptions. |
| `runbooks/k3s-node-maintenance.md` | Sequential K3s Raspberry Pi drain, clean shutdown, and recovery with kube-vip, PDB, Longhorn, Fleet, and controller gates. |
| `runbooks/node-saturation-and-zombie-processes.md` | Node load, CPU, I/O, D-state, and zombie-process diagnosis with targeted recovery. |
| `runbooks/statefulset-ondelete-rollout-recovery.md` | Sequential Valkey OnDelete rollout and Sentinel failover procedure. |
| `runbooks/k3s-rancher-upgrade-recovery-points-2026-08-11.md` | Recovery points and pre-state captured before the K3s/Rancher upgrade sequence. |
| `runbooks/jellyfin-sqlite-to-postgresql-migration.md` | Notes for Jellyfin SQLite to PostgreSQL migration rehearsal. |
| `runbooks/networking/laptop-wireguard-mtu-tls-handshake-timeouts.md` | Diagnosis and fix for laptop WireGuard MTU blackholes causing Kubernetes API and `*.home` TLS timeouts. |
| `runbooks/networking/unifi-netbox-drift-reconciliation.md` | Infrastructure-only UniFi API drift detection and reviewed NetBox MCP reconciliation; Network client data is excluded. |
| `runbooks/storage/anime-library-relocation-and-shoko-recovery.md` | Safe anime library relocation and Shoko unrecognized-file recovery. |
| `runbooks/storage/ryokan-batch-import-corruption-recovery.md` | Break-glass quarantine, download, manual import, and end-to-end verification for corrupt Ryokan batches. |
| `runbooks/storage/longhorn-disk-available-space-alerts.md` | Diagnosis and mitigation for Longhorn disk schedulable space warning and critical alerts. |
| `runbooks/storage/nfs-csi-volume-ownership-storms.md` | Root-squashed NFS fsGroup recursion, blocked mounts, and I/O-wait recovery. |
| `runbooks/storage/raspberry-pi-high-iowait.md` | Raspberry Pi I/O-wait diagnosis across NFS, Longhorn, PostgreSQL, and physical NVMe. |

## How To Add Docs

Prefer app-local READMEs when the documentation only applies to one bundle.
Use `docs/` when the procedure crosses project boundaries, changes operational
policy, or records a decision that future operators need to understand.
