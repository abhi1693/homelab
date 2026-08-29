# Rack Ops Controllers

This bundle runs rack and node automation controllers in the `rack-ops`
namespace. It bridges UPS state, Thanos Query signals, Home Assistant webhooks,
Fleet metadata, and selected Kubernetes workloads.

## Runtime Shape

- Main controller: `rack-ops` Deployment and ClusterIP metrics service
- Placement: the main controller requires an ARM64 worker node; node-local
  shutdown and thermal helpers retain their explicit per-node placement
- State: `rack-ops-state-nfs` RWX PVC, backed by the retained NAS directory
  `rack-ops/rack-ops-state-nfs`, mounted at `/state`
- Policy: `rack-ops-policy` ConfigMap mounted at `/config/policy.yaml`
- Metrics: `ServiceMonitor` and `PrometheusRule` resources
- Secrets: SOPS-managed Home Assistant and registry credentials

The main controller polls deduplicated UPS metrics from Thanos Query every 30
seconds with a 30-second request timeout and applies staged actions when the UPS moves
to battery or low-runtime states. Query failures remain fail-safe and alerting;
the longer bound only tolerates temporary monitoring-storage latency.

## Controlled Actions

The policy stages suspend low-priority CronJobs first, then scale selected
media and public-app workloads down as UPS runtime drops. Restore is gated on
the UPS being online, not on battery, and reporting at least 300 seconds of
runtime. The five-minute reserve remains reachable under the rack's normal load
and avoids leaving shed workloads down indefinitely while the battery recharges.

RBAC is intentionally resource-scoped. The controller can only patch named
Fleet bundles, HelmOps, Deployments, and CronJobs listed in
`rack-ops-rbac.yaml`.

## Node Helpers

The bundle also owns node-local helpers:

- `rpi-shutdown-*` DaemonSets expose guarded shutdown endpoints for individual
  Raspberry Pi nodes. Helpers currently cover `k8s-rpi1` through `k8s-rpi8`.
- `rpi-thermal-governor` caps CPU frequency on selected Raspberry Pi nodes when
  host temperature crosses the configured threshold.

These helpers are privileged because they interact with host power and thermal
state. Keep node selectors and host mounts explicit.

## Network Boundary

The main controller accepts Prometheus scrapes on port `8080`. Egress is limited
to DNS, Thanos Query, Home Assistant, and the Kubernetes API
through a Cilium policy.

## Operating Notes

- Treat this bundle as a safety controller; review policy changes with the same
  care as cluster maintenance automation.
- Keep `dryRun: false` deliberate in `rack-ops-policy.yaml`.
- Advance the Deployment's `home-lab.io/policy-revision` annotation whenever
  the policy changes because the controller reads it only at process startup.
- When adding a target, update both the policy and the matching RBAC allowlist.
- Do not manually patch the live cluster for normal policy changes; encode them
  in Git and let Fleet reconcile.
