# Home Assistant Status Bridge

This single-purpose bridge converts authoritative Thanos Query data into one
bounded, read-only household status document for Home Assistant. It has no
Kubernetes credentials, no write API and no external ingress.

`GET /status` reports ready/total nodes, non-ready nodes, unavailable workload
resources, actionable Fleet failures, degraded Longhorn volumes, unreachable scrape
targets, active warning/critical alerts and CloudNativePG backup age. Each
problem category includes up to five sorted, deduplicated offender labels so a
human can understand the signal at a glance; deep diagnosis remains in Grafana,
Alertmanager and Rancher. Home Assistant polls the document once per minute.
Fleet `NotReady`, `Pending`, and `WaitApplied` states describe incomplete or
in-progress reconciliation and do not raise this signal; only `ErrApplied`,
`Modified`, and `OutOfSync` are treated as actionable failures.

The bridge distinguishes a healthy zero from missing telemetry. Metric families
that should always exist (Kubernetes, Fleet, Longhorn and scrape targets) are
required, and a missing CloudNativePG backup timestamp makes `/status` return
`503` instead of presenting a misleading zero-hour backup age. Alert results may
legitimately be empty.

NetworkPolicy permits only the Home Assistant Pod to call the bridge and only
the bridge to query the in-cluster Thanos Query Service. Values are cached for
60 seconds, and concurrent readiness/Home Assistant requests share one in-flight
refresh so a slow backend cannot multiply Prometheus load. The fail-closed
snapshot combines its tagged expressions into one Prometheus-compatible request
with a bounded 30-second timeout; readiness allows 90 seconds while liveness
remains isolated on `/healthz`.
