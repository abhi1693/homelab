# OpenTelemetry Collector

Small OpenTelemetry Collector for application telemetry.

The collector receives OTLP metrics on `4317` and `4318`, batches them, and
exports them to the Rancher Monitoring Prometheus OTLP endpoint. It also
receives OTLP traces and forwards them to the local Tempo service. Logs are
intentionally not configured yet.

Applications should send metrics to:

- `http://opentelemetry-collector.cattle-monitoring-system.svc.cluster.local:4318`
- `opentelemetry-collector.cattle-monitoring-system.svc.cluster.local:4317`

The collector exposes its own Prometheus metrics on port `8888` and health
checks on port `13133`.
