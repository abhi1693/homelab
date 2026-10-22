# Tempo

Lightweight single-pod Grafana Tempo backend for OpenTelemetry traces.

This is intentionally scoped for home-lab APM:

- one ARM64 pod in `cattle-monitoring-system`;
- a `2Gi` Longhorn `ReadWriteOnce` PVC for local trace storage;
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
`overrides.defaults.compaction.block_retention`. The `tempo-data` PVC mounts at
`/var/tempo`, preserving recent-trace WAL, completed blocks, the metrics-generator
WAL, and live-store shutdown markers across pod replacement. Retention stays at
24 hours; the `2Gi` filesystem bounds storage, and existing volume-capacity alerts
must be investigated if ingestion outgrows that allocation.

The Deployment remains one replica with `Recreate`, preventing overlapping
writers to the local backend. UID/GID and `fsGroup` remain `10001`; a 120-second
termination grace period lets Tempo flush in-memory traces to WAL before a
planned replacement. Abrupt termination can still lose spans that have not yet
reached WAL. This single-pod backend has a brief ingestion/query interruption
during replacement and is not highly available.

Longhorn's three-replica storage class protects volume data from a replica
failure. It does not provide an independent backup. The PVC has
`helm.sh/resource-policy: keep` so removing the Fleet release retains it.
Explicit PVC deletion still deletes the backing volume because the Longhorn
storage class uses reclaim policy `Delete`. Recovery should reattach the
existing claim with the same paths and compatible Tempo version; never resolve
a mount or rollout error by deleting the claim.

The initial move from `emptyDir` starts a new trace history. Existing files and
representative trace responses are archived privately before that one-time
cutover; they are not automatically imported into the new volume. Subsequent
rollouts preserve history within the configured retention window. See the
[trace/profile storage runbook](../../../../../docs/runbooks/observability-persistence.md)
for staged deployment and recovery checks.

Tempo 3 removed `ingester`, `compactor`, metrics-generator `local_blocks`, and
`traces_storage`. Image upgrades must migrate the configuration together. See
the [upstream migration guide](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/migrate-to-3/).

Grafana queries Tempo through the `Tempo` datasource provisioned by the upstream
kube-prometheus-stack values.

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
readiness, sends a synthetic OTLP span, and retrieves its trace by ID. It then
replaces the container while reusing the same Docker volume, verifies the same
trace after WAL recovery, waits for a completed block to flush, and replaces the
container again before a backend-block-only read. This proves that both WAL and
completed blocks survive. The check uses loopback
ports and an isolated temporary Docker volume, then removes both containers and
volume. The test also requires every configured durable path to remain under
the PVC mount.

For a configuration change, also update `home-lab.io/tempo-config-revision` in
the Deployment to trigger replacement through Fleet. Validate the manifests
with pre-commit and server-side dry runs, require the PR's Tempo validation to
pass, then merge to `master` for Fleet deployment. After reconciliation, confirm
the Tempo endpoint is ready, OpenTelemetry exports succeed, fresh traces are
queryable, and Tempo-related alerts and Fleet dependency errors clear.

Grafana query streaming uses the Tempo HTTP endpoint on port 3200. Enable
`stream_over_http_enabled` in the server configuration so datasource streaming
does not attempt plain gRPC against an HTTP-only listener. Keep the datasource
HTTP URL; OTLP receiver ports are ingestion endpoints, not query endpoints.
Validate both trace-by-ID reads and streaming search after configuration changes.
