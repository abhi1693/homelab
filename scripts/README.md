# Scripts

This directory contains small operator utilities that do not belong to a single
Ansible role or Kubernetes app bundle.

## Script Catalog

| Script | Purpose |
| --- | --- |
| `k8s-secret-to-sops-secret.py` | Converts an existing Kubernetes Secret shape into a SOPS Secrets Operator style resource. |
| `post-node-power-on.sh` | Helper for node power-on recovery or post-power operations. |
| `safe-node-shutdown.sh` | Helper for guarded node shutdown workflows. |

## How These Fit The Lab

Scripts here are supporting tools, not the primary deployment mechanism. Normal
desired state should live in Ansible or Kubernetes manifests. A script belongs
here when it helps with conversion, migration, or controlled operator action.

When a script becomes part of a reconciled workload, move that behavior into the
owning app bundle or Ansible role so it is visible in the desired state.
