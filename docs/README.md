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
| `runbooks/README.md` | Standard format for new runbooks. |
| `runbooks/fleet-namespace-psa-labels.md` | Procedure for namespace ownership and Pod Security Admission label changes under Fleet. |
| `runbooks/jellyfin-sqlite-to-postgresql-migration.md` | Notes for Jellyfin SQLite to PostgreSQL migration rehearsal. |
| `runbooks/networking/laptop-wireguard-mtu-tls-handshake-timeouts.md` | Diagnosis and fix for laptop WireGuard MTU blackholes causing Kubernetes API and `*.home` TLS timeouts. |
| `runbooks/storage/longhorn-disk-available-space-alerts.md` | Diagnosis and mitigation for Longhorn disk schedulable space warning and critical alerts. |

## How To Add Docs

Prefer app-local READMEs when the documentation only applies to one bundle.
Use `docs/` when the procedure crosses project boundaries, changes operational
policy, or records a decision that future operators need to understand.
