# Scripts

This directory contains small operator utilities that do not belong to a single
Ansible role or Kubernetes app bundle.

## Script Catalog

| Script | Purpose |
| --- | --- |
| `monitoring-migration-state.py` | Captures private monitoring/dashboard inventories using read-only APIs and compares resource identities, scrape/rule coverage, and preparation gates. See the [migration runbook](../docs/runbooks/rancher-monitoring-migration.md). |
| `k8s-secret-to-sops-secret.py` | Converts an existing Kubernetes Secret shape into a SOPS Secrets Operator style resource. |
| `check-kubernetes-resource-bounds.py` | Requires CPU/memory requests and memory limits on directly authored Kubernetes workloads, and rejects recommendation profiles whose minimum-change threshold can block their maximum decrease step. |
| `check-renovate-policy.py` | Verifies non-critical GitOps dependency coverage and keeps cluster-foundational dependencies under manual upgrade control. |
| `check-postgresql-observability.py` | Uses `promtool` and PyYAML to validate PostgreSQL alerts, small-table thresholds, table overrides, and primary-only evaluation. |
| `post-node-power-on.sh` | Helper for node power-on recovery or post-power operations. |
| `setup-pre-commit.sh` | Installs the pinned pre-commit Python and native validation tools and configures the Git hook on Linux. |
| `run-pre-commit-validation.sh` | Runs the Ansible, YAML, Kubernetes, Terraform, shell, and Dockerfile checks used by the repository's pre-commit hooks. |
| `safe-node-shutdown.sh` | Helper for guarded node shutdown workflows. |
| `sync-readme-versions.py` | Reads pinned platform versions from Git-managed source files and checks or updates the static root README badge values. |
| `validate-tempo.py` | Verifies the pinned Tempo image and ConfigMap in local Docker, then checks readiness and an OTLP trace round trip. |

## How These Fit The Lab

Scripts here are supporting tools, not the primary deployment mechanism. Normal
desired state should live in Ansible or Kubernetes manifests. A script belongs
here when it helps with conversion, migration, or controlled operator action.

When a script becomes part of a reconciled workload, move that behavior into the
owning app bundle or Ansible role so it is visible in the desired state.

Standalone Firefly III statement import utilities are maintained in
[`abhi1693/firefly-importer`](https://github.com/abhi1693/firefly-importer).
