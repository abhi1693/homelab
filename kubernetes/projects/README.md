# Kubernetes Projects

This directory groups Fleet-managed workloads by Rancher project.

## Why Projects Exist

Projects are the main organizational boundary in the cluster. They separate
workloads by operational domain:

- application workloads;
- shared database services;
- development tooling;
- media automation;
- home automation;
- system services.

This keeps bundle ownership, namespace labels, network policy, observability,
and drift correction easier to reason about than a single flat app directory.

## Project Map

| Project | Path | Owns |
| --- | --- | --- |
| Applications | `applications/` | Public apps, personal apps, Harbor, Renovate image automation, and application-specific workers. |
| Database | `database/` | CloudNativePG, PostgreSQL, Valkey, poolers, and database network boundaries. |
| Development | `development/` | Development project metadata and future development workloads. |
| Entertainment | `entertainment/` | Media stack, media storage, torrent/import workflows, and request portals. |
| Home Automation | `home-automation/` | Home Assistant, NetBox, rack automation, Cloudflare tunnel control, and UPS monitoring. |
| System | `system/` | Monitoring, logging, tracing, profiling, DNS, backup, compliance, operators, and cluster maintenance. |

## Directory Shape

Each project can contain:

| Path | Purpose |
| --- | --- |
| `_project/` | Rancher project metadata managed separately from apps. |
| `apps/<app>/` | One Fleet app bundle or GitOps wrapper bundle. |
| `README.md` | Project-level operating notes and app catalog. |

Application bundles are intentionally local. A bundle should carry the manifests
needed to understand its runtime shape: `fleet.yaml`, deployments, services,
ingress, PVCs, network policies, monitoring, HelmOp values, jobs, and README
documentation.

## Reconciliation Model

The `kubernetes/fleet/fleet-project-gitrepos/` directory defines one Fleet
GitRepo per project. Each GitRepo lists the app paths Fleet should reconcile.
This makes project failures easier to isolate while keeping each project bundle
small enough to reason about independently.
