# Tempo

Lightweight single-pod Grafana Tempo backend for OpenTelemetry traces.

This is intentionally scoped for home-lab APM:

- one ARM64 pod in `cattle-monitoring-system`;
- `emptyDir` local trace storage capped at `2Gi`;
- 24-hour block retention;
- OTLP gRPC and HTTP receivers for the OpenTelemetry Collector;
- Tempo 3 monolithic mode with a live-store for recent traces and TraceQL metrics,
  plus an in-process metrics-generator for service graphs and span metrics;
- Tempo's built-in MCP server at `http://tempo.home/api/mcp` via Traefik and
  `http://tempo.cattle-monitoring-system.svc.cluster.local:3200/api/mcp`
  in-cluster;
- no external object storage, Kafka, or distributed Tempo components.

The pod requests `60m` CPU and keeps CPU uncapped, matching the observed
trace-ingestion baseline while retaining burst capacity for compaction and
queries.

The live-store uses `/var/tempo/wal`, cuts blocks at `1MiB` or five minutes,
and caps buffered live trace bytes at `10MiB`. The backend scheduler and worker
enforce the 24-hour retention configured in
`overrides.defaults.compaction.block_retention`. All storage remains ephemeral
inside the pod's `2Gi` `emptyDir`; replacing the pod clears its trace history.

Tempo 3 removed `ingester`, `compactor`, metrics-generator `local_blocks`, and
`traces_storage`. Image upgrades must migrate the configuration together. See
the [upstream migration guide](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/migrate-to-3/).

Grafana queries Tempo through the `Tempo` datasource provisioned by the Rancher
Monitoring chart values.

The MCP endpoint uses Tempo's HTTP API and can expose trace data to connected AI
clients. The `tempo-boundary` NetworkPolicy permits OTLP ingestion from the
OpenTelemetry processing tier and Alloy Faro, and port `3200` ingress from
Traefik for `tempo.home`, plus Grafana and Prometheus inside
`cattle-monitoring-system`.

## Validation and deployment

Run the same isolated Docker validation used by the ARM64 `Tempo validation`
GitHub Actions workflow:

```sh
python3 -m pip install --requirement .github/requirements/tempo.txt
python3 scripts/validate-tempo.py
```

The check reads the image, arguments, Go environment, user, and memory limit
from `deployment.yaml`, verifies the actual ConfigMap with that image, waits for
readiness, sends a synthetic OTLP span, and retrieves its trace by ID. It uses
temporary local storage and loopback ports, then removes the container.

For a configuration change, also update `home-lab.io/tempo-config-revision` in
the Deployment to trigger replacement through Fleet. Validate the manifests
with pre-commit and server-side dry runs, require the PR's Tempo validation to
pass, then merge to `master` for Fleet deployment. After reconciliation, confirm
the Tempo endpoint is ready, OpenTelemetry exports succeed, fresh traces are
queryable, and Tempo-related alerts and Fleet dependency errors clear.
