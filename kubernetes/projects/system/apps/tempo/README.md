# Tempo

Lightweight single-pod Grafana Tempo backend for OpenTelemetry traces.

This is intentionally scoped for home-lab APM:

- one ARM64 pod in `cattle-monitoring-system`;
- `emptyDir` local trace storage capped at `2Gi`;
- 24-hour block retention;
- OTLP gRPC and HTTP receivers for the OpenTelemetry Collector;
- in-process metrics-generator support for Grafana Traces Drilldown TraceQL
  metrics;
- Tempo's built-in MCP server at `http://tempo.home/api/mcp` via Traefik and
  `http://tempo.cattle-monitoring-system.svc.cluster.local:3200/api/mcp`
  in-cluster;
- no external object storage, Kafka, or distributed Tempo components.

Grafana queries Tempo through the `Tempo` datasource provisioned by the Rancher
Monitoring chart values.

The MCP endpoint uses Tempo's HTTP API and can expose trace data to connected AI
clients. The `tempo-boundary` NetworkPolicy permits port `3200` ingress from
Traefik for `tempo.home`, plus Grafana and Prometheus inside
`cattle-monitoring-system`.
