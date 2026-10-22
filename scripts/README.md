# Scripts

This directory contains small operator utilities that do not belong to a single
Ansible role or Kubernetes app bundle.

## Script Catalog

| Script | Purpose |
| --- | --- |
| `monitoring-migration-state.py` | Captures private monitoring/dashboard inventories using read-only APIs and compares resource identities, scrape/rule coverage, and preparation gates. See the [migration runbook](../docs/runbooks/rancher-monitoring-migration.md). |
| `migrate-devfeed-identities.py` | Plans or atomically remaps DevFeed user, partner and admin-preference identities while preserving account UUIDs; apply requires all three sign-in APIs stopped through Fleet. See the [identity migration runbook](../docs/runbooks/devfeed-identity-migration.md). |
| `k8s-secret-to-sops-secret.py` | Converts an existing Kubernetes Secret shape into a SOPS Secrets Operator style resource. |
| `check-kubernetes-resource-bounds.py` | Requires CPU/memory requests and memory limits on directly authored Kubernetes workloads, and rejects recommendation profiles whose minimum-change threshold can block their maximum decrease step. |
| `check-renovate-policy.py` | Verifies non-critical GitOps dependency coverage and keeps cluster-foundational dependencies under manual upgrade control. |
| `check-postgresql-observability.py` | Uses `promtool` and PyYAML to validate PostgreSQL alerts, small-table thresholds, table overrides, and primary-only evaluation. |
| `check-loki-observability.py` | Uses `promtool` and PyYAML to validate WAL stalls, permanent drops/rejections, immediate loss detection, brief-gap continuity, recovery, counter resets, and missing telemetry. |
| `check-etcd-observability.py` | Validates native etcd alert behavior with `promtool`. |
| `check-cilium-observability.py` | Checks Cilium bootstrap/Fleet value parity and metric alert behavior. |
| `post-node-power-on.sh` | Helper for node power-on recovery or post-power operations. |
| `setup-pre-commit.sh` | Installs the pinned pre-commit Python and native validation tools and configures the Git hook on Linux. |
| `run-pre-commit-validation.sh` | Runs the Ansible, YAML, Kubernetes, Terraform, shell, and Dockerfile checks used by the repository's pre-commit hooks; discovers role regression tests and app tests under Kubernetes project and Fleet bundles. |
| `safe-node-shutdown.sh` | Helper for guarded node shutdown workflows. |
| `sync-readme-versions.py` | Reads pinned platform versions from Git-managed source files and checks or updates the static root README badge values. |
| `validate-tempo.py` | Verifies Tempo configuration and an OTLP trace round trip, then checks the same trace after replacing the container with its data volume retained. |
| `validate-pyroscope.py` | Checks profile ingestion and queries, Raft snapshot/WAL recovery and retained profile history after container replacement in local Docker. |
| `validate-alertmanager-notifications.py` | Checks notification routes, bounded Slack rendering, permanent-loss visibility and real local group-change/repeat behavior without contacting Slack. Can compare a private effective Alertmanager configuration after reconciliation. |

## How These Fit The Lab

Scripts here are supporting tools, not the primary deployment mechanism. Normal
desired state should live in Ansible or Kubernetes manifests. A script belongs
here when it helps with conversion, migration, or controlled operator action.

When a script becomes part of a reconciled workload, move that behavior into the
owning app bundle or Ansible role so it is visible in the desired state.

Run app regression tests with `scripts/run-pre-commit-validation.sh kubernetes-tests`.
The [Infrastructure regressions workflow](../.github/workflows/infrastructure-regressions.yml)
runs this command and the `ansible` command on relevant pushes and pull requests,
using the same pinned validation dependencies. When adding an app suite, include
its source inputs in that workflow's path filters so manifest-only changes run
the suite too.
The hook discovers Python tests in `kubernetes/projects/*/apps/*/tests` and
`kubernetes/fleet/*/tests`; those tests must run without private endpoints,
credentials, or cluster changes.

Standalone Firefly III statement import utilities are maintained in
[`abhi1693/firefly-importer`](https://github.com/abhi1693/firefly-importer).
